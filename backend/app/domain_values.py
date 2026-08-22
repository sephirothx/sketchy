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


class AccountState(StrEnum):
    """Lifecycle state for a persisted player identity."""

    ANONYMOUS = "anonymous"
    REGISTERED = "registered"
    MERGED = "merged"
    DELETED = "deleted"


class UserRole(StrEnum):
    """Service-wide authorization role for an account."""

    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"


SCORING_MODES = tuple(mode.value for mode in ScoringMode)
HINT_MODES = tuple(mode.value for mode in HintMode)
TURN_END_REASONS = tuple(reason.value for reason in TurnEndReason)
PROMPT_LANGUAGES = tuple(language.value for language in PromptLanguage)
ACCOUNT_STATES = tuple(state.value for state in AccountState)
USER_ROLES = tuple(role.value for role in UserRole)
