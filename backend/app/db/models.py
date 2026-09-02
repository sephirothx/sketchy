"""SQLAlchemy ORM models for Sketchy database tables."""
from __future__ import annotations

from datetime import date, datetime
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
    text,
    true,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.auth.avatars import BUILT_IN_AVATAR_KEYS
from app.db.types import UTCDateTime
from app.domain_values import (
    BugReportScreenshotStatus,
    GameOutcome,
    RUNTIME_EVENT_TYPES,
    AUTH_TOKEN_PURPOSES,
    EMAIL_OUTBOX_STATES,
    EMAIL_TEMPLATES,
    ACCOUNT_STATES,
    BRUSH_CURSOR_STYLES,
    BUG_REPORT_AREAS,
    BUG_REPORT_SCREENSHOT_STATUSES,
    BUG_REPORT_SEVERITIES,
    DATA_EXPORT_ARTIFACT_ENCODINGS,
    DATA_EXPORT_STATUSES,
    DEFAULT_USER_KEY_BINDINGS,
    FRIENDSHIP_STATES,
    FriendshipState,
    GAME_PROMPT_SOURCE_MODES,
    HINT_MODES,
    NEAR_MISS_KINDS,
    PROMPT_CONTENT_MODERATION_STATES,
    PROMPT_CONTENT_REPORT_REASONS,
    PROMPT_CONTENT_RATINGS,
    PROMPT_EDITORIAL_DIFFICULTIES,
    PROMPT_LANGUAGES,
    PROMPT_LIST_VISIBILITIES,
    PROMPT_OFFER_SOURCE_KINDS,
    PROMPT_SOURCE_KINDS,
    REPORT_REASONS,
    REPORT_STATUSES,
    RETAINED_MESSAGE_AUDIENCES,
    RETAINED_MESSAGE_KINDS,
    SCORE_EVENT_TYPES,
    SCORING_MODES,
    TURN_DRAWING_STATUSES,
    TURN_ELIGIBILITY_REASONS,
    TURN_END_REASONS,
    TURN_PARTICIPANT_OUTCOMES,
    TURN_PARTICIPANT_STATES,
    GRANTABLE_ROLES,
    USER_ROLES,
    USER_THEMES,
    AccountState,
    BrushCursorStyle,
    DataExportStatus,
    PromptContentRating,
    PromptContentModerationState,
    PromptContentReportReason,
    PromptEditorialDifficulty,
    PromptLanguage,
    PromptListVisibility,
    ReportReason,
    ReportStatus,
    TurnEndReason,
    UserRole,
    UserTheme,
)
from app.identifiers import generate_uuid7


# PostgreSQL's `json` is a text type: it re-parses on every read, keeps
# insignificant whitespace, and has no operator class, so it can be neither
# compared nor GIN-indexed. `jsonb` stores a parsed form and does all three.
# SQLite is unaffected - it holds JSON as text either way.
#
# `none_as_null` is the other half: without it SQLAlchemy persists a Python
# None as the JSON value `null` - the four-character string - rather than SQL
# NULL, so a column that reads as "absent" is really storing a token, and one
# declared NOT NULL silently accepts it.
PortableJSON = JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def _values_check(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    allowed = ", ".join(repr(value) for value in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


def generate_uuid() -> uuid.UUID:
    """Compatibility name for the central durable UUIDv7 generator."""
    return generate_uuid7()


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy entities."""
    pass


class AppConfig(Base):
    """Key-value storage for server configuration and auto-generated secrets."""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RoomCodeReservation(Base):
    """Global room invite-code claim, including the post-room retirement window."""

    __tablename__ = "room_code_reservations"
    __table_args__ = (
        _values_check("kind", ("ephemeral", "persistent"), "ck_room_code_kind"),
        CheckConstraint(
            "(kind = 'persistent' AND retired_until IS NULL) OR kind = 'ephemeral'",
            name="ck_persistent_room_code_never_retires",
        ),
    )

    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    retired_until: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True, index=True
    )


class RoomPreset(Base):
    """Private reusable room configuration, with no room or live-state identity."""

    __tablename__ = "room_presets"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id", "name_key", name="uq_room_presets_owner_name"
        ),
        _values_check(
            "scoring_mode", SCORING_MODES, "ck_room_presets_scoring_mode"
        ),
        _values_check("hint_mode", HINT_MODES, "ck_room_presets_hint_mode"),
        _values_check(
            "color_mode",
            ("all", "palette", "colorblind_safe", "black_and_white"),
            "ck_room_presets_color_mode",
        ),
        CheckConstraint(
            "max_players >= 2 AND max_players <= 16",
            name="ck_room_presets_max_players",
        ),
        CheckConstraint("rounds >= 1 AND rounds <= 10", name="ck_room_presets_rounds"),
        CheckConstraint(
            "drawing_seconds IN (15, 30, 60, 90, 120, 180, 240, 300)",
            name="ck_room_presets_drawing_seconds",
        ),
        CheckConstraint("version >= 1", name="ck_room_presets_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    name_key: Mapped[str] = mapped_column(String(64), nullable=False)
    room_name: Mapped[str] = mapped_column(String(40), nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_players: Mapped[int] = mapped_column(Integer, nullable=False)
    rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    drawing_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    hint_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    scoring_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    spectators_see_prompt: Mapped[bool] = mapped_column(Boolean, nullable=False)
    hide_masked_prompt: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allowed_tools: Mapped[list[str]] = mapped_column(PortableJSON, nullable=False)
    color_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    prompt_list_ids: Mapped[list[str]] = mapped_column(PortableJSON, nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuthRateLimitBucket(Base):
    """Shared fixed-window bucket for security-sensitive authentication limits."""

    __tablename__ = "auth_rate_limit_buckets"

    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    window_expires_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class User(Base):
    """Persistent player identity (both anonymous guests and registered users)."""

    __tablename__ = "users"

    # Expression-based, so `alembic revision --autogenerate` cannot see it on
    # SQLite - the dialect has no way to reflect such an index, and skips it
    # rather than emitting a spurious CREATE on every run. Any change to this
    # index therefore has to be written into a migration by hand: autogenerate
    # will report nothing and mean nothing by it. Revision 9b6f4e2d1a70 pins it
    # explicitly and the migration suite checks the database definition.
    __table_args__ = (
        Index(
            "ix_users_username_lower",
            func.lower(text("username")),
            unique=True,
            postgresql_where=text("username IS NOT NULL"),
            sqlite_where=text("username IS NOT NULL"),
        ),
        Index(
            "ix_users_email_lower",
            func.lower(text("email")),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
            sqlite_where=text("email IS NOT NULL"),
        ),
        _values_check("state", ACCOUNT_STATES, "ck_users_state"),
        _values_check("role", USER_ROLES, "ck_users_role"),
        _values_check(
            "avatar_key", BUILT_IN_AVATAR_KEYS, "ck_users_avatar_key"
        ),
        Index("ix_users_state_last_active_at", "state", "last_active_at"),
        CheckConstraint(
            "email IS NULL OR email = lower(trim(email))",
            name="ck_users_email_normalized",
        ),
        CheckConstraint(
            "email IS NOT NULL OR email_verified_at IS NULL",
            name="ck_users_verified_email_present",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(32), nullable=False)
    name_color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    avatar_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[str] = mapped_column(
        String(16),
        default=AccountState.ANONYMOUS.value,
        server_default=AccountState.ANONYMOUS.value,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(16),
        default=UserRole.USER.value,
        server_default=UserRole.USER.value,
        nullable=False,
    )
    # A verified delivery flow does not ship yet. This field is deliberately
    # not exposed as a recovery channel until verification can be completed.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # Distinct from updated_at, which moves on any write. Set on guest
    # provision and refreshed on login, register, and GET /api/auth/me.
    last_login_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        server_default=func.now(),
        nullable=False,
    )
    # Meaningful participation, unlike last_login_at (page/auth activity) and
    # updated_at (any profile write). Drives anonymous-account retention.
    last_active_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    @property
    def is_anonymous(self) -> bool:
        """Compatibility view while callers migrate to the lifecycle state."""
        return self.state == AccountState.ANONYMOUS.value

    @is_anonymous.setter
    def is_anonymous(self, value: bool) -> None:
        self.state = (
            AccountState.ANONYMOUS.value
            if value
            else AccountState.REGISTERED.value
        )


class UserStatsDaily(Base):
    """Rebuildable per-account/day projection of immutable game facts."""

    __tablename__ = "user_stats_daily"
    __table_args__ = (
        CheckConstraint(
            "games_played >= 0 AND games_won >= 0 "
            "AND games_won <= games_played AND turns_played >= 0 "
            "AND prompts_guessed >= 0 "
            "AND drawings_made >= 0",
            name="ck_user_stats_daily_nonnegative",
        ),
        Index("ix_user_stats_daily_stat_date", "stat_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    stat_date: Mapped[date] = mapped_column(Date(), primary_key=True)
    games_played: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    games_won: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    total_score: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    turns_played: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    prompts_guessed: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    drawings_made: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UserSettings(Base):
    """Cross-device preferences for a registered account."""

    __tablename__ = "user_settings"
    __table_args__ = (
        _values_check("theme", USER_THEMES, "ck_user_settings_theme"),
        _values_check(
            "brush_cursor", BRUSH_CURSOR_STYLES, "ck_user_settings_brush_cursor"
        ),
        CheckConstraint(
            "sound_effects_volume >= 0.0 AND sound_effects_volume <= 1.0",
            name="ck_user_settings_volume",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    theme: Mapped[str] = mapped_column(
        String(16),
        default=UserTheme.SYSTEM.value,
        server_default=UserTheme.SYSTEM.value,
        nullable=False,
    )
    sound_effects: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    confetti_effects: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    sound_effects_volume: Mapped[float] = mapped_column(
        Float, default=0.7, server_default=text("0.7"), nullable=False
    )
    brush_cursor: Mapped[str] = mapped_column(
        String(16),
        default=BrushCursorStyle.CROSSHAIR.value,
        server_default=BrushCursorStyle.CROSSHAIR.value,
        nullable=False,
    )
    key_bindings: Mapped[dict] = mapped_column(
        PortableJSON,
        default=lambda: {
            key: list(value) for key, value in DEFAULT_USER_KEY_BINDINGS.items()
        },
        server_default=text(
            "'{\"brush\":[\"p\",\"1\"],\"fill\":[\"f\",\"2\"],"
            "\"eraser\":[\"e\",\"3\"],\"rectangle\":[\"r\",\"4\"],"
            "\"triangle\":[\"t\",\"5\"],\"ellipse\":[\"c\",\"6\"],"
            "\"brushDecrease\":[\"[\"],\"brushIncrease\":[\"]\"],"
            "\"undo\":[\"z\"]}'"
        ),
        nullable=False,
    )
    colorblind_safe_colors: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    auto_clear_chat_on_guess: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    custom_brush_presets: Mapped[list] = mapped_column(
        PortableJSON, default=list, server_default=text("'[]'"), nullable=False
    )
    # When the account was last told it has no way back in. Stored per account
    # rather than in the browser so the reminder does not restart on every new
    # device, and does not vanish because one was cleared.
    email_reminder_last_shown_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RuntimeEvent(Base):
    """One thing the server observed about itself.

    Kept for a bounded window and rolled into `runtime_stats_daily`, which is
    kept for ever. Raw rows answer "what happened last Tuesday at four"; the
    aggregates answer "is this getting worse", and only the second question is
    worth unbounded storage on an embedded database.

    `user_id` is nullable and `ON DELETE SET NULL`: an observation stays true
    after the account that caused it is erased, but stops naming anyone.
    """

    __tablename__ = "runtime_events"
    __table_args__ = (
        _values_check("event_type", RUNTIME_EVENT_TYPES, "ck_runtime_events_type"),
        Index("ix_runtime_events_occurred_at", "occurred_at"),
        Index("ix_runtime_events_type_occurred", "event_type", "occurred_at"),
    )

    # An integer, not a UUIDv7: the highest-churn table in the schema, purged
    # after thirty days, and nothing anywhere references an event. On SQLite
    # an INTEGER PRIMARY KEY is the rowid itself - no shadow key, no second
    # index.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    # The live room id, which is process-local and has no table to point at.
    room_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # One number per event, whatever that event measures: bytes for a payload,
    # milliseconds for an overrun, seconds for a room's lifetime. Kept separate
    # from `details` so it can be summed and averaged without parsing JSON.
    value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Null, not '{}', for the common eventless observation.
    details: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)


class RuntimeStatsDaily(Base):
    """Permanent daily roll-up of the raw event stream.

    Shaped after `UserStatsDaily`: one row per day per metric, summed and
    counted on write so the raw rows behind it can be discarded.
    """

    __tablename__ = "runtime_stats_daily"
    __table_args__ = (
        CheckConstraint(
            "occurrences >= 0 AND value_sum >= 0", name="ck_runtime_stats_nonnegative"
        ),
    )

    stat_date: Mapped[date] = mapped_column(Date(), primary_key=True)
    metric: Mapped[str] = mapped_column(String(32), primary_key=True)
    occurrences: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    value_sum: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    value_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuthToken(Base):
    """A one-shot credential for a flow that leaves the app and comes back.

    Only the hash is stored, for the same reason a password is: the row is a
    way to check a token somebody presents, not a way to recover one. Both
    purposes share the table because both are issued, mailed, consumed once,
    and expire - see `AuthTokenPurpose`.
    """

    __tablename__ = "auth_tokens"
    __table_args__ = (
        _values_check("purpose", AUTH_TOKEN_PURPOSES, "ck_auth_tokens_purpose"),
        CheckConstraint(
            "purpose <> 'email_verify' OR email IS NOT NULL",
            name="ck_auth_tokens_verify_address",
        ),
        Index("ix_auth_tokens_user_purpose", "user_id", "purpose"),
        Index("ix_auth_tokens_expires_at", "expires_at"),
    )

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The address being proved, for a verification token. It is deliberately
    # not written to users.email until it is proved: an unverified address
    # there would let one account reserve another person's mailbox, and would
    # make a typo a way of handing the account to a stranger.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    requested_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )


class EmailOutboxEntry(Base):
    """A message queued for delivery, written in the transaction that caused it.

    Mail is not sent inline. A ban that could not notify its subject is still a
    ban, and a reset mail that failed because the relay blinked is the one
    message a player will certainly retry. Both are answered by writing the
    intent down first and letting a sweeper carry it out.
    """

    __tablename__ = "email_outbox"
    __table_args__ = (
        _values_check("state", EMAIL_OUTBOX_STATES, "ck_email_outbox_state"),
        _values_check("template", EMAIL_TEMPLATES, "ck_email_outbox_template"),
        CheckConstraint(
            "(state = 'sent') = (sent_at IS NOT NULL)",
            name="ck_email_outbox_sent_at",
        ),
        CheckConstraint("attempts >= 0", name="ck_email_outbox_attempts"),
        Index("ix_email_outbox_ready", "state", "next_attempt_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    # Denormalized on purpose: the address a message was sent to is a fact
    # about the message, and it must survive the account changing its mind.
    to_address: Mapped[str] = mapped_column(String(255), nullable=False)
    # Nullable and SET NULL so erasing an account does not erase the record
    # that something was sent, only the link back to who it was sent to.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(PortableJSON, default=dict, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(String(256), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AuditEvent(Base):
    """Append-only record of security- and moderation-sensitive actions."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "(target_type IS NULL AND target_id IS NULL) OR "
            "(target_type IS NOT NULL AND target_id IS NOT NULL)",
            name="ck_audit_events_target_pair",
        ),
        CheckConstraint(
            "target_type IS NULL OR target_type IN "
            "('user', 'prompt_list', 'prompt_version', 'room', 'app_config', "
            "'bug_report')",
            name="ck_audit_events_target_type",
        ),
        Index("ix_audit_events_target", "target_type", "target_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # What the action was performed on, when that is not a user - the takedown
    # of a prompt list, a change to server configuration. Kept beside
    # target_user_id rather than replacing it, because that column is a real
    # foreign key with ON DELETE SET NULL and this pair cannot be: it names
    # rows in whichever table the action touched. Null together for events that
    # act on no single row, such as a bulk retention purge.
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(PortableJSON, default=dict, nullable=False)
    # Indexed because the admin ledger reads newest-first on the authoritative
    # event time rather than on the (merely time-ordered) UUIDv7 id.
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False, index=True
    )


class PlayerReport(Base):
    """Actionable player report with a bounded evidence snapshot."""

    __tablename__ = "player_reports"
    __table_args__ = (
        _values_check("reason", REPORT_REASONS, "ck_player_reports_reason"),
        _values_check("status", REPORT_STATUSES, "ck_player_reports_status"),
        Index("ix_player_reports_status_created_at", "status", "created_at"),
        CheckConstraint(
            "reporter_user_id IS NULL OR reported_user_id IS NULL "
            "OR reporter_user_id != reported_user_id",
            name="ck_player_reports_not_self",
        ),
        # One open report per reporter per player, the same rule content
        # reports carry. Saying it again while a moderator has yet to look
        # adds no evidence and buries the queue; once the report is resolved
        # or dismissed the same reporter may raise a new one, because that is
        # a new incident rather than the same complaint repeated.
        Index(
            "uq_player_reports_open_target",
            "reporter_user_id",
            "reported_user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    # Reports are retained moderation evidence. Account anonymization therefore
    # detaches references rather than cascading away the report.
    reporter_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reported_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    game_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("game_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("turn_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reason: Mapped[str] = mapped_column(
        String(32), default=ReportReason.HARASSMENT.value, nullable=False
    )
    details: Mapped[str] = mapped_column(Text, nullable=False)
    context_snapshot: Mapped[dict] = mapped_column(
        PortableJSON, default=dict, server_default=text("'{}'"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16),
        default=ReportStatus.PENDING.value,
        server_default=ReportStatus.PENDING.value,
        nullable=False,
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    message_evidence: Mapped[list[PlayerReportMessageEvidence]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="PlayerReportMessageEvidence.position",
    )


class RoomMessage(Base):
    """Short-lived player-authored chat or guess with its real audience."""

    __tablename__ = "room_messages"
    __table_args__ = (
        _values_check(
            "message_kind", RETAINED_MESSAGE_KINDS, "ck_room_messages_kind"
        ),
        _values_check(
            "audience", RETAINED_MESSAGE_AUDIENCES, "ck_room_messages_audience"
        ),
        _values_check(
            "near_miss_kind", NEAR_MISS_KINDS, "ck_room_messages_near_miss_kind"
        ),
        CheckConstraint(
            "message_kind = 'wrong_guess' OR near_miss_kind IS NULL",
            name="ck_room_messages_near_miss_only_for_wrong_guess",
        ),
        CheckConstraint(
            "turn_id IS NULL OR game_id IS NOT NULL",
            name="ck_room_messages_turn_has_game",
        ),
        CheckConstraint(
            "message_kind = 'chat' OR (game_id IS NOT NULL AND turn_id IS NOT NULL)",
            name="ck_room_messages_guesses_have_turn",
        ),
        CheckConstraint(
            "expires_at > created_at", name="ck_room_messages_expiry_after_creation"
        ),
        # A lobby line has no room and no seat; a room line has both. Never
        # one without the other, so a null scope is a statement, not a gap.
        CheckConstraint(
            "(audience = 'lobby' AND room_instance_id IS NULL"
            " AND sender_player_id IS NULL)"
            " OR (audience <> 'lobby' AND room_instance_id IS NOT NULL"
            " AND sender_player_id IS NOT NULL)",
            name="ck_room_messages_lobby_has_no_scope",
        ),
        CheckConstraint(
            "audience <> 'lobby' OR message_kind = 'chat'",
            name="ck_room_messages_lobby_is_chat",
        ),
        Index("ix_room_messages_expires_at", "expires_at"),
        Index("ix_room_messages_game_turn_created", "game_id", "turn_id", "created_at"),
        Index("ix_room_messages_sender_created", "sender_user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    # Null for a lobby line, which is the only kind without a room.
    room_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=True, index=True
    )
    # Games and turns are allocated at runtime but written only when the game
    # completes. These durable correlation IDs intentionally do not use FKs so
    # live messages survive a process failure or an abandoned game.
    game_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=True
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=True
    )
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    sender_player_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=True
    )
    sender_seat_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=True
    )
    sender_display_name_snapshot: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    sender_name_color_snapshot: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    sender_is_anonymous_snapshot: Mapped[bool] = mapped_column(
        Boolean, nullable=False
    )
    is_spectator: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    message_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    audience: Mapped[str] = mapped_column(String(24), nullable=False)
    # Exact account recipients at send time, after Blocks are applied. Kept
    # only for the same short retention window and used to authorize evidence
    # selection without exposing a transcript API.
    audience_user_ids: Mapped[list] = mapped_column(PortableJSON, default=list, nullable=False)
    near_miss_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class PlayerReportMessageEvidence(Base):
    """Immutable message copy pinned by a player report beyond normal expiry."""

    __tablename__ = "player_report_message_evidence"
    __table_args__ = (
        UniqueConstraint(
            "report_id",
            "source_message_snapshot_id",
            name="uq_report_message_evidence_source",
        ),
        _values_check(
            "message_kind",
            RETAINED_MESSAGE_KINDS,
            "ck_report_message_evidence_kind",
        ),
        _values_check(
            "audience",
            RETAINED_MESSAGE_AUDIENCES,
            "ck_report_message_evidence_audience",
        ),
        _values_check(
            "near_miss_kind",
            NEAR_MISS_KINDS,
            "ck_report_message_evidence_near_miss_kind",
        ),
        CheckConstraint(
            "message_kind = 'wrong_guess' OR near_miss_kind IS NULL",
            name="ck_report_message_evidence_near_miss_only_for_wrong_guess",
        ),
        CheckConstraint("position >= 0", name="ck_report_message_evidence_position"),
    )

    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("player_reports.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("room_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_message_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=False
    )
    game_id_snapshot: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=True
    )
    turn_id_snapshot: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=True
    )
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sender_display_name_snapshot: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    sender_name_color_snapshot: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    sender_is_anonymous_snapshot: Mapped[bool] = mapped_column(
        Boolean, nullable=False
    )
    message_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    audience: Mapped[str] = mapped_column(String(24), nullable=False)
    near_miss_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    text_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    message_created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False
    )
    copied_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    report: Mapped[PlayerReport] = relationship(back_populates="message_evidence")


class PromptContentReport(Base):
    """Durable evidence and review state for one player-authored list or prompt."""

    __tablename__ = "prompt_content_reports"
    __table_args__ = (
        _values_check(
            "reason",
            PROMPT_CONTENT_REPORT_REASONS,
            "ck_prompt_content_reports_reason",
        ),
        _values_check(
            "status", REPORT_STATUSES, "ck_prompt_content_reports_status"
        ),
        _values_check(
            "resolution_moderation_state",
            PROMPT_CONTENT_MODERATION_STATES,
            "ck_prompt_content_reports_resolution_state",
        ),
        CheckConstraint(
            "target_type IN ('list', 'prompt')",
            name="ck_prompt_content_reports_target_type",
        ),
        CheckConstraint(
            "(target_type = 'list' AND prompt_snapshot IS NULL) OR "
            "(target_type = 'prompt' AND prompt_snapshot IS NOT NULL)",
            name="ck_prompt_content_reports_target_snapshot",
        ),
        CheckConstraint(
            "reporter_user_id IS NULL OR reported_owner_user_id IS NULL "
            "OR reporter_user_id != reported_owner_user_id",
            name="ck_prompt_content_reports_not_self",
        ),
        Index(
            "ix_prompt_content_reports_status_created_at", "status", "created_at"
        ),
        # One open report per reporter per target. Reporting the same content
        # again while a moderator has yet to look at it adds no evidence and
        # buries the queue; once a report is resolved or dismissed the same
        # reporter may raise a new one, because that is a new incident.
        # Two indexes rather than one because NULL is distinct from NULL in a
        # unique index, so a list-level report would never collide with itself.
        Index(
            "uq_prompt_content_reports_open_list",
            "reporter_user_id",
            "prompt_list_id",
            unique=True,
            postgresql_where=text(
                "status = 'pending' AND prompt_version_id IS NULL"
            ),
            sqlite_where=text("status = 'pending' AND prompt_version_id IS NULL"),
        ),
        Index(
            "uq_prompt_content_reports_open_prompt",
            "reporter_user_id",
            "prompt_version_id",
            unique=True,
            postgresql_where=text(
                "status = 'pending' AND prompt_version_id IS NOT NULL"
            ),
            sqlite_where=text(
                "status = 'pending' AND prompt_version_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    reporter_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reported_owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    prompt_list_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_lists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    list_name_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(
        String(32),
        default=PromptContentReportReason.INAPPROPRIATE.value,
        nullable=False,
    )
    details: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        default=ReportStatus.PENDING.value,
        server_default=ReportStatus.PENDING.value,
        nullable=False,
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_moderation_state: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class BugReport(Base):
    """A player's report that the app itself is broken.

    Deliberately not a moderation row. A bug report is about the software, not
    about a person, and it carries build and diagnostic data rather than
    safety evidence - two different audiences, two different confidentiality
    regimes. It reuses `ReportStatus` because the review semantics really are
    identical: one pending row receives one decision.

    Context arrives in two halves that must not be confused. `client_context`
    is what the reporter's browser said about itself and is evidence supplied
    by a player; `server_context` is what this server knew about their seat at
    the moment they filed, and is the only half a reader may treat as fact.

    There is no "one open report per reporter" rule here, unlike every other
    report table. That rule exists to stop the same complaint about the same
    person being repeated; a player who meets three unrelated bugs in one
    session is not repeating themselves. Volume is bounded by the rate limiter.
    """

    __tablename__ = "bug_reports"
    __table_args__ = (
        _values_check("area", BUG_REPORT_AREAS, "ck_bug_reports_area"),
        _values_check("severity", BUG_REPORT_SEVERITIES, "ck_bug_reports_severity"),
        _values_check("status", REPORT_STATUSES, "ck_bug_reports_status"),
        _values_check(
            "screenshot_status",
            BUG_REPORT_SCREENSHOT_STATUSES,
            "ck_bug_reports_screenshot_status",
        ),
        # A row claiming to hold a screenshot holds one, with the identity
        # needed to serve and verify it.
        CheckConstraint(
            "screenshot_status <> 'ready' OR ("
            "screenshot_payload IS NOT NULL AND screenshot_byte_size IS NOT NULL "
            "AND screenshot_checksum_sha256 IS NOT NULL "
            "AND screenshot_content_type IS NOT NULL)",
            name="ck_bug_reports_screenshot_ready_identity",
        ),
        # Erasure is structural, not procedural: deciding a report drops the
        # picture, and no future code path can leave the pixels behind.
        CheckConstraint(
            "screenshot_status <> 'erased' OR screenshot_payload IS NULL",
            name="ck_bug_reports_screenshot_erased",
        ),
        CheckConstraint(
            "screenshot_status <> 'none' OR screenshot_payload IS NULL",
            name="ck_bug_reports_screenshot_absent",
        ),
        CheckConstraint(
            "screenshot_byte_size IS NULL OR ("
            "screenshot_byte_size > 0 AND screenshot_byte_size <= 2097152)",
            name="ck_bug_reports_screenshot_byte_size",
        ),
        # A decision is a decision: reviewed rows carry who and when.
        CheckConstraint(
            "status = 'pending' OR reviewed_at IS NOT NULL",
            name="ck_bug_reports_reviewed_identity",
        ),
        Index("ix_bug_reports_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    # Detached rather than cascaded on deletion: the bug outlives the account
    # that met it, and a fixed defect should not be un-fixed by an erasure.
    reporter_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    area: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)

    # Pulled out of `client_context` so a queue can be filtered and grouped by
    # them without parsing JSON - the two questions every triage starts with
    # are "which build" and "which screen".
    build_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    route: Mapped[str | None] = mapped_column(String(255), nullable=True)
    room_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Not foreign keys: a live game is not written to `game_records` until it
    # finishes, so at filing time these name rows that may not exist yet.
    game_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=True
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=True
    )

    client_context: Mapped[dict] = mapped_column(PortableJSON, default=dict, nullable=False)
    server_context: Mapped[dict] = mapped_column(PortableJSON, default=dict, nullable=False)

    screenshot_status: Mapped[str] = mapped_column(
        String(16),
        default=BugReportScreenshotStatus.NONE.value,
        server_default=BugReportScreenshotStatus.NONE.value,
        nullable=False,
    )
    screenshot_payload: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    screenshot_content_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    screenshot_byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screenshot_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screenshot_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The server's own digest of the bytes it stored, never the sender's claim.
    screenshot_checksum_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(16),
        default=ReportStatus.PENDING.value,
        server_default=ReportStatus.PENDING.value,
        nullable=False,
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class UserBan(Base):
    """Audited temporary or permanent suspension of an account."""

    __tablename__ = "user_bans"
    __table_args__ = (
        Index("ix_user_bans_user_active_expires", "user_id", "is_active", "expires_at"),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_user_bans_expiry_after_creation",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    banned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    # The report this suspension was decided from, when it came from one. It is
    # what lets the suspended player be shown the messages the complaint was
    # about, rather than a reason with nothing behind it. Nullable because a
    # suspension can be issued directly, and SET NULL because the suspension
    # outlives the report if the report is ever removed.
    source_report_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("player_reports.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoke_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)


class UserWarning(Base):
    """A moderator's formal warning: shown to the player once, then kept.

    The step between dismissing a report and suspending the account. It does
    not restrict anything - the player is told what was reported and that a
    moderator looked, and the acknowledgement records that the message
    actually reached them.
    """

    __tablename__ = "user_warnings"
    __table_args__ = (
        Index("ix_user_warnings_user_pending", "user_id", "acknowledged_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    issued_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    # The report this warning was decided from. It is what lets the warned
    # player be shown the messages the complaint was about; SET NULL because
    # the warning outlives the report if the report is ever removed.
    source_report_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("player_reports.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )


class RoleChangeNotice(Base):
    """What an account still has to be told about its own role.

    The role itself lives on `users.role`; this is only the message. It exists
    for the same reason `user_warnings` does: an administrator acts while the
    player is asleep, and a **Moderation** entry that appears - or vanishes -
    with no explanation is a change nobody can ask about. A connected account
    hears it on the socket, everybody else on their next visit, and
    acknowledging records that the notice actually landed.

    No actor column. Who acted, and the reason they gave, are the audit
    ledger's job and are written there in the same transaction; the reason in
    particular is text one administrator wrote for another and can name a
    report or a second account, so it deliberately has no route to the person
    it is about.
    """

    __tablename__ = "role_change_notices"
    __table_args__ = (
        # The grantable roles, not every role: `admin` is never set over the
        # network, so a notice about one is a row that could only arrive by
        # mistake - and the client drops what it cannot explain rather than
        # showing a player a pop-up about a role nobody gave them.
        _values_check("role", GRANTABLE_ROLES, "ck_role_change_notices_role"),
        Index("ix_role_change_notices_user_pending", "user_id", "acknowledged_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The role the account holds now, not the step it took: a notice read late
    # should describe where the account stands, and `users.role` is the only
    # thing that can contradict it.
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )


class UserBlock(Base):
    """Directional player block used to mute ordinary social interaction."""

    __tablename__ = "user_blocks"
    __table_args__ = (
        CheckConstraint(
            "blocker_user_id != blocked_user_id", name="chk_no_self_block"
        ),
        Index("ix_user_blocks_blocked_user_id", "blocked_user_id"),
    )

    # The pair is the identity: nothing references a block by anything else,
    # and a surrogate id was one more column, one more index, and one more
    # thing for the merge path to deduplicate around.
    blocker_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    blocked_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )


class Friendship(Base):
    """A mutual friendship, or a request on its way to becoming one.

    **One row per pair, in a canonical order**, rather than one row per
    direction. Two directional rows can disagree - one accepted, one not - and
    no constraint can forbid it; here the pair *is* the identity, the way it is
    for `user_blocks`. It also settles the case #529 was really asking about:
    a crossing request, where A asks B while B has already asked A, collides on
    the primary key instead of creating a second row, so the handler sees a
    pending request from the other party and accepts it.

    The columns are named for the invariant they hold. `ck_friendships_ordered`
    makes it unfalsifiable and forbids a self-friendship for free, since
    `x < x` is false. Canonicalisation lives in exactly one place -
    `app.services.friends.friendship_key` - and a site that forgets it writes a
    row this CHECK rejects, which is the failure worth having.
    """

    __tablename__ = "friendships"
    __table_args__ = (
        CheckConstraint("user_low_id < user_high_id", name="ck_friendships_ordered"),
        CheckConstraint(
            "requested_by_id = user_low_id OR requested_by_id = user_high_id",
            name="ck_friendships_requester_is_a_member",
        ),
        _values_check("status", FRIENDSHIP_STATES, "ck_friendships_status"),
        Index("ix_friendships_user_high_id", "user_high_id"),
        Index("ix_friendships_requested_by_id", "requested_by_id"),
    )

    user_low_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_high_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Which of the pair asked. Needed to answer an incoming request from an
    # outgoing one, and to let the decliner ask in their own right later.
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=FriendshipState.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class IdentityAlias(Base):
    """Immutable mapping from a merged guest identity to its account."""

    __tablename__ = "identity_aliases"
    __table_args__ = (
        CheckConstraint(
            "source_user_id != target_user_id", name="ck_identity_alias_distinct"
        ),
    )

    # The merged guest is the identity: one row per source, so the column
    # that was unique anyway is the key.
    source_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    target_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )


class UploadedAvatarAsset(Base):
    """Reserved ownership/metadata row for a future moderated upload flow."""

    __tablename__ = "uploaded_avatar_assets"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )


class ExternalIdentity(Base):
    """Reserved link to a future authenticated external identity provider."""

    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_external_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )


class AuthSession(Base):
    """Revocable server-side session identified by a hashed opaque token."""

    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    device_label: Mapped[str] = mapped_column(String(64), nullable=False)
    rotated_from_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("auth_sessions.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    # Indexed for the retention sweep and for every resolution path, all of
    # which filter on it.
    expires_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class DataExport(Base):
    """Durable asynchronous snapshot of the data belonging to one account."""

    __tablename__ = "data_exports"
    __table_args__ = (
        _values_check("status", DATA_EXPORT_STATUSES, "ck_data_exports_status"),
        _values_check(
            "artifact_encoding",
            DATA_EXPORT_ARTIFACT_ENCODINGS,
            "ck_data_exports_artifact_encoding",
        ),
        # A stored document says how to read itself, and a row with no
        # document claims no encoding.
        CheckConstraint(
            "(artifact IS NULL) = (artifact_encoding IS NULL)",
            name="ck_data_exports_artifact_encoding_present",
        ),
        Index("ix_data_exports_user_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        default=DataExportStatus.PENDING.value,
        server_default=DataExportStatus.PENDING.value,
        nullable=False,
    )
    schema_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    # The finished document, compressed: it is the largest single non-blob
    # value in the schema and is highly repetitive JSON. The encoding is stored
    # beside it rather than assumed, so a later format is a new discriminator
    # rather than a migration - the same rule `canvas_storage` applies to
    # drawings.
    artifact: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    artifact_encoding: Mapped[str | None] = mapped_column(String(16), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, index=True
    )


class GameRecord(Base):
    """Finished multiplayer game summary."""

    __tablename__ = "game_records"
    __table_args__ = (
        _values_check(
            "scoring_mode", SCORING_MODES, "ck_game_records_scoring_mode"
        ),
        _values_check("hint_mode", HINT_MODES, "ck_game_records_hint_mode"),
        CheckConstraint(
            "scoring_version >= 0", name="ck_game_records_scoring_version"
        ),
        CheckConstraint(
            "score_ledger_version >= 0",
            name="ck_game_records_score_ledger_version",
        ),
        CheckConstraint(
            "rule_snapshot_version >= 0",
            name="ck_game_records_rule_snapshot_version",
        ),
        _values_check(
            "prompt_source_mode",
            GAME_PROMPT_SOURCE_MODES,
            "ck_game_records_prompt_source_mode",
        ),
        # The same bounds the room-settings tables pin, minus the exact
        # drawing-seconds value set: a recorded duration is a historical fact,
        # and pinning today's permitted values here would make changing that
        # set fail writes with no migration. Table-level, unlike `outcome`'s
        # column-attached check below: the cascade risk that placement dodged
        # applies to a rebuild with foreign keys ON, and migrations run with
        # them OFF - and the time-order check spans two columns anyway.
        CheckConstraint("player_count >= 1", name="ck_game_records_player_count"),
        CheckConstraint("total_rounds >= 1", name="ck_game_records_total_rounds"),
        CheckConstraint(
            "drawing_seconds > 0", name="ck_game_records_drawing_seconds"
        ),
        CheckConstraint(
            "started_at <= finished_at", name="ck_game_records_time_order"
        ),
        Index("ix_game_records_outcome_finished_at", "outcome", "finished_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    payload_hash: Mapped[str] = mapped_column(
        String(64), default="", server_default="", nullable=False
    )
    room_name: Mapped[str] = mapped_column(String(64), nullable=False)
    scoring_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    # Version zero/empty JSON identify legacy/manual rows whose exact rules are
    # unknown. Production game writes always provide the current versions.
    scoring_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    score_ledger_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    rule_snapshot_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    rule_snapshot: Mapped[dict] = mapped_column(
        PortableJSON, default=dict, server_default=text("'{}'"), nullable=False
    )
    # Python-side default only, mirroring the writer-facing dataclasses: a
    # game whose pool carries no curated identity is custom by definition.
    # No server default - a raw insert must say what it stored.
    prompt_source_mode: Mapped[str] = mapped_column(
        String(24), default="custom", nullable=False
    )
    hint_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    drawing_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    total_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    player_count: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    # Indexed because every read of a player's history sorts on it: the page
    # query filters to the games they took part in and takes the newest first,
    # which without this orders the whole matching set on each request.
    finished_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, index=True
    )
    # How it ended, not whether it did. Deliberately not expressed by making
    # finished_at nullable: every query that orders a player's history by it
    # keeps working, and a game that stopped still stopped at a knowable time.
    #
    # The check rides on the column rather than sitting in __table_args__,
    # matching where SQLite already keeps `prompt_source_mode`'s. A table-level
    # one could only be added by rebuilding game_records, and rebuilding it
    # cascades every child row away.
    outcome: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "outcome IN ('finished', 'abandoned', 'shutdown')",
            name="ck_game_records_outcome",
        ),
        default=GameOutcome.FINISHED.value,
        server_default=text("'finished'"),
        nullable=False,
    )
    # Deliberately distinct from game event time; supports save-lag and
    # retry diagnosis.
    persisted_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    participants: Mapped[list[GameParticipant]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
    )
    turns: Mapped[list[TurnRecord]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
    )
    prompt_sources: Mapped[list[GamePromptSource]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
    )
    score_events: Mapped[list[ScoreEvent]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
        order_by="ScoreEvent.event_order",
    )


class PlannedShutdownAbandonment(Base):
    """Privacy-safe fact that a planned drain expired with a game still live."""

    __tablename__ = "planned_shutdown_abandonments"
    __table_args__ = (
        CheckConstraint("contract_version = 1", name="ck_shutdown_abandonment_contract"),
        _values_check(
            "reason",
            ("drain_timeout",),
            "ck_shutdown_abandonment_reason",
        ),
        _values_check(
            "phase",
            ("choosing_prompt", "drawing", "turn_results", "game_end"),
            "ck_shutdown_abandonment_phase",
        ),
        CheckConstraint(
            "round_number >= 0 AND completed_turn_count >= 0",
            name="ck_shutdown_abandonment_progress",
        ),
        CheckConstraint(
            "seated_player_count >= 0 AND connected_player_count >= 0 "
            "AND spectator_count >= 0 AND canvas_action_count >= 0",
            name="ck_shutdown_abandonment_counts",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    # A partial game intentionally has no game_records parent. Its runtime ID
    # remains the idempotency/correlation key without pretending it finished.
    game_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=False, unique=True, index=True
    )
    room_instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=False, index=True
    )
    contract_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    phase: Mapped[str] = mapped_column(String(24), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_turn_count: Mapped[int] = mapped_column(Integer, nullable=False)
    seated_player_count: Mapped[int] = mapped_column(Integer, nullable=False)
    connected_player_count: Mapped[int] = mapped_column(Integer, nullable=False)
    spectator_count: Mapped[int] = mapped_column(Integer, nullable=False)
    canvas_action_count: Mapped[int] = mapped_column(Integer, nullable=False)
    game_started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False, index=True
    )


class GamePromptSource(Base):
    """One exact immutable prompt-list revision present in a game's real pool."""

    __tablename__ = "game_prompt_sources"

    game_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("game_records.id", ondelete="CASCADE"),
        primary_key=True,
    )
    prompt_list_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_list_revisions.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    )

    game: Mapped[GameRecord] = relationship(back_populates="prompt_sources")


class GameParticipant(Base):
    """Player participation and final standing in a finished game."""

    __tablename__ = "game_participants"
    __table_args__ = (
        Index("uq_game_participants_game_user", "game_id", "user_id", unique=True),
        CheckConstraint(
            "final_rank IS NULL OR final_rank >= 1",
            name="ck_game_participants_final_rank",
        ),
        # Lets children reference the seat *together with its game*, so a row
        # naming a seat from another game is a constraint violation instead of
        # a plausible-looking lie (see score_events, turn_records, outcomes).
        UniqueConstraint("game_id", "id", name="uq_game_participants_game_id_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    game_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("game_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    display_name_snapshot: Mapped[str] = mapped_column(
        String(32), default="Unknown", nullable=False
    )
    name_color_snapshot: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_anonymous_snapshot: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    final_score: Mapped[int] = mapped_column(Integer, nullable=False)
    # Null for a game that did not finish: a rank is a claim about how a game
    # ended, and an abandoned one did not end (R-HIST-06). The score stays -
    # points earned in the turns that were played are a fact.
    final_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Turns this player was still in the rotation for. A one-round walkout and
    # a full game otherwise look identical, which skews win rate and averages.
    turns_played: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    game: Mapped[GameRecord] = relationship(back_populates="participants")
    user: Mapped[User | None] = relationship()


class TurnRecord(Base):
    """Individual round turn details within a finished game."""

    __tablename__ = "turn_records"
    __table_args__ = (
        Index(
            "uq_turn_records_game_round_turn",
            "game_id",
            "round_number",
            "turn_number",
            unique=True,
        ),
        _values_check(
            "end_reason", TURN_END_REASONS, "ck_turn_records_end_reason"
        ),
        _values_check(
            "prompt_source_kind",
            PROMPT_SOURCE_KINDS,
            "ck_turn_records_prompt_source_kind",
        ),
        CheckConstraint(
            "(prompt_source_kind = 'curated' AND prompt_version_id IS NOT NULL) "
            "OR (prompt_source_kind != 'curated' AND prompt_version_id IS NULL)",
            name="ck_turn_records_prompt_identity",
        ),
        CheckConstraint(
            "duration_seconds > 0", name="ck_turn_records_duration"
        ),
        CheckConstraint(
            "round_number >= 1 AND turn_number >= 1 AND guesser_count >= 0 "
            "AND wrong_guess_count >= 0 AND near_miss_count >= 0 "
            "AND stroke_count >= 0",
            name="ck_turn_records_counts_nonnegative",
        ),
        UniqueConstraint("game_id", "id", name="uq_turn_records_game_id_id"),
        # The drawer's seat must belong to this turn's game. CASCADE for the
        # same reason as before: a seat only ever goes with its whole game.
        ForeignKeyConstraint(
            ["game_id", "drawer_participant_id"],
            ["game_participants.game_id", "game_participants.id"],
            name="fk_turn_records_drawer_seat_same_game",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    game_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("game_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    drawer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The factual game seat is authoritative; account linkage may be null,
    # the seat itself never is. Referenced together with game_id by the
    # same-game constraint in __table_args__.
    drawer_participant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=False, index=True
    )
    drawer_display_name_snapshot: Mapped[str] = mapped_column(
        String(32), default="Unknown", nullable=False
    )
    drawer_name_color_snapshot: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    drawer_is_anonymous_snapshot: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    prompt: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    prompt_source_kind: Mapped[str] = mapped_column(
        String(24), default="custom", nullable=False
    )
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    # How many player seats were eligible when drawing began. Correct-guess
    # counts are uninterpretable without it: two of two is not two of eight.
    guesser_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # The drawer let the clock run out and took the first offered prompt. Not a
    # preference, and it should not be counted as one.
    prompt_auto_picked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    # Canvas actions committed during the turn: separates an impossible prompt
    # from a drawer who drew nothing.
    stroke_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # "all_guessed" or "timeout". A turn whose drawer leaves never completes,
    # so it is never recorded and cannot appear here.
    end_reason: Mapped[str] = mapped_column(
        String(16),
        default=TurnEndReason.TIMEOUT.value,
        server_default=TurnEndReason.TIMEOUT.value,
        nullable=False,
    )
    wrong_guess_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    near_miss_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    game: Mapped[GameRecord] = relationship(back_populates="turns")
    drawer: Mapped[User | None] = relationship()
    guesses: Mapped[list[TurnGuess]] = relationship(
        back_populates="turn_record",
        cascade="all, delete-orphan",
    )
    prompt_offers: Mapped[list[TurnPromptOffer]] = relationship(
        back_populates="turn_record",
        cascade="all, delete-orphan",
        order_by="TurnPromptOffer.position",
    )
    participant_outcomes: Mapped[list[TurnParticipantOutcome]] = relationship(
        back_populates="turn_record",
        cascade="all, delete-orphan",
    )
    # The relationships below exist for the unit of work as much as for
    # reads: composite table-level constraints alone give the flush no
    # ordering edge, so each references its parent through an explicit join.
    drawer_seat: Mapped[GameParticipant] = relationship(
        primaryjoin="GameParticipant.id == foreign(TurnRecord.drawer_participant_id)",
        viewonly=False,
    )
    drawing: Mapped[TurnDrawing | None] = relationship(
        back_populates="turn_record",
        cascade="all, delete-orphan",
        uselist=False,
    )


class TurnDrawing(Base):
    """The drawing made during one turn, kept for as long as its game.

    The blob is the exact frame the canvas produced, stored verbatim; the format
    it declares in its own first bytes decides which decoder reads it back.
    ``app/canvas_storage.py`` holds the rules that keep that readable.
    """

    __tablename__ = "turn_drawings"
    __table_args__ = (
        _values_check("status", TURN_DRAWING_STATUSES, "ck_turn_drawings_status"),
        CheckConstraint(
            "status <> 'ready' OR ("
            "format_magic IS NOT NULL AND format_version IS NOT NULL "
            "AND byte_size IS NOT NULL AND checksum_sha256 IS NOT NULL "
            "AND (payload IS NOT NULL OR object_key IS NOT NULL))",
            name="ck_turn_drawings_ready_identity",
        ),
        # Erasure is structural, not procedural: no future code path can leave
        # bytes behind on a row that says the drawing is gone.
        CheckConstraint(
            "status NOT IN ('unavailable', 'deleted') OR payload IS NULL",
            name="ck_turn_drawings_erased",
        ),
        CheckConstraint(
            "(status = 'unavailable') = (unavailable_reason IS NOT NULL)",
            name="ck_turn_drawings_unavailable_reason",
        ),
        # A structural sanity bound, deliberately not the exact protocol limit:
        # that one is derived from the action and point caps, so pinning it here
        # would make raising either of them fail writes with no migration.
        CheckConstraint(
            "byte_size IS NULL OR (byte_size > 0 AND byte_size <= 8388608)",
            name="ck_turn_drawings_byte_size",
        ),
        Index("ix_turn_drawings_status_created_at", "status", "created_at"),
    )

    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("turn_records.id", ondelete="CASCADE"),
        primary_key=True,
    )
    game_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("game_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Read from the blob rather than assumed, so a row can be found by format
    # without parsing bytes.
    format_magic: Mapped[str | None] = mapped_column(String(4), nullable=True)
    format_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Reserved for the day drawings move to object storage; a stored key and a
    # stored payload are alternatives, which the ready-identity check accepts
    # either way.
    object_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    unavailable_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    stored_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    turn_record: Mapped[TurnRecord] = relationship(back_populates="drawing")


class ScoreEvent(Base):
    """Ordered append-only point delta beside a participant's cached score."""

    __tablename__ = "score_events"
    __table_args__ = (
        UniqueConstraint("game_id", "event_order", name="uq_score_events_game_order"),
        UniqueConstraint("game_id", "id", name="uq_score_events_game_id_id"),
        # Same-game coherence, structurally: an event cannot award points to a
        # seat, charge a turn, or correct an entry that belongs to another
        # game. The writer proves the arithmetic; these prove the addressing.
        ForeignKeyConstraint(
            ["game_id", "participant_id"],
            ["game_participants.game_id", "game_participants.id"],
            name="fk_score_events_seat_same_game",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["game_id", "turn_id"],
            ["turn_records.game_id", "turn_records.id"],
            name="fk_score_events_turn_same_game",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["game_id", "corrects_event_id"],
            ["score_events.game_id", "score_events.id"],
            name="fk_score_events_correction_same_game",
            ondelete="RESTRICT",
        ),
        _values_check("event_type", SCORE_EVENT_TYPES, "ck_score_events_event_type"),
        CheckConstraint("event_order > 0", name="ck_score_events_order_positive"),
        CheckConstraint("points_delta != 0", name="ck_score_events_delta_nonzero"),
        CheckConstraint(
            "scoring_version >= 0 AND rule_snapshot_version >= 0",
            name="ck_score_events_versions_nonnegative",
        ),
        CheckConstraint(
            "(event_type IN ('guess_award', 'drawer_bonus') AND points_delta > 0) "
            "OR (event_type = 'hint_charge' AND points_delta < 0) "
            "OR event_type = 'correction'",
            name="ck_score_events_delta_direction",
        ),
        CheckConstraint(
            "(event_type = 'correction' AND corrects_event_id IS NOT NULL) OR "
            "(event_type != 'correction' AND corrects_event_id IS NULL)",
            name="ck_score_events_correction_target",
        ),
        CheckConstraint(
            "event_type = 'correction' OR turn_id IS NOT NULL",
            name="ck_score_events_turn_required",
        ),
        CheckConstraint(
            "corrects_event_id IS NULL OR id != corrects_event_id",
            name="ck_score_events_not_self_correction",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    game_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("game_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=False, index=True
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=True, index=True
    )
    event_order: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    points_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    scoring_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    corrects_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    game: Mapped[GameRecord] = relationship(
        back_populates="score_events", foreign_keys=[game_id]
    )
    # Flush-ordering edges (see TurnRecord.drawer_seat).
    participant: Mapped[GameParticipant] = relationship(
        primaryjoin="GameParticipant.id == foreign(ScoreEvent.participant_id)",
    )
    turn_record: Mapped[TurnRecord | None] = relationship(
        primaryjoin="TurnRecord.id == foreign(ScoreEvent.turn_id)",
    )
    corrected_event: Mapped[ScoreEvent | None] = relationship(
        primaryjoin="remote(ScoreEvent.id) == foreign(ScoreEvent.corrects_event_id)",
    )


class TurnParticipantOutcome(Base):
    """One participant seat's eligibility and terminal result for a turn."""

    __tablename__ = "turn_participant_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "turn_id",
            "participant_id",
            name="uq_turn_participant_outcomes_turn_participant",
        ),
        UniqueConstraint(
            "turn_id", "id", name="uq_turn_participant_outcomes_turn_id_id"
        ),
        # game_id is denormalized precisely so these can exist: the turn and
        # the seat must belong to the same game as the outcome that joins
        # them, and each other by transitivity.
        ForeignKeyConstraint(
            ["game_id", "turn_id"],
            ["turn_records.game_id", "turn_records.id"],
            name="fk_turn_participant_outcomes_turn_same_game",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["game_id", "participant_id"],
            ["game_participants.game_id", "game_participants.id"],
            name="fk_turn_participant_outcomes_seat_same_game",
            ondelete="CASCADE",
        ),
        _values_check(
            "eligibility_reason",
            TURN_ELIGIBILITY_REASONS,
            "ck_turn_participant_outcomes_eligibility_reason",
        ),
        _values_check(
            "outcome",
            TURN_PARTICIPANT_OUTCOMES,
            "ck_turn_participant_outcomes_outcome",
        ),
        _values_check(
            "terminal_state",
            TURN_PARTICIPANT_STATES,
            "ck_turn_participant_outcomes_terminal_state",
        ),
        CheckConstraint(
            "(eligible AND eligibility_reason = 'eligible' "
            "AND outcome != 'ineligible') OR "
            "(NOT eligible AND eligibility_reason != 'eligible' "
            "AND outcome = 'ineligible')",
            name="ck_turn_participant_outcomes_eligibility",
        ),
        CheckConstraint(
            "(outcome = 'correct' AND correct_guess_time_seconds IS NOT NULL) OR "
            "(outcome != 'correct' AND correct_guess_time_seconds IS NULL)",
            name="ck_turn_participant_outcomes_correct_time",
        ),
        CheckConstraint(
            "wrong_guess_count >= 0 AND near_miss_count >= 0 "
            "AND hints_used >= 0 AND points_spent_on_hints >= 0",
            name="ck_turn_participant_outcomes_nonnegative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    game_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=False
    )
    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=False
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=False, index=True
    )
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    eligibility_reason: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    terminal_state: Mapped[str] = mapped_column(String(24), nullable=False)
    correct_guess_time_seconds: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    wrong_guess_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    near_miss_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    hints_used: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    points_spent_on_hints: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    turn_record: Mapped[TurnRecord] = relationship(
        back_populates="participant_outcomes",
        foreign_keys=[game_id, turn_id],
    )
    # Flush-ordering edge (see TurnRecord.drawer_seat).
    participant: Mapped[GameParticipant] = relationship(
        primaryjoin=(
            "GameParticipant.id == foreign(TurnParticipantOutcome.participant_id)"
        ),
    )
    correct_guess: Mapped[TurnGuess | None] = relationship(
        back_populates="outcome",
        uselist=False,
        primaryjoin=(
            "TurnParticipantOutcome.id == foreign(TurnGuess.outcome_id)"
        ),
    )


class TurnPromptOffer(Base):
    """An immutable prompt option and source snapshot offered for one turn."""

    __tablename__ = "turn_prompt_offers"
    __table_args__ = (
        UniqueConstraint(
            "turn_id", "position", name="uq_turn_prompt_offers_turn_position"
        ),
        CheckConstraint("position >= 0", name="ck_turn_prompt_offers_position"),
        _values_check(
            "source_kind",
            PROMPT_OFFER_SOURCE_KINDS,
            "ck_turn_prompt_offers_source_kind",
        ),
        Index(
            "uq_turn_prompt_offers_selected",
            "turn_id",
            unique=True,
            sqlite_where=text("selected = 1"),
            postgresql_where=text("selected"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("turn_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    prompt_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    turn_record: Mapped[TurnRecord] = relationship(back_populates="prompt_offers")
    sources: Mapped[list[TurnPromptOfferSource]] = relationship(
        back_populates="offer", cascade="all, delete-orphan"
    )


class TurnPromptOfferSource(Base):
    """One list revision that contained an offered curated prompt version."""

    __tablename__ = "turn_prompt_offer_sources"

    offer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("turn_prompt_offers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    prompt_list_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_list_revisions.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    )

    offer: Mapped[TurnPromptOffer] = relationship(back_populates="sources")


class TurnGuess(Base):
    """Optional scoring child for a participant's correct turn outcome."""

    __tablename__ = "turn_guesses"
    __table_args__ = (
        Index(
            "uq_turn_guesses_turn_participant",
            "turn_id",
            "participant_id",
            unique=True,
        ),
        Index("uq_turn_guesses_outcome", "outcome_id", unique=True),
        # The outcome must belong to the same turn as the guess it scores.
        ForeignKeyConstraint(
            ["turn_id", "outcome_id"],
            ["turn_participant_outcomes.turn_id", "turn_participant_outcomes.id"],
            name="fk_turn_guesses_outcome_same_turn",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("turn_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    participant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("game_participants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    outcome_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=False
    )
    display_name_snapshot: Mapped[str] = mapped_column(
        String(32), default="Unknown", nullable=False
    )
    name_color_snapshot: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_anonymous_snapshot: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    points_awarded: Mapped[int] = mapped_column(Integer, nullable=False)
    guess_time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    # Attempt and hint facts live on the parent outcome row alone - two
    # records of one fact were two chances to disagree.
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    turn_record: Mapped[TurnRecord] = relationship(
        back_populates="guesses", foreign_keys=[turn_id]
    )
    # Flush-ordering edge (see TurnRecord.drawer_seat): outcomes must land
    # before the guesses that reference them.
    outcome: Mapped[TurnParticipantOutcome] = relationship(
        back_populates="correct_guess",
        primaryjoin=(
            "TurnParticipantOutcome.id == foreign(TurnGuess.outcome_id)"
        ),
    )
    user: Mapped[User | None] = relationship()


class PromptConcept(Base):
    """Stable prompt identity shared only by explicit references."""

    __tablename__ = "prompt_concepts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    versions: Mapped[list[PromptVersion]] = relationship(
        back_populates="concept", cascade="all, delete-orphan"
    )
    aliases: Mapped[list[PromptAlias]] = relationship(
        back_populates="concept", cascade="all, delete-orphan"
    )


class PromptVersion(Base):
    """Immutable language-specific answer and editorial metadata."""

    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint(
            "concept_id",
            "language",
            "version",
            name="uq_prompt_version_concept_language_version",
        ),
        _values_check(
            "language", PROMPT_LANGUAGES, "ck_prompt_versions_language"
        ),
        _values_check(
            "editorial_difficulty",
            PROMPT_EDITORIAL_DIFFICULTIES,
            "ck_prompt_versions_editorial_difficulty",
        ),
        _values_check(
            "content_rating",
            PROMPT_CONTENT_RATINGS,
            "ck_prompt_versions_content_rating",
        ),
        _values_check(
            "moderation_state",
            PROMPT_CONTENT_MODERATION_STATES,
            "ck_prompt_versions_moderation_state",
        ),
        CheckConstraint("version >= 1", name="ck_prompt_versions_version_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_concepts.id", ondelete="CASCADE"),
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    canonical_answer: Mapped[str] = mapped_column(String(64), nullable=False)
    match_key: Mapped[str] = mapped_column(String(64), nullable=False)
    editorial_difficulty: Mapped[str] = mapped_column(
        String(16),
        default=PromptEditorialDifficulty.UNSPECIFIED.value,
        server_default=PromptEditorialDifficulty.UNSPECIFIED.value,
        nullable=False,
    )
    content_rating: Mapped[str] = mapped_column(
        String(16),
        default=PromptContentRating.EVERYONE.value,
        server_default=PromptContentRating.EVERYONE.value,
        nullable=False,
    )
    moderation_state: Mapped[str] = mapped_column(
        String(16),
        default=PromptContentModerationState.ACTIVE.value,
        server_default=PromptContentModerationState.ACTIVE.value,
        nullable=False,
        index=True,
    )
    moderated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    moderated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    concept: Mapped[PromptConcept] = relationship(back_populates="versions")
    version_aliases: Mapped[list[PromptVersionAlias]] = relationship(
        back_populates="prompt_version", cascade="all, delete-orphan"
    )
    version_tags: Mapped[list[PromptVersionTag]] = relationship(
        back_populates="prompt_version", cascade="all, delete-orphan"
    )
    revision_items: Mapped[list[PromptListRevisionItem]] = relationship(
        back_populates="prompt_version"
    )


class PromptAlias(Base):
    """Concept-and-language-scoped accepted answer."""

    __tablename__ = "prompt_aliases"
    __table_args__ = (
        UniqueConstraint(
            "concept_id",
            "language",
            "match_key",
            name="uq_prompt_alias_concept_language_match_key",
        ),
        _values_check("language", PROMPT_LANGUAGES, "ck_prompt_aliases_language"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_concepts.id", ondelete="CASCADE"),
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    answer: Mapped[str] = mapped_column(String(64), nullable=False)
    match_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    concept: Mapped[PromptConcept] = relationship(back_populates="aliases")
    alias_versions: Mapped[list[PromptVersionAlias]] = relationship(
        back_populates="alias", cascade="all, delete-orphan"
    )


class PromptVersionAlias(Base):
    """Attach a concept alias to the exact immutable versions accepting it."""

    __tablename__ = "prompt_version_aliases"

    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    alias_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_aliases.id", ondelete="CASCADE"),
        primary_key=True,
    )

    prompt_version: Mapped[PromptVersion] = relationship(
        back_populates="version_aliases"
    )
    alias: Mapped[PromptAlias] = relationship(back_populates="alias_versions")


class PromptTag(Base):
    """Stable searchable category shared by explicit version membership."""

    __tablename__ = "prompt_tags"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    slug: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(
        String(255), default="", server_default="", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    version_tags: Mapped[list[PromptVersionTag]] = relationship(
        back_populates="tag", cascade="all, delete-orphan"
    )
    list_revision_tags: Mapped[list[PromptListRevisionTag]] = relationship(
        back_populates="tag", cascade="all, delete-orphan"
    )


class PromptVersionTag(Base):
    """Explicit tag membership for an immutable prompt version."""

    __tablename__ = "prompt_version_tags"

    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_tags.id", ondelete="CASCADE"),
        primary_key=True,
    )

    prompt_version: Mapped[PromptVersion] = relationship(
        back_populates="version_tags"
    )
    tag: Mapped[PromptTag] = relationship(back_populates="version_tags")


class PromptList(Base):
    """Curated or custom prompt collection."""

    __tablename__ = "prompt_lists"
    __table_args__ = (
        _values_check("language", PROMPT_LANGUAGES, "ck_prompt_lists_language"),
        _values_check(
            "visibility", PROMPT_LIST_VISIBILITIES, "ck_prompt_lists_visibility"
        ),
        _values_check(
            "moderation_state",
            PROMPT_CONTENT_MODERATION_STATES,
            "ck_prompt_lists_moderation_state",
        ),
        CheckConstraint(
            "is_bundled = false OR owner_user_id IS NULL",
            name="ck_prompt_lists_bundled_owner",
        ),
        CheckConstraint(
            "visibility != 'unlisted' OR share_code IS NOT NULL",
            name="ck_prompt_lists_unlisted_share_code",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(
        String(255), default="", server_default="", nullable=False
    )
    language: Mapped[str] = mapped_column(
        String(16),
        default=PromptLanguage.ENGLISH.value,
        server_default=PromptLanguage.ENGLISH.value,
        nullable=False,
    )
    is_bundled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    visibility: Mapped[str] = mapped_column(
        String(16),
        default=PromptListVisibility.PRIVATE.value,
        server_default=PromptListVisibility.PRIVATE.value,
        nullable=False,
        index=True,
    )
    share_code: Mapped[str | None] = mapped_column(
        String(24), nullable=True, unique=True, index=True
    )
    moderation_state: Mapped[str] = mapped_column(
        String(16),
        default=PromptContentModerationState.ACTIVE.value,
        server_default=PromptContentModerationState.ACTIVE.value,
        nullable=False,
        index=True,
    )
    moderated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    moderated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    prompts: Mapped[list[Prompt]] = relationship(
        back_populates="prompt_list",
        cascade="all, delete-orphan",
    )
    localizations: Mapped[list[PromptListLocalization]] = relationship(
        back_populates="prompt_list",
        cascade="all, delete-orphan",
    )
    revisions: Mapped[list[PromptListRevision]] = relationship(
        back_populates="prompt_list",
        cascade="all, delete-orphan",
    )


class PromptListRevision(Base):
    """Immutable, content-addressed membership for one list version."""

    __tablename__ = "prompt_list_revisions"
    __table_args__ = (
        UniqueConstraint(
            "prompt_list_id", "version", name="uq_prompt_list_revision_version"
        ),
        CheckConstraint(
            "version >= 1", name="ck_prompt_list_revisions_version_positive"
        ),
        _values_check(
            "language", PROMPT_LANGUAGES, "ck_prompt_list_revisions_language"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    prompt_list_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_lists.id", ondelete="CASCADE"),
        nullable=False,
    )
    forked_from_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_list_revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # How often each a-z letter appears across every answer this revision
    # holds, and how many alphabetic characters they come to in total. Wheel
    # pricing needs that distribution, not the words, so storing it here is
    # what lets a room price letters without keeping its prompt pool resident.
    # Written once when the revision is, and counted over its whole membership
    # rather than what moderation allowed at that moment: membership is
    # immutable and moderation is not, so counting the latter would drift the
    # first time a version was hidden or restored. Hidden content is therefore
    # priced without being drawable - an approximation R-HINT-03 records.
    letter_counts: Mapped[dict] = mapped_column(
        PortableJSON, default=dict, server_default=text("'{}'"), nullable=False
    )
    letter_total: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    prompt_list: Mapped[PromptList] = relationship(back_populates="revisions")
    items: Mapped[list[PromptListRevisionItem]] = relationship(
        back_populates="revision",
        cascade="all, delete-orphan",
        order_by="PromptListRevisionItem.position",
    )
    revision_tags: Mapped[list[PromptListRevisionTag]] = relationship(
        back_populates="revision", cascade="all, delete-orphan"
    )


class PromptListRevisionItem(Base):
    """Ordered membership in one immutable prompt-list revision."""

    __tablename__ = "prompt_list_revision_items"
    __table_args__ = (
        UniqueConstraint(
            "revision_id", "position", name="uq_prompt_list_revision_item_position"
        ),
        CheckConstraint(
            "position >= 0", name="ck_prompt_list_revision_items_position_nonnegative"
        ),
    )

    revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_list_revisions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    revision: Mapped[PromptListRevision] = relationship(back_populates="items")
    prompt_version: Mapped[PromptVersion] = relationship(
        back_populates="revision_items"
    )


class PromptListRevisionTag(Base):
    """Structured discovery metadata attached to one immutable list revision."""

    __tablename__ = "prompt_list_revision_tags"

    revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_list_revisions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_tags.id", ondelete="CASCADE"),
        primary_key=True,
    )

    revision: Mapped[PromptListRevision] = relationship(
        back_populates="revision_tags"
    )
    tag: Mapped[PromptTag] = relationship(back_populates="list_revision_tags")


class PromptListLocalization(Base):
    """Localized catalogue copy, separate from the list's content language."""

    __tablename__ = "prompt_list_localizations"
    __table_args__ = (
        UniqueConstraint(
            "prompt_list_id", "locale", name="uq_prompt_list_localization_locale"
        ),
        _values_check(
            "locale", PROMPT_LANGUAGES, "ck_prompt_list_localizations_locale"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    prompt_list_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_lists.id", ondelete="CASCADE"),
        nullable=False,
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(
        String(255), default="", server_default="", nullable=False
    )

    prompt_list: Mapped[PromptList] = relationship(back_populates="localizations")


class PromptUsageFact(Base):
    """Append-only, per-game usage totals for one prompt in one pinned revision."""

    __tablename__ = "prompt_usage_facts"
    __table_args__ = (
        CheckConstraint("offer_count >= 0", name="ck_prompt_usage_facts_offers"),
        CheckConstraint("pick_count >= 0", name="ck_prompt_usage_facts_picks"),
        CheckConstraint(
            "correct_guess_count >= 0",
            name="ck_prompt_usage_facts_correct_guesses",
        ),
        CheckConstraint(
            "total_guesser_count >= 0",
            name="ck_prompt_usage_facts_total_guessers",
        ),
        _values_check(
            "scoring_mode", SCORING_MODES, "ck_prompt_usage_facts_scoring_mode"
        ),
        _values_check(
            "hint_mode", HINT_MODES, "ck_prompt_usage_facts_hint_mode"
        ),
        Index(
            "ix_prompt_usage_facts_revision_occurred_at",
            "prompt_list_revision_id",
            "occurred_at",
        ),
        Index(
            "ix_prompt_usage_facts_version_occurred_at",
            "prompt_version_id",
            "occurred_at",
        ),
    )

    # The idempotency triple is the identity - it is what makes a retried
    # finished game a no-op - so it is the key, and the surrogate id and its
    # two extra indexes are gone.
    batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True
    )
    prompt_list_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_list_revisions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    scoring_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    hint_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    offer_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=sql_text("0"), nullable=False
    )
    pick_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=sql_text("0"), nullable=False
    )
    correct_guess_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=sql_text("0"), nullable=False
    )
    total_guesser_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=sql_text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )


class Prompt(Base):
    """Current display row for one prompt concept in a prompt list."""

    __tablename__ = "prompts"

    __table_args__ = (
        UniqueConstraint("prompt_list_id", "text", name="uq_prompt_list_text"),
        UniqueConstraint(
            "prompt_list_id", "concept_id", name="uq_prompt_list_concept"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    prompt_list_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_lists.id", ondelete="CASCADE"),
        nullable=False,
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_concepts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(String(64), nullable=False)
    # When the current prompt membership entered the list, not the immutable
    # concept/version creation time.
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    prompt_list: Mapped[PromptList] = relationship(back_populates="prompts")
