"""Canonical stored values shared by validation, domain logic, and schema."""
from __future__ import annotations

from enum import StrEnum


class ScoringMode(StrEnum):
    NONE = "none"
    DEFAULT = "default"
    PRESSURE = "pressure"


class HintMode(StrEnum):
    NONE = "none"
    CHECKPOINTS = "checkpoints"
    PURCHASE = "purchase"
    WHEEL = "wheel"


class TurnEndReason(StrEnum):
    ALL_GUESSED = "all_guessed"
    TIMEOUT = "timeout"


class PromptLanguage(StrEnum):
    ENGLISH = "en"


SCORING_MODES = tuple(mode.value for mode in ScoringMode)
HINT_MODES = tuple(mode.value for mode in HintMode)
TURN_END_REASONS = tuple(reason.value for reason in TurnEndReason)
PROMPT_LANGUAGES = tuple(language.value for language in PromptLanguage)
