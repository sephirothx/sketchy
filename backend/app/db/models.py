"""SQLAlchemy ORM models for Sketchy database tables."""
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from uuid6 import uuid7

from app.auth.avatars import BUILT_IN_AVATAR_KEYS
from app.db.types import UTCDateTime
from app.domain_values import (
    ACCOUNT_STATES,
    BRUSH_CURSOR_STYLES,
    DATA_EXPORT_STATUSES,
    DEFAULT_USER_KEY_BINDINGS,
    GAME_PROMPT_SOURCE_MODES,
    HINT_MODES,
    PROMPT_CONTENT_MODERATION_STATES,
    PROMPT_CONTENT_REPORT_REASONS,
    PROMPT_CONTENT_RATINGS,
    PROMPT_EDITORIAL_DIFFICULTIES,
    PROMPT_LANGUAGES,
    PROMPT_LIST_VISIBILITIES,
    PROMPT_SOURCE_KINDS,
    REPORT_REASONS,
    REPORT_STATUSES,
    SCORING_MODES,
    TURN_END_REASONS,
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


def _values_check(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    allowed = ", ".join(repr(value) for value in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


def generate_uuid() -> uuid.UUID:
    """Generate a time-ordered UUIDv7 for a persisted entity."""
    return uuid7()


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy entities."""
    pass


class AppConfig(Base):
    """Key-value storage for server configuration and auto-generated secrets."""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable only for rows created before timestamp coverage existed. New
    # database writes receive both values from the server clock.
    created_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=True
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
        JSON,
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
        JSON, default=list, server_default=text("'[]'"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuditEvent(Base):
    """Append-only record of security- and moderation-sensitive actions."""

    __tablename__ = "audit_events"

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
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
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
        JSON, default=dict, server_default=text("'{}'"), nullable=False
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
        index=True,
    )
    banned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
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


class UserBlock(Base):
    """Directional player block used to mute ordinary social interaction."""

    __tablename__ = "user_blocks"
    __table_args__ = (
        UniqueConstraint("blocker_user_id", "blocked_user_id", name="uq_user_block"),
        CheckConstraint(
            "blocker_user_id != blocked_user_id", name="chk_no_self_block"
        ),
        Index("ix_user_blocks_blocked_user_id", "blocked_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    blocker_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    blocked_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )


class IdentityAlias(Base):
    """Immutable mapping from a merged guest identity to its account."""

    __tablename__ = "identity_aliases"
    __table_args__ = (
        CheckConstraint(
            "source_user_id != target_user_id", name="ck_identity_alias_distinct"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    source_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
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
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class DataExport(Base):
    """Durable asynchronous snapshot of the data belonging to one account."""

    __tablename__ = "data_exports"
    __table_args__ = (
        _values_check("status", DATA_EXPORT_STATUSES, "ck_data_exports_status"),
        Index("ix_data_exports_user_created_at", "user_id", "created_at"),
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
    status: Mapped[str] = mapped_column(
        String(16),
        default=DataExportStatus.PENDING.value,
        server_default=DataExportStatus.PENDING.value,
        nullable=False,
    )
    schema_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    artifact: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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
            "rule_snapshot_version >= 0",
            name="ck_game_records_rule_snapshot_version",
        ),
        _values_check(
            "prompt_source_mode",
            GAME_PROMPT_SOURCE_MODES,
            "ck_game_records_prompt_source_mode",
        ),
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
    rule_snapshot_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    rule_snapshot: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'"), nullable=False
    )
    prompt_source_mode: Mapped[str] = mapped_column(
        String(24),
        default="builtin_fallback",
        server_default="builtin_fallback",
        nullable=False,
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
    # Deliberately distinct from game event time. This supports save-lag and
    # retry diagnosis; legacy rows remain null rather than receiving a false
    # migration timestamp.
    persisted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=True
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
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    game_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("game_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    final_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    # Turns this player was still in the rotation for. A one-round walkout and
    # a full game otherwise look identical, which skews win rate and averages.
    turns_played: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=True
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
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    game_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("game_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    drawer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    # How many players could still have guessed. Correct-guess counts are
    # uninterpretable without it: two of two is not two of eight.
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
    created_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=True
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


class TurnPromptOffer(Base):
    """An immutable prompt option and source snapshot offered for one turn."""

    __tablename__ = "turn_prompt_offers"
    __table_args__ = (
        UniqueConstraint(
            "turn_id", "position", name="uq_turn_prompt_offers_turn_position"
        ),
        CheckConstraint("position >= 0", name="ck_turn_prompt_offers_position"),
        _values_check(
            "source_kind", PROMPT_SOURCE_KINDS, "ck_turn_prompt_offers_source_kind"
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
        index=True,
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
    """Correct guess recorded for a player in a specific round."""

    __tablename__ = "turn_guesses"
    __table_args__ = (
        Index("uq_turn_guesses_turn_user", "turn_id", "user_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("turn_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    points_awarded: Mapped[int] = mapped_column(Integer, nullable=False)
    guess_time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    # `points_awarded` is already net of the hints bought that turn, so without
    # these a cheap win and an expensive one are the same number. Only settled
    # spend is recorded: hints are free to a player who never guesses, and they
    # leave no row here at all.
    hints_used: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    points_spent_on_hints: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    wrong_guesses_before: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=True
    )

    turn_record: Mapped[TurnRecord] = relationship(back_populates="guesses")
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
        index=True,
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
        index=True,
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
        index=True,
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
        index=True,
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
        UniqueConstraint(
            "batch_id",
            "prompt_list_revision_id",
            "prompt_version_id",
            name="uq_prompt_usage_fact_batch_revision_version",
        ),
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

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=False, index=True
    )
    prompt_list_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_list_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Legacy counter imports have no truthful occurrence time or rules. New
    # writes always populate all three nullable dimensions.
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    scoring_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    hint_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
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
        index=True,
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_concepts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    text: Mapped[str] = mapped_column(String(64), nullable=False)
    # This is when the current prompt membership entered the list, not the
    # immutable concept/version creation time. Legacy memberships are unknown.
    created_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=True
    )
    prompt_list: Mapped[PromptList] = relationship(back_populates="prompts")
