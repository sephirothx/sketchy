"""Per-room game state machine: turn rotation, prompt choice, drawing timer, scoring.

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
from datetime import datetime, timezone
from enum import Enum
from itertools import groupby
from typing import Mapping, Sequence

from app.canvas_session import CanvasSession
from app.drawing_rules import (
    DEFAULT_ALLOWED_TOOLS,
    DEFAULT_COLOR_MODE,
    allowed_colors,
)
from app.domain_values import (
    GamePromptSourceMode,
    PromptSourceKind,
    TurnEligibilityReason,
    TurnEndReason,
    TurnParticipantOutcome,
)
from app.identifiers import generate_uuid7
from app.prompts import MAX_PROMPT_LENGTH, PROMPTS
from app.prompt_content import prompt_match_key

# How many prompts a drawer chooses between each turn. The pre-drawn sample
# is sized off this, so the two must not drift apart.
PROMPT_CHOICES_PER_TURN = 3
DRAWING_SECONDS = 80
# The phase lengths live on `app.flow_timing.timing`, because a constant
# imported by name is copied at import and cannot be tuned at runtime (#446).
MIN_GUESS_POINTS = 100
MAX_GUESS_POINTS = 300
# Bump this whenever any parameter or algorithm that can change a score changes.
SCORING_RULES_VERSION = 1
# Bump this only when the stored rule-snapshot JSON contract changes.
GAME_RULE_SNAPSHOT_VERSION = 1


def competition_ranks(sorted_scores: Sequence[int]) -> list[int]:
    """Places for scores already ordered best-first, ties sharing a place.

    Standard competition ranking: equal scores take the same place, and the
    places they crowd out are skipped - 1, 2, 2, 4, never 1, 2, 2, 3. Two
    players who finish level did not finish first and second, and the one
    behind them came third by count of people ahead, not by row number.

    Kept here rather than beside either caller because both the live standings
    and the recorded ones have to agree: a game whose final screen says two
    players tied for first must not be written down as a first and a second.
    """
    ranks: list[int] = []
    for index, score in enumerate(sorted_scores):
        if index > 0 and score == sorted_scores[index - 1]:
            ranks.append(ranks[-1])
        else:
            ranks.append(index + 1)
    return ranks

# A turn's hint spend is settled against that turn's guess, so committing more
# than the best possible guess is worth would just be an unpayable debt. Cap it
# there: the worst a turn can do is come out at zero, never below. In practice
# the escalating per-hint price binds first (12 + 24 + 36 + ... = 252 after
# six), so this is a safety rail rather than a balance lever.
MAX_HINT_SPEND = MAX_GUESS_POINTS

# "pressure" mode: starts from the same MAX_GUESS_POINTS baseline as default
# scoring, but points bleed away as a percentage of what is still on the table,
# and the bleed rate doubles once someone gets the prompt. The per-second rate is
# derived from the room's own drawing time so the curve has the same shape in a
# 15s room and a 300s one -- unpressured, a correct guess late in the turn is
# always worth the same share of the maximum, until PRESSURE_MIN_POINTS takes
# over in the last moments.
PRESSURE_MAX_POINTS = MAX_GUESS_POINTS
PRESSURE_DECAY_PER_SECOND = 0.98  # measured at PRESSURE_REFERENCE_SECONDS
PRESSURE_REFERENCE_SECONDS = 90.0
PRESSURE_MULTIPLIER = 2.0  # applies once anyone has guessed correctly
# Under the multiplier the accumulated decay time overshoots the reference
# length, so the raw curve bottoms out near zero. Floor it: being last should
# sting, not make a correct guess worthless. The floor guarantees the gross
# award only - this turn's hint spend is settled after it, so a heavily hinted
# last-place guess can still come out at zero.
PRESSURE_MIN_POINTS = 50

# Hint letters (see Game.reveal_hint_letter / Game.buy_hint_letter / Game.buy_wheel_letter):
# - "checkpoints" reveals letters to everyone at fixed points during drawing.
# - "purchase" lets each guesser spend points to reveal a letter SLOT of their
#   choice, visible only to them.
# - "wheel" (wheel-of-fortune style) lets each guesser spend points to buy a
#   specific LETTER, revealing every occurrence of it (if any) in the prompt,
#   visible only to them. Unlike "purchase", the cost varies per letter
#   (vowels cost more than consonants, and more common letters across the
#   room's prompt pool cost more than rare ones) and is charged whether or not
#   the letter turns out to be in the prompt.
# Each hint a player buys in a turn costs more than the last: 12, 24, 36, ...
HINT_BASE_COST = 12
MIN_HIDDEN_LETTERS = 2

# Wheel-of-fortune letter pricing: a flat base cost depending on whether the
# letter is a vowel or consonant (vowels cost more, since there are only 5 of
# them and they're needed to reveal most of a prompt), scaled by how common
# that letter is across the room's own prompt pool (commoner -> pricier, rarer
# -> cheaper, clamped to a sane range so a letter that never appears in any
# candidate prompt is still worth something small rather than free).
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
# - for multi-word prompts, words are matched position-independently (as a
#   bag/multiset, so reordered guesses still count) as long as the guess's
#   word count is within 1 of the target's. One or more correct words whose
#   combined length is at least CLOSE_GUESS_MIN_CORRECT_LETTERS letters is
#   flagged separately as a "some words are correct" hint.
CLOSE_GUESS_MAX_DISTANCE = 2
CLOSE_GUESS_SIMILARITY_THRESHOLD = 0.75
CLOSE_GUESS_MIN_CORRECT_LETTERS = 5


class Phase(str, Enum):
    CHOOSING_PROMPT = "choosing_prompt"
    DRAWING = "drawing"
    TURN_RESULTS = "turn_results"
    GAME_END = "game_end"


def _normalize(text: str, language: str = "en") -> str:
    """Normalize guesses while preserving letters without canonical ASCII forms.

    Whitespace and case differences are ignored as before. Canonically
    decomposable diacritics are stripped so, for example, "è" matches "e".
    Letters such as "ø" and "ł" remain distinct because Unicode NFD does not
    decompose them into ASCII letters.
    """
    return prompt_match_key(text, language)


def _bounded_damerau_levenshtein(a: str, b: str, max_distance: int) -> int:
    """Bounded Damerau-Levenshtein distance (optimal string alignment variant).

    Returns ``max_distance + 1`` when the distance exceeds the requested
    bound. Only the diagonal band that could still produce an in-bound result
    is evaluated, and only three sparse rows are retained for adjacent
    transpositions.

    The distance counts single-character insertions, deletions, substitutions, or
    transpositions of two adjacent characters to turn `a` into `b`.

    Counting adjacent transpositions as a single edit (rather than two
    substitutions) matters for a guessing game, since swapped letters are one
    of the most common typos (e.g. "hte" for "the").
    """
    over_limit = max_distance + 1
    if a == b:
        return 0
    if abs(len(a) - len(b)) > max_distance:
        return over_limit
    if not a:
        return len(b) if len(b) <= max_distance else over_limit
    if not b:
        return len(a) if len(a) <= max_distance else over_limit
    len_b = len(b)

    previous_previous: dict[int, int] = {}
    previous = {j: j for j in range(min(len_b, max_distance) + 1)}
    for i, ch_a in enumerate(a, start=1):
        current: dict[int, int] = {}
        first_column = max(0, i - max_distance)
        last_column = min(len_b, i + max_distance)
        if first_column == 0:
            current[0] = i
        for j in range(max(1, first_column), last_column + 1):
            ch_b = b[j - 1]
            insert_cost = current.get(j - 1, over_limit) + 1
            delete_cost = previous.get(j, over_limit) + 1
            substitute_cost = previous.get(j - 1, over_limit) + (ch_a != ch_b)
            best = min(insert_cost, delete_cost, substitute_cost)
            if i > 1 and j > 1 and ch_a == b[j - 2] and a[i - 2] == ch_b:
                best = min(best, previous_previous.get(j - 2, over_limit) + 1)
            current[j] = min(best, over_limit)
        previous_previous, previous = previous, current
    return previous.get(len_b, over_limit)


def _is_close_pair(guess: str, target: str) -> bool:
    """Whether `guess` is close to `target` (already known to differ).

    Very short strings are skipped to avoid trivial/noisy matches (e.g. a
    guess of "a" being "close" to a 3-letter word just by sharing a letter).
    """
    if len(target) < 3 or len(guess) < 2 or guess == target:
        return False
    if abs(len(guess) - len(target)) > CLOSE_GUESS_MAX_DISTANCE:
        return False
    distance = _bounded_damerau_levenshtein(
        guess,
        target,
        CLOSE_GUESS_MAX_DISTANCE,
    )
    if distance == 1:
        return True
    if distance <= CLOSE_GUESS_MAX_DISTANCE:
        return difflib.SequenceMatcher(None, guess, target).ratio() >= CLOSE_GUESS_SIMILARITY_THRESHOLD
    return False


@dataclass(frozen=True)
class TurnGuessRecord:
    """One correct guess, kept after the turn that produced it has ended."""

    token: str
    points_awarded: int
    guess_time_seconds: float
    # Compatibility scoring detail duplicated from the parent participant
    # outcome. `points_awarded` is already net of settled hint spend.
    hints_used: int = 0
    points_spent_on_hints: int = 0
    wrong_guesses_before: int = 0


@dataclass(frozen=True)
class TurnParticipantOutcomeRecord:
    """One factual seat's eligibility and terminal result for a turn."""

    token: str
    eligible: bool
    eligibility_reason: str
    outcome: str
    terminal_state: str
    correct_guess_time_seconds: float | None = None
    wrong_guess_count: int = 0
    near_miss_count: int = 0
    hints_used: int = 0
    points_spent_on_hints: int = 0


@dataclass(frozen=True)
class CompletedTurnStats:
    """Everything a finished turn is worth remembering.

    Snapshotted in `end_turn` because `start_next_turn` clears the drawer,
    `guess_points`, and `guess_times` on the way to the next turn - by game end
    only the final turn would still be readable off the live `Game`, which is
    not enough to record a game's history.
    """

    round_number: int
    turn_number: int
    offered_prompts: list[str]
    chosen_prompt: str
    correct_guess_count: int
    # Who could still have guessed. Without it, "two players guessed" could
    # equally mean two out of two or two out of eight.
    total_guesser_count: int
    # Allocated when the live turn starts so messages written during play and
    # the eventual history row share one durable UUIDv7 correlation key.
    id: str = ""
    # Source identity is recorded alongside display snapshots. ``None`` means
    # an ephemeral room custom prompt and must never enter curated projections.
    offered_prompt_version_ids: tuple[str | None, ...] = ()
    offered_prompt_source_kinds: tuple[str, ...] = ()
    offered_prompt_source_revision_ids: tuple[tuple[str, ...], ...] = ()
    chosen_prompt_version_id: str | None = None
    drawer_token: str = ""
    # Real elapsed drawing time, not the configured limit: a turn ends as soon
    # as everyone has guessed.
    duration_seconds: float = 0.0
    guesses: tuple[TurnGuessRecord, ...] = ()
    # The drawer ran out of time and took the first offered prompt, rather than
    # picking one - which is not a preference, and should not read as one.
    prompt_auto_picked: bool = False
    # Canvas actions committed during the turn. Separates a prompt nobody could
    # guess from a drawer who drew nothing.
    stroke_count: int = 0
    # "all_guessed" or "timeout". A turn the drawer abandons never completes,
    # so it is never recorded and cannot appear here.
    end_reason: str = TurnEndReason.TIMEOUT.value
    wrong_guess_count: int = 0
    near_miss_count: int = 0
    # Everyone still in the rotation as the turn ended, which is what makes a
    # player who quit after one turn distinguishable from one who played on.
    present_tokens: tuple[str, ...] = ()
    participant_outcomes: tuple[TurnParticipantOutcomeRecord, ...] = ()


@dataclass
class Game:
    turn_order: list[str]
    id: str = field(default_factory=lambda: str(generate_uuid7()))
    rounds_total: int = 3
    # The seat count the room advertised, which bounds how long this game can
    # run. `None` leaves the game unbounded, which is what tests constructing a
    # bare `Game` want; `_start_fresh_game` always passes the room's setting.
    max_players: int | None = None
    # Turns actually started. Unlike `turn_index`, which is re-based when the
    # roster changes, this only ever goes up - see `max_turns`.
    turns_started: int = 0
    scoring_mode: str = "default"
    scoring_version: int = SCORING_RULES_VERSION
    turn_index: int = -1
    current_turn_id: str | None = None
    phase: Phase = Phase.CHOOSING_PROMPT
    current_drawer: str | None = None
    prompt: str | None = None
    prompt_choices: list[str] = field(default_factory=list)
    correct_guessers: set[str] = field(default_factory=set)
    guess_points: dict[str, int] = field(default_factory=dict)
    guess_times: dict[str, float] = field(default_factory=dict)
    # "pressure" scoring accumulator: elapsed drawing seconds weighted by the
    # multiplier in force for each stretch, plus the elapsed reading at the
    # last advance. Never read outside pressure mode.
    decay_time: float = 0.0
    decay_marker_elapsed: float = 0.0
    canvas: CanvasSession = field(default_factory=CanvasSession)
    phase_deadline: float | None = None
    used_prompts: set[str] = field(default_factory=set)
    # The prompts this game can play: a sample drawn once at start, holding at
    # most `rounds x max_players x 3` entries rather than every prompt the
    # room's lists contain. `None` means the built-in list.
    prompt_pool: list[str] | None = None
    # How often each a-z letter appears across the pool this sample was drawn
    # from, summed from the pinned revisions. Empty means "count `prompt_pool`
    # instead", which is what the built-in and quick-prompt-only paths do -
    # pricing a 72-prompt sample as though it were the whole pool would make
    # rare letters swing on the luck of one draw.
    letter_counts: dict[str, int] = field(default_factory=dict, repr=False)
    letter_total: int = 0
    # Aliases belong to the exact localized prompt versions resolved when the
    # game starts. They never alter the canonical answer shown in the UI or
    # frozen into history.
    prompt_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    prompt_language: str = "en"
    prompt_source_revision_ids: tuple[str, ...] = ()
    prompt_version_ids: dict[str, str] = field(default_factory=dict)
    prompt_source_revision_ids_by_answer: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    custom_prompt_keys: frozenset[str] = frozenset()
    # Where this game's prompts come from, decided from the room's settings.
    # Empty means "work it out from the pool", which is what a bare `Game` in a
    # test wants; `_start_fresh_game` always passes the room's own answer.
    prompt_source_mode_value: str = ""
    drawing_seconds: float = DRAWING_SECONDS
    hint_mode: str = "none"
    hide_masked_prompt: bool = False
    # Frozen at game start: room settings can outlive this game and must never
    # reinterpret its drawing record after they change.
    allowed_tools: tuple[str, ...] = DEFAULT_ALLOWED_TOOLS
    color_mode: str = DEFAULT_COLOR_MODE
    letter_positions: list[int] = field(default_factory=list)
    revealed_positions: set[int] = field(default_factory=set)
    purchased_hints: dict[str, set[int]] = field(default_factory=dict)  # slot hints ("purchase")
    purchased_letters: dict[str, set[str]] = field(default_factory=dict)  # letter hints ("wheel")
    # Per-turn accounting, also kept for the game record. Hints are bought on
    # credit: nothing is charged up front, and `submit_guess` settles the whole
    # turn's spend against the points that turn's correct guess earns.
    hint_spend: dict[str, int] = field(default_factory=dict)
    hint_purchases: dict[str, int] = field(default_factory=dict)
    wrong_guesses: dict[str, int] = field(default_factory=dict)
    near_misses: dict[str, int] = field(default_factory=dict)
    # Snapshotted when drawing begins. None exists only in direct domain tests
    # and pre-snapshot compatibility paths; an empty dict means nobody may
    # guess. Later joiners are added explicitly as joined_late.
    turn_eligibility_reasons: dict[str, str] | None = None
    prompt_auto_picked: bool = False
    completed_turns: list[CompletedTurnStats] = field(default_factory=list)
    # Wall clock, unlike the monotonic `phase_deadline`: persisted game records
    # need a real timestamp, and a monotonic reading means nothing outside this
    # process.
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def rule_snapshot(self) -> dict[str, object]:
        """Return the versioned parameters needed to interpret this game's facts."""
        permitted_colors = allowed_colors(self.color_mode)
        return {
            "schemaVersion": GAME_RULE_SNAPSHOT_VERSION,
            "scoring": {
                "mode": self.scoring_mode,
                "version": self.scoring_version,
                "default": {
                    "minimumGuessPoints": MIN_GUESS_POINTS,
                    "maximumGuessPoints": MAX_GUESS_POINTS,
                    "algorithm": "linear_remaining_time",
                },
                "pressure": {
                    "maximumGuessPoints": PRESSURE_MAX_POINTS,
                    "minimumGuessPoints": PRESSURE_MIN_POINTS,
                    "decayPerReferenceSecond": PRESSURE_DECAY_PER_SECOND,
                    "referenceSeconds": PRESSURE_REFERENCE_SECONDS,
                    "postGuessMultiplier": PRESSURE_MULTIPLIER,
                },
                "drawerBonus": "sum_net_correct_guess_points",
            },
            "hints": {
                "mode": self.hint_mode,
                "minimumHiddenLetters": MIN_HIDDEN_LETTERS,
                "escalatingBaseCost": HINT_BASE_COST,
                "maximumSpendPerTurn": MAX_HINT_SPEND,
                "wheel": {
                    "vowelBaseCost": WHEEL_VOWEL_BASE_COST,
                    "consonantBaseCost": WHEEL_CONSONANT_BASE_COST,
                    "minimumFrequencyMultiplier": WHEEL_MIN_FREQUENCY_MULTIPLIER,
                    "maximumFrequencyMultiplier": WHEEL_MAX_FREQUENCY_MULTIPLIER,
                },
            },
            "drawing": {
                "seconds": self.drawing_seconds,
                "allowedTools": list(self.allowed_tools),
                "colorMode": self.color_mode,
                "allowedColors": (
                    list(permitted_colors) if permitted_colors is not None else None
                ),
            },
            "prompt": {
                "language": self.prompt_language,
                "hideMaskedPrompt": self.hide_masked_prompt,
                "sourceRevisionIds": list(self.prompt_source_revision_ids),
            },
        }

    def prompt_source_kind(self, answer: str) -> str:
        if self.prompt_version_ids.get(answer) is not None:
            return PromptSourceKind.CURATED.value
        if _normalize(answer, self.prompt_language) in self.custom_prompt_keys:
            return PromptSourceKind.CUSTOM.value
        return PromptSourceKind.BUILTIN_FALLBACK.value

    def prompt_source_mode(self) -> str:
        """Where this game's prompts came from, as recorded in its history.

        Read from the room's settings rather than from the prompts on hand: the
        pool is a sample, and a mixed room that happened to draw no quick
        prompts would otherwise be filed for good as a purely curated game.
        """
        if self.prompt_source_mode_value:
            return self.prompt_source_mode_value
        pool = self.prompt_pool if self.prompt_pool is not None else PROMPTS
        kinds = {self.prompt_source_kind(answer) for answer in pool}
        if kinds == {PromptSourceKind.CURATED.value}:
            return GamePromptSourceMode.CURATED.value
        if kinds == {PromptSourceKind.CUSTOM.value}:
            return GamePromptSourceMode.CUSTOM.value
        if len(kinds) > 1:
            return GamePromptSourceMode.MIXED.value
        return GamePromptSourceMode.BUILTIN_FALLBACK.value
    # Every token that was ever in the rotation, including players who have
    # since left. `turn_order` shrinks on departure, so it cannot answer "who
    # played this game?" once the game is over.
    roster: list[str] = field(default_factory=list)
    history_seat_ids: dict[str, str] = field(default_factory=dict)
    _cached_letter_frequencies: dict[str, float] | None = field(default=None, repr=False, compare=False)
    # The sample, shuffled and handed out three at a time. Filled on the first
    # turn rather than at construction, so callers may still set `prompt_pool`
    # on a freshly built game. Offers used to be resampled per turn against the
    # picked ones, which could re-offer a prompt the drawer had already
    # declined; taking them in order cannot.
    _prompt_queue: list[str] = field(default_factory=list, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.max_players is not None:
            # Seating caps `turn_order` at `max_players`, so this only guards
            # against a caller passing a ceiling below the roster it handed us -
            # which would otherwise finish the game before its first turn.
            self.max_players = max(self.max_players, len(self.turn_order))
        for token in self.turn_order:
            if token not in self.roster:
                self.roster.append(token)
            self.history_seat_ids.setdefault(token, str(generate_uuid7()))

    @property
    def total_turns(self) -> int:
        return self.rounds_total * len(self.turn_order)

    @property
    def round_number(self) -> int:
        if not self.turn_order:
            return 0
        return self.turn_index // len(self.turn_order) + 1

    @property
    def max_turns(self) -> int | None:
        """Hard ceiling on turns started, or `None` when the game is unbounded.

        `total_turns` is derived from `turn_index`, which is *re-based* rather
        than incremented when a player joins or leaves the rotation. Those
        re-bases can move it backwards, replaying turn slots, so a room with
        mid-game churn can run past the length it advertised. `turns_started`
        only ever goes up, which makes `rounds x max_players` a ceiling the
        prompt sample can be sized against rather than an estimate.
        """
        if self.max_players is None:
            return None
        return self.rounds_total * self.max_players

    def is_finished(self) -> bool:
        ceiling = self.max_turns
        if ceiling is not None and self.turns_started >= ceiling:
            return True
        return self.turn_index + 1 >= self.total_turns

    def add_player_to_rotation(self, token: str) -> None:
        """Add a mid-game player without moving the current turn cursor."""
        if token in self.turn_order:
            return
        if token not in self.roster:
            self.roster.append(token)
        self.history_seat_ids.setdefault(token, str(generate_uuid7()))
        if (
            self.phase == Phase.DRAWING
            and self.turn_eligibility_reasons is not None
            and token != self.current_drawer
        ):
            # A seat that arrives mid-drawing joins the turn's guesser
            # population rather than sitting the turn out: it can see the
            # canvas and the masked prompt, so refusing its guesses would only
            # mean typing into a chat nobody but the drawer reads. The turn
            # therefore also waits on it, and its outcome is recorded like any
            # other guesser's - late arrival is not a reason to be ineligible.
            self.turn_eligibility_reasons.setdefault(
                token, TurnEligibilityReason.ELIGIBLE.value
            )
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

    def elapsed_drawing_seconds(self) -> float:
        """How far into the drawing phase we are, clamped to the turn."""
        return max(
            0.0,
            min(self.drawing_seconds, self.drawing_seconds - self.remaining_seconds()),
        )

    def _pressure_rate(self) -> float:
        """Per-second decay factor, scaled so the curve keeps its shape in any
        room length: PRESSURE_DECAY_PER_SECOND is the rate at a
        PRESSURE_REFERENCE_SECONDS turn, and shorter turns burn faster."""
        return PRESSURE_DECAY_PER_SECOND ** (
            PRESSURE_REFERENCE_SECONDS / self.drawing_seconds
        )

    def _pressure_multiplier(self) -> float:
        return PRESSURE_MULTIPLIER if self.correct_guessers else 1.0

    def _advance_decay_clock(self) -> None:
        """Bank the time since the last advance at the multiplier in force for it.

        Called just before a guesser joins `correct_guessers`, so each stretch
        is charged at the rate that actually applied during it.
        """
        elapsed = self.elapsed_drawing_seconds()
        self.decay_time += (
            max(0.0, elapsed - self.decay_marker_elapsed) * self._pressure_multiplier()
        )
        self.decay_marker_elapsed = elapsed

    def start_next_turn(
        self,
        afk_tokens: set[str] | None = None,
        *,
        canvas_generation: int,
    ) -> list[str]:
        """Advance to the next drawer and offer prompt choices."""
        self.turns_started += 1
        self.turn_index += 1
        if afk_tokens:
            attempts = 0
            while attempts < len(self.turn_order) and self.turn_order[self.turn_index % len(self.turn_order)] in afk_tokens:
                self.turn_index += 1
                attempts += 1
        self.current_drawer = self.turn_order[self.turn_index % len(self.turn_order)]
        self.current_turn_id = str(generate_uuid7())
        self.prompt = None
        self.prompt_choices = self._next_prompt_choices()
        self.correct_guessers = set()
        self.guess_points = {}
        self.guess_times = {}
        self.decay_time = 0.0
        self.decay_marker_elapsed = 0.0
        self.canvas = CanvasSession(
            revision=self.canvas.revision + 1,
            generation=canvas_generation,
        )
        self.letter_positions = []
        self.revealed_positions = set()
        self.purchased_hints = {}
        self.purchased_letters = {}
        self.hint_spend = {}
        self.hint_purchases = {}
        self.wrong_guesses = {}
        self.near_misses = {}
        self.turn_eligibility_reasons = None
        self.prompt_auto_picked = False
        self.phase = Phase.CHOOSING_PROMPT
        return self.prompt_choices

    def choose_prompt(self, token: str, prompt: str) -> bool:
        if self.phase != Phase.CHOOSING_PROMPT or token != self.current_drawer:
            return False
        if prompt not in self.prompt_choices:
            return False
        self._set_prompt(prompt)
        return True

    def force_prompt_choice(self) -> None:
        if self.phase == Phase.CHOOSING_PROMPT and self.prompt_choices:
            self.prompt_auto_picked = True
            self._set_prompt(self.prompt_choices[0])

    def _shuffled_pool(self) -> list[str]:
        pool = list(self.prompt_pool) if self.prompt_pool else list(PROMPTS)
        random.shuffle(pool)
        return pool

    def _next_prompt_choices(self) -> list[str]:
        """Take the next three prompts, refilling from the pool if they run out.

        The sample is sized to outlast the game, so refilling only happens when
        the pool itself is smaller than the game is long - a room playing off a
        handful of quick prompts. Prompts already picked are held back first,
        and only offered again once nothing else is left, which is the
        degradation short pools have always had.
        """
        choices: list[str] = []
        while len(choices) < PROMPT_CHOICES_PER_TURN:
            if not self._prompt_queue:
                remaining = [
                    prompt
                    for prompt in self._shuffled_pool()
                    if prompt not in self.used_prompts and prompt not in choices
                ]
                self._prompt_queue = remaining or [
                    prompt
                    for prompt in self._shuffled_pool()
                    if prompt not in choices
                ]
                if not self._prompt_queue:
                    break
            choices.append(self._prompt_queue.pop())
        return choices

    def _set_prompt(self, prompt: str) -> None:
        self.prompt = prompt
        self.used_prompts.add(prompt)
        self.letter_positions = [i for i, ch in enumerate(prompt) if ch.isalnum()]
        self.phase = Phase.DRAWING

    def snapshot_turn_participants(self, reasons: Mapping[str, str]) -> None:
        """Freeze who may guess and why every other current seat may not.

        Seats arriving after this point are added by `add_player_to_rotation`.
        """
        if self.phase != Phase.DRAWING:
            raise ValueError("Turn participation can only be snapshotted while drawing")
        self.turn_eligibility_reasons = dict(reasons)

    def is_turn_eligible(self, token: str) -> bool:
        """Whether this seat may guess this turn.

        The population is frozen when drawing begins and only ever grows, by
        seats that join mid-turn (`add_player_to_rotation`). Seats that were
        AFK or disconnected at that instant stay out for the rest of the turn.
        """
        if self.turn_eligibility_reasons is None:
            return token != self.current_drawer
        return (
            self.turn_eligibility_reasons.get(token)
            == TurnEligibilityReason.ELIGIBLE.value
        )

    @property
    def near_miss_count(self) -> int:
        """Compatibility aggregate; durable outcomes retain the per-seat split."""
        return sum(self.near_misses.values())

    def masked_prompt(
        self,
        token: str | None = None,
        is_spectator: bool = False,
        spectators_see_prompt: bool = False,
    ) -> str:
        """Blank out each prompt's letters/digits into underscores while keeping
        spaces and other special characters (hyphens, apostrophes, etc.)
        visible, so multi-word entries (e.g. "red panda") and punctuated
        words (e.g. "spider-man") clearly show their structure to guessers.
        Every letter run's count is appended at the end, in order - special
        characters act as boundaries here too, so "spider-man" reports "6 3"
        (one count for "spider", one for "man") - and the blanks themselves
        stay tightly packed with a clear gap between words.

        Letters revealed via checkpoint hints (`revealed_positions`) are shown
        to everyone. Letters a specific player bought - either a slot
        (`purchased_hints`, hint_mode="purchase") or a whole letter
        (`purchased_letters`, hint_mode="wheel") - are only shown when
        `masked_prompt` is called with that player's token - every other caller
        (including token=None) never sees them.
        """
        if not self.prompt:
            return ""
        if (is_spectator and spectators_see_prompt) or (
            token and (token == self.current_drawer or token in self.correct_guessers)
        ):
            return self.prompt
        if self.hide_masked_prompt:
            return "???"
        revealed_slots = self.revealed_positions | self.purchased_hints.get(token, set())
        revealed_indices = {
            self.letter_positions[slot] for slot in revealed_slots if slot < len(self.letter_positions)
        }
        bought_letters = self.purchased_letters.get(token, set())
        if bought_letters:
            revealed_indices |= {i for i in self.letter_positions if self.prompt[i].lower() in bought_letters}
        masked_words = []
        for match in re.finditer(r"\S+", self.prompt):
            start = match.start()
            masked_words.append(
                "".join(
                    ch if not ch.isalnum() or (start + i) in revealed_indices else "_"
                    for i, ch in enumerate(match.group())
                )
            )
        letter_counts = [
            str(len(list(run)))
            for is_alnum, run in groupby(self.prompt, key=str.isalnum)
            if is_alnum
        ]
        return "  ".join(masked_words) + "  " + " ".join(letter_counts)

    def max_hint_checkpoints(self) -> int:
        """Calculate the number of timed hint checkpoints for the current prompt.

        Frequency and amount scale with prompt length (approx ~40% of letters) while
        keeping at least MIN_HIDDEN_LETTERS hidden.
        """
        if not self.prompt:
            return 0
        total_slots = len(self.letter_positions)
        if total_slots <= MIN_HIDDEN_LETTERS:
            return 0
        max_possible = total_slots - MIN_HIDDEN_LETTERS
        scaled = max(1, round(total_slots * 0.4))
        return min(max_possible, scaled)

    def reveal_hint_letter(self) -> bool:
        """Reveal one more random letter to every player (hint_mode="checkpoints").

        Keeps at least MIN_HIDDEN_LETTERS letters hidden so the prompt never
        becomes trivially guessable. Returns False if there was nothing left
        to safely reveal.
        """
        if not self.prompt:
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

        Scales up with each hint the player already bought this turn (12,
        24, 36, ...), so hints stay useful early but can't be spammed cheaply.
        """
        already_bought = len(self.purchased_hints.get(token, set()))
        return HINT_BASE_COST * (already_bought + 1)

    def buy_hint_letter(self, token: str, slot: int) -> bool:
        """Reveal a specific letter slot for `token` only (hint_mode="purchase").

        Nothing is charged here or by the caller: the price is added to this
        turn's `hint_spend`, which `submit_guess` settles against the points a
        correct guess earns. Returns False if the slot is invalid, already
        revealed (publicly or to this player), the token isn't an eligible
        guesser right now, or the price would take the turn's spend past
        MAX_HINT_SPEND.
        """
        if self.hint_mode != "purchase" or self.phase != Phase.DRAWING or not self.prompt:
            return False
        if not self.is_turn_eligible(token) or token in self.correct_guessers:
            return False
        if slot < 0 or slot >= len(self.letter_positions):
            return False
        if slot in self.revealed_positions:
            return False
        purchased = self.purchased_hints.setdefault(token, set())
        if slot in purchased:
            return False
        # Read the price before the purchase moves it, so the debt recorded
        # here is the one the player was quoted.
        cost = self.hint_cost(token)
        if cost > self.hint_spend_remaining(token):
            return False
        self._record_hint_spend(token, cost)
        purchased.add(slot)
        return True

    def _letter_frequencies(self) -> dict[str, float]:
        """Relative frequency (0-1) of each a-z letter across the prompts this
        game could have drawn - used to price wheel-of-fortune letters by how
        rare they are among the actual possible solutions, rather than
        English-language letter frequency.

        `letter_counts` carries that distribution when the game drew from
        prompt lists, because `prompt_pool` is then only a sample of them and
        counting it would price rare letters off a few dozen words. Without it
        the pool *is* everything the game can play - the built-in list, or a
        room's own quick prompts - and counting it is exact.
        """
        if self._cached_letter_frequencies is not None:
            return self._cached_letter_frequencies
        if self.letter_total:
            counts = self.letter_counts
            total = self.letter_total
        else:
            pool = self.prompt_pool or PROMPTS
            counts = Counter(ch for w in pool for ch in w.lower() if ch.isalpha())
            total = sum(counts.values()) or 1
        self._cached_letter_frequencies = {letter: counts.get(letter, 0) / total for letter in string.ascii_lowercase}
        return self._cached_letter_frequencies

    def letter_price(self, letter: str) -> int:
        """Base cost (before the per-turn escalation in `wheel_hint_cost`) of
        buying `letter` in hint_mode="wheel": a flat vowel/consonant cost,
        scaled up the more common that letter is across `prompt_pool`/`PROMPTS`
        (rarer letters are cheaper - revealing every instance of a letter
        that barely appears in the prompt is worth comparatively little).
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

        Every occurrence of `letter` in the prompt will be shown to this player
        (via `masked_prompt`) regardless of whether it's actually present, and
        the price is charged either way - on credit, like `buy_hint_letter`.
        Returns False if the letter is invalid, already bought by this player
        this turn, the token isn't an eligible guesser right now, or the price
        would take the turn's spend past MAX_HINT_SPEND.
        """
        if self.hint_mode != "wheel" or self.phase != Phase.DRAWING or not self.prompt:
            return False
        if not self.is_turn_eligible(token) or token in self.correct_guessers:
            return False
        letter = letter.lower()
        if letter not in string.ascii_lowercase:
            return False
        bought = self.purchased_letters.setdefault(token, set())
        if letter in bought:
            return False
        cost = self.wheel_hint_cost(token, letter)
        if cost > self.hint_spend_remaining(token):
            return False
        self._record_hint_spend(token, cost)
        bought.add(letter)
        return True

    def hint_spend_remaining(self, token: str) -> int:
        """How much more `token` may still commit to hints this turn."""
        return max(0, MAX_HINT_SPEND - self.hint_spend.get(token, 0))

    def _record_hint_spend(self, token: str, cost: int) -> None:
        self.hint_spend[token] = self.hint_spend.get(token, 0) + cost
        self.hint_purchases[token] = self.hint_purchases.get(token, 0) + 1

    def submit_guess(self, token: str, text: str) -> tuple[bool, int]:
        if self.phase != Phase.DRAWING or not self.prompt:
            return False, 0
        if not self.is_turn_eligible(token) or token in self.correct_guessers:
            return False, 0
        if len(text) > MAX_PROMPT_LENGTH:
            return False, 0
        normalized_guess = _normalize(text, self.prompt_language)
        accepted_answers = self._accepted_answer_keys()
        if normalized_guess not in accepted_answers:
            # Counted here rather than at the caller so that only real attempts
            # land: the drawer and players who already have it return above,
            # and their messages are chat, not guesses.
            self.wrong_guesses[token] = self.wrong_guesses.get(token, 0) + 1
            if self.guess_hint(token, text) is not None:
                self.near_misses[token] = self.near_misses.get(token, 0) + 1
            return False, 0
        self.guess_times[token] = self.elapsed_drawing_seconds()
        if self.scoring_mode == "none":
            self.correct_guessers.add(token)
            self.guess_points[token] = 0
            return True, 0
        if self.scoring_mode == "pressure":
            # Advance before this guesser lands, so the stretch ending here is
            # charged at the pre-guess multiplier. Adding to correct_guessers
            # below is what raises the rate for everyone still guessing.
            self._advance_decay_clock()
            points = max(
                PRESSURE_MIN_POINTS,
                round(PRESSURE_MAX_POINTS * self._pressure_rate() ** self.decay_time),
            )
        else:
            remaining_ratio = self.remaining_seconds() / self.drawing_seconds
            points = round(
                MIN_GUESS_POINTS + (MAX_GUESS_POINTS - MIN_GUESS_POINTS) * remaining_ratio
            )
        # Hints are bought on credit and settled here: the turn pays for them
        # out of what it earned, and a turn that earned nothing owes nothing.
        points = max(0, points - self.hint_spend.get(token, 0))
        self.correct_guessers.add(token)
        self.guess_points[token] = points
        return True, points

    def guess_hint(self, token: str, text: str) -> str | None:
        """Whether a (known-incorrect) guess deserves a private hint instead of
        being silently broadcast to the room as-is.

        Returns "close" if the guess is a close guess for the whole prompt/phrase
        (see `_is_close_pair`), "partial" if (for multi-word prompts only,
        matching words position-independently and tolerating a word-count
        difference of at most 1) one or more correct words together add up to
        at least `CLOSE_GUESS_MIN_CORRECT_LETTERS` letters, or None if
        neither applies.
        """
        if not self.prompt:
            return None
        if not self.is_turn_eligible(token) or token in self.correct_guessers:
            return None
        if len(text) > MAX_PROMPT_LENGTH:
            return None
        guess = _normalize(text, self.prompt_language)
        accepted_answers = self._accepted_answer_keys()
        if guess in accepted_answers:
            return None
        if any(_is_close_pair(guess, answer) for answer in accepted_answers):
            return "close"
        guess_tokens = guess.split(" ")
        for answer in accepted_answers:
            word_tokens = answer.split(" ")
            if len(word_tokens) <= 1 or abs(len(guess_tokens) - len(word_tokens)) > 1:
                continue
            # Bag-of-words intersection: matches regardless of word order,
            # capping duplicate words at the lower count on either side.
            overlap = Counter(guess_tokens) & Counter(word_tokens)
            correct_letter_count = sum(
                len(word) * count for word, count in overlap.items()
            )
            if correct_letter_count >= CLOSE_GUESS_MIN_CORRECT_LETTERS:
                return "partial"
        return None

    def _accepted_answer_keys(self) -> tuple[str, ...]:
        """Canonical answer plus aliases for this exact selected version."""
        if not self.prompt:
            return ()
        aliases = self.prompt_aliases.get(self.prompt, ())
        return tuple(
            dict.fromkeys(
                _normalize(answer, self.prompt_language)
                for answer in (self.prompt, *aliases)
            )
        )

    def all_guessed(self, total_guessers: int) -> bool:
        return total_guessers > 0 and len(self.correct_guessers) >= total_guessers

    def end_turn(
        self,
        total_guesser_count: int = 0,
        *,
        terminal_states: Mapping[str, str] | None = None,
        all_active_guessed: bool | None = None,
    ) -> int | None:
        """Transition to TURN_RESULTS, return drawer bonus points.

        The drawer receives the sum of the points earned by all correct guessers in this turn.

        Returns None if the game is no longer drawing, making the transition
        safe when a timeout races the final correct guess.
        """
        if self.phase != Phase.DRAWING:
            return None
        self.phase = Phase.TURN_RESULTS
        participant_outcomes: tuple[TurnParticipantOutcomeRecord, ...] = ()
        if self.turn_eligibility_reasons is not None:
            states = terminal_states or {}
            # Every frozen seat must be told how it ended; a missing token is
            # a caller bug, and a KeyError mid-write is a worse way to learn
            # about it than this.
            missing = self.turn_eligibility_reasons.keys() - states.keys()
            if missing:
                raise ValueError(
                    "end_turn requires a terminal state for every seat frozen "
                    f"at turn start; missing {sorted(missing)}"
                )
            rows: list[TurnParticipantOutcomeRecord] = []
            for token, eligibility_reason in self.turn_eligibility_reasons.items():
                eligible = eligibility_reason == TurnEligibilityReason.ELIGIBLE.value
                correct = token in self.correct_guessers
                wrong_count = self.wrong_guesses.get(token, 0)
                outcome = (
                    TurnParticipantOutcome.CORRECT.value
                    if correct
                    else TurnParticipantOutcome.INCORRECT.value
                    if eligible and wrong_count
                    else TurnParticipantOutcome.NO_ATTEMPT.value
                    if eligible
                    else TurnParticipantOutcome.INELIGIBLE.value
                )
                rows.append(
                    TurnParticipantOutcomeRecord(
                        token=token,
                        eligible=eligible,
                        eligibility_reason=eligibility_reason,
                        outcome=outcome,
                        terminal_state=states[token],
                        correct_guess_time_seconds=(
                            self.guess_times.get(token) if correct else None
                        ),
                        wrong_guess_count=wrong_count,
                        near_miss_count=self.near_misses.get(token, 0),
                        hints_used=self.hint_purchases.get(token, 0),
                        points_spent_on_hints=self.hint_spend.get(token, 0),
                    )
                )
            participant_outcomes = tuple(rows)

        self.completed_turns.append(
            CompletedTurnStats(
                id=self.current_turn_id or str(generate_uuid7()),
                round_number=self.round_number,
                turn_number=len(self.completed_turns) + 1,
                offered_prompts=list(self.prompt_choices),
                chosen_prompt=self.prompt or "",
                correct_guess_count=len(self.correct_guessers),
                total_guesser_count=total_guesser_count,
                offered_prompt_version_ids=tuple(
                    self.prompt_version_ids.get(prompt)
                    for prompt in self.prompt_choices
                ),
                offered_prompt_source_kinds=tuple(
                    self.prompt_source_kind(prompt) for prompt in self.prompt_choices
                ),
                offered_prompt_source_revision_ids=tuple(
                    self.prompt_source_revision_ids_by_answer.get(prompt, ())
                    for prompt in self.prompt_choices
                ),
                chosen_prompt_version_id=self.prompt_version_ids.get(
                    self.prompt or ""
                ),
                drawer_token=self.current_drawer or "",
                duration_seconds=self.elapsed_drawing_seconds(),
                guesses=tuple(
                    TurnGuessRecord(
                        token=token,
                        points_awarded=self.guess_points.get(token, 0),
                        guess_time_seconds=self.guess_times.get(token, 0.0),
                        hints_used=self.hint_purchases.get(token, 0),
                        points_spent_on_hints=self.hint_spend.get(token, 0),
                        wrong_guesses_before=self.wrong_guesses.get(token, 0),
                    )
                    for token in sorted(
                        self.correct_guessers,
                        key=lambda t: self.guess_times.get(t, 0.0),
                    )
                ),
                prompt_auto_picked=self.prompt_auto_picked,
                stroke_count=len(self.canvas.history),
                end_reason=(
                    TurnEndReason.ALL_GUESSED.value
                    if (
                        all_active_guessed
                        if all_active_guessed is not None
                        else self.all_guessed(total_guesser_count)
                    )
                    else TurnEndReason.TIMEOUT.value
                ),
                wrong_guess_count=sum(self.wrong_guesses.values()),
                near_miss_count=sum(self.near_misses.values()),
                present_tokens=tuple(self.turn_order),
                participant_outcomes=participant_outcomes,
            )
        )
        return sum(self.guess_points.values())

    def advance_phase_after_turn(self) -> Phase:
        self.phase = Phase.GAME_END if self.is_finished() else Phase.CHOOSING_PROMPT
        return self.phase
