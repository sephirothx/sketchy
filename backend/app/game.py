"""Per-room game state machine: turn rotation, word choice, drawing timer, scoring.

Pure state/logic only (no socket I/O) so it can be unit tested directly.
"""
from __future__ import annotations

import difflib
import random
import re
import string
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from itertools import groupby

from app.words import WORDS, random_word_choices

CHOOSE_WORD_SECONDS = 15
DRAWING_SECONDS = 80
ROUND_END_SECONDS = 5
MIN_GUESS_POINTS = 100
MAX_GUESS_POINTS = 300
MAX_STROKE_RECORDS = 20_000
SCORING_MODES = ("none", "default")

# Hint letters (see Game.reveal_hint_letter / Game.buy_hint_letter / Game.buy_wheel_letter):
# - "checkpoints" reveals letters to everyone at fixed points during drawing.
# - "purchase" lets each guesser spend points to reveal a letter SLOT of their
#   choice, visible only to them.
# - "wheel" (wheel-of-fortune style) lets each guesser spend points to buy a
#   specific LETTER, revealing every occurrence of it (if any) in the word,
#   visible only to them. Unlike "purchase", the cost varies per letter
#   (vowels cost more than consonants, and more common letters across the
#   room's word pool cost more than rare ones) and is charged whether or not
#   the letter turns out to be in the word.
HINT_MODES = ("none", "checkpoints", "purchase", "wheel")
# Each hint a player buys in a turn costs more than the last: 5, 10, 15, ...
HINT_BASE_COST = 12
MIN_HIDDEN_LETTERS = 2

# Wheel-of-fortune letter pricing: a flat base cost depending on whether the
# letter is a vowel or consonant (vowels cost more, since there are only 5 of
# them and they're needed to reveal most of a word), scaled by how common
# that letter is across the room's own word pool (commoner -> pricier, rarer
# -> cheaper, clamped to a sane range so a letter that never appears in any
# candidate word is still worth something small rather than free).
VOWELS = frozenset("aeiou")
WHEEL_VOWEL_BASE_COST = 12
WHEEL_CONSONANT_BASE_COST = 8
WHEEL_MIN_FREQUENCY_MULTIPLIER = 1.0
WHEEL_MAX_FREQUENCY_MULTIPLIER = 3.0

# Close guess detection (see Game.guess_hint):
# - distance 1 (a single insertion/deletion/substitution/transposition) is
#   always considered close.
# - distance >1 and <= CLOSE_GUESS_MAX_DISTANCE is close if the strings are
#   still similar enough overall (difflib ratio).
# - for multi-word answers, words are matched position-independently (as a
#   bag/multiset, so reordered guesses still count) as long as the guess's
#   word count is within 1 of the target's. One or more correct words whose
#   combined length is at least CLOSE_GUESS_MIN_CORRECT_LETTERS letters is
#   flagged separately as a "some words are correct" hint.
CLOSE_GUESS_MAX_DISTANCE = 2
CLOSE_GUESS_SIMILARITY_THRESHOLD = 0.75
CLOSE_GUESS_MIN_CORRECT_LETTERS = 5


class Phase(str, Enum):
    CHOOSING_WORD = "choosing_word"
    DRAWING = "drawing"
    ROUND_END = "round_end"
    GAME_END = "game_end"


def _normalize(text: str) -> str:
    """Collapse whitespace and lowercase, so multi-word expressions match
    regardless of extra/irregular spacing in the guesser's input (e.g. "red  panda")."""
    return " ".join(text.split()).lower()


def _damerau_levenshtein(a: str, b: str) -> int:
    """Damerau-Levenshtein edit distance (optimal string alignment variant):
    minimum single-character insertions, deletions, substitutions, or
    transpositions of two adjacent characters to turn `a` into `b`.

    Counting adjacent transpositions as a single edit (rather than two
    substitutions) matters for a guessing game, since swapped letters are one
    of the most common typos (e.g. "hte" for "the").
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    len_a, len_b = len(a), len(b)
    # Full matrix (rather than a rolling row) since the transposition check
    # needs the row from two steps back, not just the previous one.
    rows = [[0] * (len_b + 1) for _ in range(len_a + 1)]
    for i in range(len_a + 1):
        rows[i][0] = i
    for j in range(len_b + 1):
        rows[0][j] = j
    for i, ch_a in enumerate(a, start=1):
        for j, ch_b in enumerate(b, start=1):
            insert_cost = rows[i][j - 1] + 1
            delete_cost = rows[i - 1][j] + 1
            substitute_cost = rows[i - 1][j - 1] + (ch_a != ch_b)
            best = min(insert_cost, delete_cost, substitute_cost)
            if i > 1 and j > 1 and ch_a == b[j - 2] and a[i - 2] == ch_b:
                best = min(best, rows[i - 2][j - 2] + 1)
            rows[i][j] = best
    return rows[len_a][len_b]


def _is_close_pair(guess: str, target: str) -> bool:
    """Whether `guess` is a near-miss for `target` (already known to differ).

    Very short strings are skipped to avoid trivial/noisy matches (e.g. a
    guess of "a" being "close" to a 3-letter word just by sharing a letter).
    """
    if len(target) < 3 or len(guess) < 2 or guess == target:
        return False
    distance = _damerau_levenshtein(guess, target)
    if distance == 1:
        return True
    if distance <= CLOSE_GUESS_MAX_DISTANCE:
        return difflib.SequenceMatcher(None, guess, target).ratio() >= CLOSE_GUESS_SIMILARITY_THRESHOLD
    return False


@dataclass
class Game:
    turn_order: list[str]
    rounds_total: int = 3
    scoring_mode: str = "default"
    turn_index: int = -1
    phase: Phase = Phase.CHOOSING_WORD
    current_drawer: str | None = None
    word: str | None = None
    word_choices: list[str] = field(default_factory=list)
    correct_guessers: set[str] = field(default_factory=set)
    guess_points: dict[str, int] = field(default_factory=dict)
    guess_times: dict[str, float] = field(default_factory=dict)
    strokes: list[dict] = field(default_factory=list)
    phase_deadline: float | None = None
    used_words: set[str] = field(default_factory=set)
    word_pool: list[str] | None = None
    drawing_seconds: float = DRAWING_SECONDS
    hint_mode: str = "none"
    letter_positions: list[int] = field(default_factory=list)
    revealed_positions: set[int] = field(default_factory=set)
    purchased_hints: dict[str, set[int]] = field(default_factory=dict)  # slot hints ("purchase")
    purchased_letters: dict[str, set[str]] = field(default_factory=dict)  # letter hints ("wheel")

    @property
    def total_turns(self) -> int:
        return self.rounds_total * len(self.turn_order)

    @property
    def round_number(self) -> int:
        if not self.turn_order:
            return 0
        return self.turn_index // len(self.turn_order) + 1

    def is_finished(self) -> bool:
        return self.turn_index + 1 >= self.total_turns

    def add_player_to_rotation(self, token: str) -> None:
        """Add a mid-game player without moving the current turn cursor."""
        if token in self.turn_order:
            return
        current_round = self.round_number
        current_drawer = self.current_drawer
        self.turn_order.append(token)
        if current_drawer in self.turn_order and current_round > 0:
            current_position = self.turn_order.index(current_drawer)
            self.turn_index = (current_round - 1) * len(self.turn_order) + current_position

    def remove_player_from_rotation(self, token: str) -> bool:
        """Remove a player while preserving the current or next turn.

        Returns whether the removed player was the active drawer. In that
        case, the cursor is positioned immediately before the next survivor
        so the caller can start the replacement turn.
        """
        if token not in self.turn_order:
            return False

        old_order = self.turn_order
        removed_position = old_order.index(token)
        current_round = self.round_number
        was_drawer = token == self.current_drawer
        surviving_order = [player_token for player_token in old_order if player_token != token]
        self.turn_order = surviving_order

        if not surviving_order:
            self.current_drawer = None
            return was_drawer

        if was_drawer:
            next_old_position = (removed_position + 1) % len(old_order)
            next_token = old_order[next_old_position]
            next_round = current_round + (next_old_position <= removed_position)
            next_position = surviving_order.index(next_token)
            self.turn_index = (next_round - 1) * len(surviving_order) + next_position - 1
        elif self.current_drawer in surviving_order:
            current_position = surviving_order.index(self.current_drawer)
            self.turn_index = (current_round - 1) * len(surviving_order) + current_position

        return was_drawer

    def set_phase_deadline(self, seconds: float) -> None:
        self.phase_deadline = time.monotonic() + seconds

    def remaining_seconds(self) -> float:
        if self.phase_deadline is None:
            return 0.0
        return max(0.0, self.phase_deadline - time.monotonic())

    def start_next_turn(self, afk_tokens: set[str] | None = None) -> list[str]:
        """Advance to the next drawer and offer word choices."""
        self.turn_index += 1
        if afk_tokens:
            attempts = 0
            while attempts < len(self.turn_order) and self.turn_order[self.turn_index % len(self.turn_order)] in afk_tokens:
                self.turn_index += 1
                attempts += 1
        self.current_drawer = self.turn_order[self.turn_index % len(self.turn_order)]
        self.word = None
        self.word_choices = random_word_choices(3, exclude=self.used_words, pool=self.word_pool)
        self.correct_guessers = set()
        self.guess_points = {}
        self.guess_times = {}
        self.strokes = []
        self.letter_positions = []
        self.revealed_positions = set()
        self.purchased_hints = {}
        self.purchased_letters = {}
        self.phase = Phase.CHOOSING_WORD
        return self.word_choices

    def choose_word(self, token: str, word: str) -> bool:
        if self.phase != Phase.CHOOSING_WORD or token != self.current_drawer:
            return False
        if word not in self.word_choices:
            return False
        self._set_word(word)
        return True

    def force_word_choice(self) -> None:
        if self.phase == Phase.CHOOSING_WORD and self.word_choices:
            self._set_word(self.word_choices[0])

    def _set_word(self, word: str) -> None:
        self.word = word
        self.used_words.add(word)
        self.letter_positions = [i for i, ch in enumerate(word) if ch.isalnum()]
        self.phase = Phase.DRAWING

    def masked_word(
        self,
        token: str | None = None,
        is_spectator: bool = False,
        spectators_see_solution: bool = False,
    ) -> str:
        """Blank out each word's letters/digits into underscores while keeping
        spaces and other special characters (hyphens, apostrophes, etc.)
        visible, so multi-word expressions (e.g. "red panda") and punctuated
        words (e.g. "spider-man") clearly show their structure to guessers.
        Every letter run's count is appended at the end, in order - special
        characters act as boundaries here too, so "spider-man" reports "6 3"
        (one count for "spider", one for "man") - and the blanks themselves
        stay tightly packed with a clear gap between words.

        Letters revealed via checkpoint hints (`revealed_positions`) are shown
        to everyone. Letters a specific player bought - either a slot
        (`purchased_hints`, hint_mode="purchase") or a whole letter
        (`purchased_letters`, hint_mode="wheel") - are only shown when
        `masked_word` is called with that player's token - every other caller
        (including token=None) never sees them.
        """
        if not self.word:
            return ""
        if (is_spectator and spectators_see_solution) or (
            token and (token == self.current_drawer or token in self.correct_guessers)
        ):
            return self.word
        revealed_slots = self.revealed_positions | self.purchased_hints.get(token, set())
        revealed_indices = {
            self.letter_positions[slot] for slot in revealed_slots if slot < len(self.letter_positions)
        }
        bought_letters = self.purchased_letters.get(token, set())
        if bought_letters:
            revealed_indices |= {i for i in self.letter_positions if self.word[i].lower() in bought_letters}
        masked_words = []
        for match in re.finditer(r"\S+", self.word):
            start = match.start()
            masked_words.append(
                "".join(
                    ch if not ch.isalnum() or (start + i) in revealed_indices else "_"
                    for i, ch in enumerate(match.group())
                )
            )
        letter_counts = [
            str(len(list(run)))
            for is_alnum, run in groupby(self.word, key=str.isalnum)
            if is_alnum
        ]
        return "  ".join(masked_words) + "  " + " ".join(letter_counts)

    def max_hint_checkpoints(self) -> int:
        """Calculate the number of timed hint checkpoints for the current word.

        Frequency and amount scale with prompt length (approx ~40% of letters) while
        keeping at least MIN_HIDDEN_LETTERS hidden.
        """
        if not self.word:
            return 0
        total_slots = len(self.letter_positions)
        if total_slots <= MIN_HIDDEN_LETTERS:
            return 0
        max_possible = total_slots - MIN_HIDDEN_LETTERS
        scaled = max(1, round(total_slots * 0.4))
        return min(max_possible, scaled)

    def reveal_hint_letter(self) -> bool:
        """Reveal one more random letter to every player (hint_mode="checkpoints").

        Keeps at least MIN_HIDDEN_LETTERS letters hidden so the word never
        becomes trivially guessable. Returns False if there was nothing left
        to safely reveal.
        """
        if not self.word:
            return False
        available = [
            slot for slot in range(len(self.letter_positions)) if slot not in self.revealed_positions
        ]
        if len(available) <= MIN_HIDDEN_LETTERS:
            return False
        self.revealed_positions.add(random.choice(available))
        return True

    def hint_cost(self, token: str) -> int:
        """Cost in points of the next hint `token` would buy this turn.

        Scales up with each hint the player already bought this turn (5,
        10, 15, ...), so hints stay useful early but can't be spammed cheaply.
        """
        already_bought = len(self.purchased_hints.get(token, set()))
        return HINT_BASE_COST * (already_bought + 1)

    def buy_hint_letter(self, token: str, slot: int) -> bool:
        """Reveal a specific letter slot for `token` only (hint_mode="purchase").

        The caller is responsible for checking/deducting points - this only
        validates and records which slot was unlocked. Returns False if the
        slot is invalid, already revealed (publicly or to this player), or
        the token isn't an eligible guesser right now.
        """
        if self.hint_mode != "purchase" or self.phase != Phase.DRAWING or not self.word:
            return False
        if token == self.current_drawer or token in self.correct_guessers:
            return False
        if slot < 0 or slot >= len(self.letter_positions):
            return False
        if slot in self.revealed_positions:
            return False
        purchased = self.purchased_hints.setdefault(token, set())
        if slot in purchased:
            return False
        purchased.add(slot)
        return True

    def _letter_frequencies(self) -> dict[str, float]:
        """Relative frequency (0-1) of each a-z letter across this game's word
        pool (`word_pool`, or the built-in `WORDS` list when no custom pool is
        set) - used to price wheel-of-fortune letters by how rare they are
        among the actual possible solutions, rather than English-language
        letter frequency.
        """
        pool = self.word_pool or WORDS
        counts = Counter(ch for w in pool for ch in w.lower() if ch.isalpha())
        total = sum(counts.values()) or 1
        return {letter: counts.get(letter, 0) / total for letter in string.ascii_lowercase}

    def letter_price(self, letter: str) -> int:
        """Base cost (before the per-turn escalation in `wheel_hint_cost`) of
        buying `letter` in hint_mode="wheel": a flat vowel/consonant cost,
        scaled up the more common that letter is across `word_pool`/`WORDS`
        (rarer letters are cheaper - revealing every instance of a letter
        that barely appears in the word is worth comparatively little).
        """
        letter = letter.lower()
        base = WHEEL_VOWEL_BASE_COST if letter in VOWELS else WHEEL_CONSONANT_BASE_COST
        frequencies = self._letter_frequencies()
        max_frequency = max(frequencies.values()) or 1e-9
        relative_frequency = frequencies.get(letter, 0.0)
        frequency_multiplier = min(
            WHEEL_MAX_FREQUENCY_MULTIPLIER,
            max(
                WHEEL_MIN_FREQUENCY_MULTIPLIER,
                WHEEL_MIN_FREQUENCY_MULTIPLIER
                + (WHEEL_MAX_FREQUENCY_MULTIPLIER - WHEEL_MIN_FREQUENCY_MULTIPLIER)
                * (relative_frequency / max_frequency),
            ),
        )
        return round(base * frequency_multiplier)

    def wheel_hint_cost(self, token: str, letter: str) -> int:
        """Cost in points for `token` to buy `letter` right now (hint_mode="wheel").

        Like `hint_cost`, scales up with each wheel letter the player already
        bought this turn (so hints stay useful early but can't be spammed
        cheaply), on top of that letter's own base price.
        """
        already_bought = len(self.purchased_letters.get(token, set()))
        return self.letter_price(letter) * (already_bought + 1)

    def wheel_letter_prices(self, token: str) -> dict[str, int]:
        """Current price of every a-z letter `token` hasn't already bought this
        turn (hint_mode="wheel") - sent to the client to render the letter picker.
        """
        bought = self.purchased_letters.get(token, set())
        return {
            letter: self.wheel_hint_cost(token, letter)
            for letter in string.ascii_lowercase
            if letter not in bought
        }

    def buy_wheel_letter(self, token: str, letter: str) -> bool:
        """Buy a whole letter for `token` only (hint_mode="wheel").

        Every occurrence of `letter` in the word will be shown to this player
        (via `masked_word`) regardless of whether it's actually present - the
        caller is responsible for checking/deducting points before calling
        this. Returns False if the letter is invalid, already bought by this
        player this turn, or the token isn't an eligible guesser right now.
        """
        if self.hint_mode != "wheel" or self.phase != Phase.DRAWING or not self.word:
            return False
        if token == self.current_drawer or token in self.correct_guessers:
            return False
        letter = letter.lower()
        if letter not in string.ascii_lowercase:
            return False
        bought = self.purchased_letters.setdefault(token, set())
        if letter in bought:
            return False
        bought.add(letter)
        return True

    def record_stroke(self, event: str, payload: dict) -> bool:
        if len(self.strokes) >= MAX_STROKE_RECORDS:
            return False
        # If the canvas was previously cleared and a new stroke starts, reset pre-clear history.
        if self.strokes and self.strokes[-1]["event"] == "clear_canvas":
            if event == "clear_canvas":
                return True
            self.strokes = []
        self.strokes.append({"event": event, "payload": payload})
        return True

    def clear_canvas_stroke(self) -> bool:
        """Record a clear_canvas event in stroke history, allowing undo to restore pre-clear history."""
        if not self.strokes:
            return False
        if self.strokes[-1]["event"] == "clear_canvas":
            return False
        self.strokes.append({"event": "clear_canvas", "payload": {}})
        return True

    def undo_last_stroke(self) -> bool:
        """Remove the most recent logical stroke or clear event from the recorded history.

        The canvas is a raster (not vector), so "undoing" means dropping the
        last stroke's events from the replay log and having every client
        clear + redraw from what remains (via a fresh sync_strokes). A
        logical stroke is either a single draw_shape/draw_fill/clear_canvas event,
        or a draw_start/draw_move*/draw_end run - so this walks backward from the
        end to find where that run began. Returns False if there was nothing
        to undo.
        """
        if not self.strokes:
            return False
        if self.strokes[-1]["event"] in ("draw_shape", "draw_fill", "clear_canvas"):
            self.strokes.pop()
            return True
        start = len(self.strokes) - 1
        while start >= 0 and self.strokes[start]["event"] != "draw_start":
            start -= 1
        self.strokes = self.strokes[:start] if start >= 0 else self.strokes[:-1]
        return True

    def submit_guess(self, token: str, text: str) -> tuple[bool, int]:
        if self.phase != Phase.DRAWING or not self.word:
            return False, 0
        if token == self.current_drawer or token in self.correct_guessers:
            return False, 0
        normalized_guess = _normalize(text)
        normalized_word = _normalize(self.word)
        if normalized_guess != normalized_word:
            return False, 0
        self.correct_guessers.add(token)
        self.guess_times[token] = max(
            0.0,
            min(self.drawing_seconds, self.drawing_seconds - self.remaining_seconds()),
        )
        if self.scoring_mode == "none":
            self.guess_points[token] = 0
            return True, 0
        remaining_ratio = self.remaining_seconds() / self.drawing_seconds
        points = round(100 + 200 * remaining_ratio)
        self.guess_points[token] = points
        return True, points

    def guess_hint(self, token: str, text: str) -> str | None:
        """Whether a (known-incorrect) guess deserves a private hint instead of
        being silently broadcast to the room as-is.

        Returns "close" if the guess is a near-miss for the whole word/phrase
        (see `_is_close_pair`), "partial" if (for multi-word answers only,
        matching words position-independently and tolerating a word-count
        difference of at most 1) one or more correct words together add up to
        at least `CLOSE_GUESS_MIN_CORRECT_LETTERS` letters, or None if
        neither applies.
        """
        if not self.word:
            return None
        if token == self.current_drawer or token in self.correct_guessers:
            return None
        guess = _normalize(text)
        word = _normalize(self.word)
        if guess == word:
            return None
        if _is_close_pair(guess, word):
            return "close"
        word_tokens = word.split(" ")
        if len(word_tokens) > 1:
            guess_tokens = guess.split(" ")
            if abs(len(guess_tokens) - len(word_tokens)) <= 1:
                # Bag-of-words intersection: matches regardless of word order,
                # capping duplicate words at the lower count on either side.
                overlap = Counter(guess_tokens) & Counter(word_tokens)
                correct_letter_count = sum(len(w) * count for w, count in overlap.items())
                if correct_letter_count >= CLOSE_GUESS_MIN_CORRECT_LETTERS:
                    return "partial"
        return None

    def all_guessed(self, total_guessers: int) -> bool:
        return total_guessers > 0 and len(self.correct_guessers) >= total_guessers

    def end_round(self) -> int | None:
        """Transition to ROUND_END, return drawer bonus points.

        The drawer receives the sum of the points earned by all correct guessers in this round.

        Returns None if the game is no longer drawing, making the transition
        safe when a timeout races the final correct guess.
        """
        if self.phase != Phase.DRAWING:
            return None
        self.phase = Phase.ROUND_END
        return sum(self.guess_points.values())

    def advance_phase_after_round(self) -> Phase:
        self.phase = Phase.GAME_END if self.is_finished() else Phase.CHOOSING_WORD
        return self.phase
