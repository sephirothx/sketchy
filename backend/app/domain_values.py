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
    GERMAN = "de"
    SPANISH = "es"
    FRENCH = "fr"
    ITALIAN = "it"
    DUTCH = "nl"
    PORTUGUESE = "pt"


class PromptEditorialDifficulty(StrEnum):
    UNSPECIFIED = "unspecified"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class PromptContentRating(StrEnum):
    EVERYONE = "everyone"
    TEEN = "teen"
    MATURE = "mature"


class PromptListVisibility(StrEnum):
    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class PromptContentModerationState(StrEnum):
    ACTIVE = "active"
    UNDER_REVIEW = "under_review"
    HIDDEN = "hidden"


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


class DataExportStatus(StrEnum):
    """Lifecycle of a durable asynchronous account-data export."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class UserTheme(StrEnum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class BrushCursorStyle(StrEnum):
    CROSSHAIR = "crosshair"
    CIRCLE = "circle"


class ReportReason(StrEnum):
    HARASSMENT = "harassment"
    OFFENSIVE_DRAWING = "offensive_drawing"
    INAPPROPRIATE_NAME = "inappropriate_name"
    CHEATING = "cheating"
    SPAM = "spam"


class ReportStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


SCORING_MODES = tuple(mode.value for mode in ScoringMode)
HINT_MODES = tuple(mode.value for mode in HintMode)
TURN_END_REASONS = tuple(reason.value for reason in TurnEndReason)
PROMPT_LANGUAGES = tuple(language.value for language in PromptLanguage)
PROMPT_EDITORIAL_DIFFICULTIES = tuple(
    difficulty.value for difficulty in PromptEditorialDifficulty
)
PROMPT_CONTENT_RATINGS = tuple(rating.value for rating in PromptContentRating)
PROMPT_LIST_VISIBILITIES = tuple(
    visibility.value for visibility in PromptListVisibility
)
PROMPT_CONTENT_MODERATION_STATES = tuple(
    state.value for state in PromptContentModerationState
)
ACCOUNT_STATES = tuple(state.value for state in AccountState)
USER_ROLES = tuple(role.value for role in UserRole)
DATA_EXPORT_STATUSES = tuple(status.value for status in DataExportStatus)
USER_THEMES = tuple(theme.value for theme in UserTheme)
BRUSH_CURSOR_STYLES = tuple(style.value for style in BrushCursorStyle)
REPORT_REASONS = tuple(reason.value for reason in ReportReason)
REPORT_STATUSES = tuple(status.value for status in ReportStatus)

# Keep the backend's registration/API/database fallback aligned with the
# frontend's checked-in default shortcuts. A fresh row must be usable even when
# it is inserted outside the normal settings service (for example by a data
# repair or import).
DEFAULT_USER_KEY_BINDINGS = {
    "brush": ["p", "1"],
    "fill": ["f", "2"],
    "eraser": ["e", "3"],
    "rectangle": ["r", "4"],
    "triangle": ["t", "5"],
    "ellipse": ["c", "6"],
    "brushDecrease": ["["],
    "brushIncrease": ["]"],
    "undo": ["z"],
}
