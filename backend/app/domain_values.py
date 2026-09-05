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


class TurnEligibilityReason(StrEnum):
    ELIGIBLE = "eligible"
    AFK = "afk"
    DISCONNECTED = "disconnected"
    # No longer recorded: a seat that joins mid-turn is an eligible guesser
    # like any other. Kept because finished games still carry the value.
    JOINED_LATE = "joined_late"


class TurnParticipantOutcome(StrEnum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    NO_ATTEMPT = "no_attempt"
    INELIGIBLE = "ineligible"


class TurnParticipantState(StrEnum):
    ACTIVE = "active"
    AFK = "afk"
    DISCONNECTED = "disconnected"
    LEFT = "left"


class ScoreEventType(StrEnum):
    """Constrained reasons for an append-only change to a game score."""

    GUESS_AWARD = "guess_award"
    HINT_CHARGE = "hint_charge"
    DRAWER_BONUS = "drawer_bonus"
    CORRECTION = "correction"


class RetainedMessageKind(StrEnum):
    CHAT = "chat"
    WRONG_GUESS = "wrong_guess"
    CORRECT_GUESS = "correct_guess"


class RetainedMessageAudience(StrEnum):
    ROOM = "room"
    PROMPT_AWARE = "prompt_aware"
    # Said in the lobby, to every lobby that was open: public by construction,
    # with no room to scope it to and no recipient list worth recording.
    LOBBY = "lobby"


class NearMissKind(StrEnum):
    CLOSE = "close"
    PARTIAL = "partial"


class PromptSourceKind(StrEnum):
    CURATED = "curated"
    CUSTOM = "custom"
    BUILTIN_FALLBACK = "builtin_fallback"


class GamePromptSourceMode(StrEnum):
    CURATED = "curated"
    CUSTOM = "custom"
    MIXED = "mixed"
    BUILTIN_FALLBACK = "builtin_fallback"


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


class PromptContentReportReason(StrEnum):
    INAPPROPRIATE = "inappropriate"
    HATEFUL_OR_ABUSIVE = "hateful_or_abusive"
    SEXUAL_CONTENT = "sexual_content"
    VIOLENCE = "violence"
    SPAM = "spam"
    OTHER = "other"


class AccountState(StrEnum):
    """Lifecycle state for a persisted player identity."""

    ANONYMOUS = "anonymous"
    REGISTERED = "registered"
    MERGED = "merged"
    DELETED = "deleted"


class FriendshipState(StrEnum):
    """Where a friendship between two accounts has got to.

    `declined` is kept rather than deleted: a row that disappears lets the
    sender ask again immediately and for ever, and "you are doing that too
    quickly" is the wrong sentence for "this person said no". The person who
    declined may still send their own request later, which rewrites the row -
    saying no is not a commitment.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class UserRole(StrEnum):
    """Service-wide authorization role for an account."""

    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"


class DataExportArtifactEncoding(StrEnum):
    """How a stored export document is encoded, read from the row itself."""

    GZIP_JSON = "gzip+json"


class DataExportStatus(StrEnum):
    """Lifecycle of a durable asynchronous account-data export."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class TurnDrawingStatus(StrEnum):
    """Lifecycle of one turn's stored drawing.

    Only ``ready`` and ``unavailable`` are reachable today: the blob is written
    inside the same transaction as its game, so there is no window in which a
    drawing is promised but missing. ``pending`` and ``failed`` are kept for the
    day storage moves out of the database and a write can outlive its
    transaction.
    """

    PENDING = "pending"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    DELETED = "deleted"


TURN_DRAWING_STATUSES = tuple(status.value for status in TurnDrawingStatus)


class ReactionEmoji(StrEnum):
    """The fixed, positive set of reactions a drawing can be given (#520).

    Codes are stored on the row and rendered by the client, so they follow the
    rule stored-drawing decoders already follow (R-HIST-18): a code shipped is a
    code forever. Retiring one means adding it to
    ``RETIRED_REACTION_EMOJI_CODES`` so it is no longer offered; it is never
    removed from this enum, or every row that carries it stops rendering.
    Adding one is additive and bumps ``REACTION_SET_VERSION``.
    """

    HEART = "heart"
    LAUGH = "laugh"
    WOW = "wow"
    FIRE = "fire"


# Every code ever stored: what the database CHECK and a history read accept.
REACTION_EMOJI_CODES = tuple(emoji.value for emoji in ReactionEmoji)
# Stored and rendered, but no longer offered to a player. Empty so far.
RETIRED_REACTION_EMOJI_CODES: frozenset[str] = frozenset()
# What a player may pick today.
OFFERED_REACTION_EMOJI_CODES = tuple(
    code for code in REACTION_EMOJI_CODES if code not in RETIRED_REACTION_EMOJI_CODES
)
REACTION_SET_VERSION = 1

# The recap drops a drawing's bytes once a room exceeds its per-game budget.
# That turn is stored as unavailable so history matches what players saw.
DRAWING_UNAVAILABLE_RECAP_BUDGET = "recap_budget"


class UserTheme(StrEnum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class BrushCursorStyle(StrEnum):
    CROSSHAIR = "crosshair"
    CIRCLE = "circle"


class TimeFormat(StrEnum):
    """How a clock reads to this player; SYSTEM follows the device's locale."""

    SYSTEM = "system"
    TWELVE_HOUR = "12h"
    TWENTY_FOUR_HOUR = "24h"


class ReportReason(StrEnum):
    HARASSMENT = "harassment"
    OFFENSIVE_DRAWING = "offensive_drawing"
    INAPPROPRIATE_NAME = "inappropriate_name"
    CHEATING = "cheating"
    SPAM = "spam"
    INAPPROPRIATE_AVATAR = "inappropriate_avatar"


class ReportStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class BugReportArea(StrEnum):
    """Where in the product a bug was met.

    Ten buckets taken from the requirement sections rather than invented, so a
    report lands where the code and its tests already live. Connection and
    accessibility get their own rather than folding into `OTHER`: both have
    dedicated requirements and end-to-end suites, and both are exactly what
    goes unreported when the only honest answer is "something else".
    """

    DRAWING_AND_CANVAS = "drawing_and_canvas"
    GUESSING_AND_CHAT = "guessing_and_chat"
    ROUNDS_AND_SCORING = "rounds_and_scoring"
    ROOMS_AND_LOBBY = "rooms_and_lobby"
    PROMPT_LISTS = "prompt_lists"
    ACCOUNT_AND_SETTINGS = "account_and_settings"
    CONNECTION_AND_SYNC = "connection_and_sync"
    PERFORMANCE = "performance"
    ACCESSIBILITY = "accessibility"
    OTHER = "other"


class BugReportSeverity(StrEnum):
    BLOCKS_PLAY = "blocks_play"
    MAJOR = "major"
    MINOR = "minor"


class BugReportScreenshotStatus(StrEnum):
    """Whether a report carries a screenshot, and whether it still does.

    `ERASED` is not the same as `NONE`: a decided report should say that a
    screenshot existed and was dropped, rather than reading as one that never
    had a picture at all.
    """

    NONE = "none"
    READY = "ready"
    ERASED = "erased"


class RuntimeEventType(StrEnum):
    """What the server records about its own behaviour.

    Every one of these was invisible before: `RoomManager` had the natural
    hooks and counted nothing, so peak concurrency, reconnect rate, timer
    overruns and observed payload sizes could only be guessed at.
    """

    ROOM_CREATED = "room.created"
    ROOM_CLOSED = "room.closed"
    PLAYER_JOINED = "player.joined"
    PLAYER_LEFT = "player.left"
    PLAYER_DISCONNECTED = "player.disconnected"
    PLAYER_RECONNECTED = "player.reconnected"
    PLAYER_EVICTED = "player.evicted"
    GAME_STARTED = "game.started"
    GAME_FINISHED = "game.finished"
    GAME_ABANDONED = "game.abandoned"
    TURN_ENDED = "turn.ended"
    TIMER_OVERRAN = "timer.overran"
    CANVAS_PAYLOAD_OBSERVED = "canvas.payload_observed"
    DRAWING_STORED = "drawing.stored"
    RECAP_BUDGET_DROPPED = "recap.budget_dropped"
    COMMAND_THROTTLED = "command.throttled"
    # A finished game's history, or its prompt-usage facts, that the server
    # gave up writing. The swallow is deliberate (a slow database must not
    # hold a room open); the count is what makes the loss visible (#482).
    HISTORY_WRITE_ABANDONED = "history.write_abandoned"


class GameOutcome(StrEnum):
    """How a game stopped.

    `finished_at` keeps meaning when the game ended; this says whether it
    reached an end or merely stopped. Games that stop were invisible before -
    `_persist_game_history` only ran for finished ones - so the games a
    maintainer most wants to see left no trace at all.
    """

    FINISHED = "finished"
    ABANDONED = "abandoned"
    SHUTDOWN = "shutdown"


class AuthTokenPurpose(StrEnum):
    """Why a one-shot token exists.

    One table rather than one per kind: the shape and the lifecycle are
    identical - issued, mailed, consumed once or expired - so a third purpose
    is a new value here rather than a migration.
    """

    PASSWORD_RESET = "password_reset"
    EMAIL_VERIFY = "email_verify"


class EmailOutboxState(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class EmailTemplate(StrEnum):
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"
    PASSWORD_CHANGED = "password_changed"
    ACCOUNT_BANNED = "account_banned"
    CONTENT_HIDDEN = "content_hidden"


class AuditTargetType(StrEnum):
    """What an audited action was performed on.

    Recorded beside `target_user_id` rather than replacing it: that column is a
    real foreign key with `ON DELETE SET NULL`, which a generic pair naming
    rows in any table cannot be. The pair exists so that a takedown can say
    what was taken down.
    """

    USER = "user"
    PROMPT_LIST = "prompt_list"
    PROMPT_VERSION = "prompt_version"
    ROOM = "room"
    APP_CONFIG = "app_config"
    BUG_REPORT = "bug_report"


SCORING_MODES = tuple(mode.value for mode in ScoringMode)
PROMPT_SOURCE_KINDS = tuple(kind.value for kind in PromptSourceKind)
PROMPT_OFFER_SOURCE_KINDS = tuple(kind.value for kind in PromptSourceKind)
GAME_PROMPT_SOURCE_MODES = tuple(mode.value for mode in GamePromptSourceMode)
HINT_MODES = tuple(mode.value for mode in HintMode)
TURN_END_REASONS = tuple(reason.value for reason in TurnEndReason)
TURN_ELIGIBILITY_REASONS = tuple(reason.value for reason in TurnEligibilityReason)
TURN_PARTICIPANT_OUTCOMES = tuple(outcome.value for outcome in TurnParticipantOutcome)
TURN_PARTICIPANT_STATES = tuple(state.value for state in TurnParticipantState)
SCORE_EVENT_TYPES = tuple(event_type.value for event_type in ScoreEventType)
RETAINED_MESSAGE_KINDS = tuple(kind.value for kind in RetainedMessageKind)
RETAINED_MESSAGE_AUDIENCES = tuple(
    audience.value for audience in RetainedMessageAudience
)
NEAR_MISS_KINDS = tuple(kind.value for kind in NearMissKind)
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
PROMPT_CONTENT_REPORT_REASONS = tuple(
    reason.value for reason in PromptContentReportReason
)
ACCOUNT_STATES = tuple(state.value for state in AccountState)
USER_ROLES = tuple(role.value for role in UserRole)
FRIENDSHIP_STATES = tuple(state.value for state in FriendshipState)
# The roles an administrator may set over the network, and so the only ones a
# role-change notice can ever be about. `admin` is deliberately absent: the
# first one is made by a guarded server-side command, and `api/admin_controls`
# carries the reasoning where the refusal is enforced.
GRANTABLE_ROLES = (UserRole.USER.value, UserRole.MODERATOR.value)
DATA_EXPORT_STATUSES = tuple(status.value for status in DataExportStatus)
DATA_EXPORT_ARTIFACT_ENCODINGS = tuple(
    encoding.value for encoding in DataExportArtifactEncoding
)
USER_THEMES = tuple(theme.value for theme in UserTheme)
BRUSH_CURSOR_STYLES = tuple(style.value for style in BrushCursorStyle)
TIME_FORMATS = tuple(value.value for value in TimeFormat)
REPORT_REASONS = tuple(reason.value for reason in ReportReason)
BUG_REPORT_AREAS = tuple(area.value for area in BugReportArea)
BUG_REPORT_SEVERITIES = tuple(severity.value for severity in BugReportSeverity)
BUG_REPORT_SCREENSHOT_STATUSES = tuple(
    status.value for status in BugReportScreenshotStatus
)
REPORT_STATUSES = tuple(status.value for status in ReportStatus)
AUDIT_TARGET_TYPES = tuple(target.value for target in AuditTargetType)
GAME_OUTCOMES = tuple(outcome.value for outcome in GameOutcome)
RUNTIME_EVENT_TYPES = tuple(event.value for event in RuntimeEventType)
AUTH_TOKEN_PURPOSES = tuple(purpose.value for purpose in AuthTokenPurpose)
EMAIL_OUTBOX_STATES = tuple(state.value for state in EmailOutboxState)
EMAIL_TEMPLATES = tuple(template.value for template in EmailTemplate)

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
