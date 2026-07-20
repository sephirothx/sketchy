"""Per-room game state machine: turn rotation, word choice, drawing timer, scoring.

Pure state/logic only (no socket I/O) so it can be unit tested directly.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from itertools import groupby

from app.words import random_word_choices

CHOOSE_WORD_SECONDS = 15
DRAWING_SECONDS = 80
ROUND_END_SECONDS = 5
DRAWER_POINTS_PER_GUESSER = 10
MIN_GUESS_POINTS = 10
MAX_GUESS_POINTS = 100


class Phase(str, Enum):
    CHOOSING_WORD = "choosing_word"
    DRAWING = "drawing"
    ROUND_END = "round_end"
    GAME_END = "game_end"


@dataclass
class Game:
    turn_order: list[str]
    rounds_total: int = 3
    turn_index: int = -1
    phase: Phase = Phase.CHOOSING_WORD
    current_drawer: str | None = None
    word: str | None = None
    word_choices: list[str] = field(default_factory=list)
    correct_guessers: set[str] = field(default_factory=set)
    guess_points: dict[str, int] = field(default_factory=dict)
    strokes: list[dict] = field(default_factory=list)
    phase_deadline: float | None = None
    used_words: set[str] = field(default_factory=set)
    word_pool: list[str] | None = None
    drawing_seconds: float = DRAWING_SECONDS

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

    def set_phase_deadline(self, seconds: float) -> None:
        self.phase_deadline = time.monotonic() + seconds

    def remaining_seconds(self) -> float:
        if self.phase_deadline is None:
            return 0.0
        return max(0.0, self.phase_deadline - time.monotonic())

    def start_next_turn(self) -> list[str]:
        """Advance to the next drawer and offer word choices."""
        self.turn_index += 1
        self.current_drawer = self.turn_order[self.turn_index % len(self.turn_order)]
        self.word = None
        self.word_choices = random_word_choices(3, exclude=self.used_words, pool=self.word_pool)
        self.correct_guessers = set()
        self.guess_points = {}
        self.strokes = []
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
        self.phase = Phase.DRAWING

    def masked_word(self) -> str:
        """Blank out each word's letters/digits into underscores while keeping
        spaces and other special characters (hyphens, apostrophes, etc.)
        visible, so multi-word expressions (e.g. "red panda") and punctuated
        words (e.g. "spider-man") clearly show their structure to guessers.
        Every letter run's count is appended at the end, in order - special
        characters act as boundaries here too, so "spider-man" reports "6 3"
        (one count for "spider", one for "man") - and the blanks themselves
        stay tightly packed with a clear gap between words.
        """
        if not self.word:
            return ""
        tokens = self.word.split()
        masked_words = [
            "".join("_" if ch.isalnum() else ch for ch in token) for token in tokens
        ]
        letter_counts = [
            str(len(list(run)))
            for is_alnum, run in groupby(self.word, key=str.isalnum)
            if is_alnum
        ]
        return "  ".join(masked_words) + "  " + " ".join(letter_counts)

    def record_stroke(self, event: str, payload: dict) -> None:
        self.strokes.append({"event": event, "payload": payload})

    def submit_guess(self, token: str, text: str) -> tuple[bool, int]:
        if self.phase != Phase.DRAWING or not self.word:
            return False, 0
        if token == self.current_drawer or token in self.correct_guessers:
            return False, 0
        # Normalize whitespace so multi-word expressions match regardless of
        # extra/irregular spacing in the guesser's input (e.g. "red  panda").
        normalized_guess = " ".join(text.split()).lower()
        normalized_word = " ".join(self.word.split()).lower()
        if normalized_guess != normalized_word:
            return False, 0
        self.correct_guessers.add(token)
        remaining_ratio = self.remaining_seconds() / self.drawing_seconds
        points = max(MIN_GUESS_POINTS, round(MAX_GUESS_POINTS * remaining_ratio))
        self.guess_points[token] = points
        return True, points

    def all_guessed(self, total_guessers: int) -> bool:
        return total_guessers > 0 and len(self.correct_guessers) >= total_guessers

    def end_round(self) -> int:
        """Transition to ROUND_END, return drawer bonus points.

        The bonus scales with how quickly guessers actually answered (each
        guesser's own points, scaled down to the DRAWER_POINTS_PER_GUESSER
        baseline), not just a flat amount per correct guesser. This removes
        the incentive for a drawer to stall before drawing: delaying reveals
        an easy word right before the deadline still caps everyone's guess
        points near the floor, which now also caps the drawer's own bonus.
        """
        self.phase = Phase.ROUND_END
        return sum(
            round(points * DRAWER_POINTS_PER_GUESSER / MAX_GUESS_POINTS)
            for points in self.guess_points.values()
        )

    def advance_phase_after_round(self) -> Phase:
        self.phase = Phase.GAME_END if self.is_finished() else Phase.CHOOSING_WORD
        return self.phase
