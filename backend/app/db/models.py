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
    DATA_EXPORT_STATUSES,
    HINT_MODES,
    PROMPT_LANGUAGES,
    SCORING_MODES,
    TURN_END_REASONS,
    USER_ROLES,
    AccountState,
    DataExportStatus,
    PromptLanguage,
    TurnEndReason,
    UserRole,
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
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
    )
    room_name: Mapped[str] = mapped_column(String(64), nullable=False)
    scoring_mode: Mapped[str] = mapped_column(String(16), nullable=False)
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

    participants: Mapped[list[GameParticipant]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
    )
    turns: Mapped[list[TurnRecord]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
    )


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

    game: Mapped[GameRecord] = relationship(back_populates="turns")
    drawer: Mapped[User | None] = relationship()
    guesses: Mapped[list[TurnGuess]] = relationship(
        back_populates="turn_record",
        cascade="all, delete-orphan",
    )


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

    turn_record: Mapped[TurnRecord] = relationship(back_populates="guesses")
    user: Mapped[User | None] = relationship()


class PromptList(Base):
    """Curated or custom prompt collection."""

    __tablename__ = "prompt_lists"
    __table_args__ = (
        _values_check("language", PROMPT_LANGUAGES, "ck_prompt_lists_language"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=generate_uuid
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
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )

    prompts: Mapped[list[Prompt]] = relationship(
        back_populates="prompt_list",
        cascade="all, delete-orphan",
    )


class Prompt(Base):
    """Individual prompt belonging to a prompt list with usage statistics."""

    __tablename__ = "prompts"

    __table_args__ = (
        UniqueConstraint("prompt_list_id", "text", name="uq_prompt_list_text"),
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
    text: Mapped[str] = mapped_column(String(64), nullable=False)
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

    prompt_list: Mapped[PromptList] = relationship(back_populates="prompts")
