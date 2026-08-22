"""SQLAlchemy ORM models for Sketchy database tables."""
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def generate_uuid() -> str:
    """Generate a standard UUID string for primary keys."""
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy entities."""
    pass


class AppConfig(Base):
    """Key-value storage for server configuration and auto-generated secrets."""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class User(Base):
    """Persistent player identity (both anonymous guests and registered users)."""

    __tablename__ = "users"

    # Expression-based, so `alembic revision --autogenerate` cannot see it on
    # SQLite - the dialect has no way to reflect such an index, and skips it
    # rather than emitting a spurious CREATE on every run. Any change to this
    # index therefore has to be written into a migration by hand: autogenerate
    # will report nothing and mean nothing by it.
    __table_args__ = (
        Index(
            "ix_users_username_lower",
            func.lower(text("username")),
            unique=True,
            postgresql_where=text("username IS NOT NULL"),
            sqlite_where=text("username IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(32), nullable=False)
    name_color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Reserved for password recovery; no reset flow ships yet, but the column
    # exists so recovery can be added without migrating live accounts.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # Distinct from updated_at, which moves on any write. Set on guest
    # provision and refreshed on login, register, and GET /api/auth/me.
    last_login_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class GameRecord(Base):
    """Finished multiplayer game summary."""

    __tablename__ = "game_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    room_name: Mapped[str] = mapped_column(String(64), nullable=False)
    scoring_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    hint_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    drawing_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    total_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    player_count: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Indexed because every read of a player's history sorts on it: the page
    # query filters to the games they took part in and takes the newest first,
    # which without this orders the whole matching set on each request.
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
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

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    game_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("game_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    final_score: Mapped[int] = mapped_column(Integer, nullable=False)
    final_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    # Turns this player was still in the rotation for. A one-round walkout and
    # a full game otherwise look identical, which skews win rate and averages.
    turns_played: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    game: Mapped[GameRecord] = relationship(back_populates="participants")
    user: Mapped[User] = relationship()


class TurnRecord(Base):
    """Individual round turn details within a finished game."""

    __tablename__ = "turn_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    game_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("game_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    drawer_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
        String(16), default="timeout", server_default="timeout", nullable=False
    )
    wrong_guess_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    near_miss_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    game: Mapped[GameRecord] = relationship(back_populates="turns")
    drawer: Mapped[User] = relationship()
    guesses: Mapped[list[TurnGuess]] = relationship(
        back_populates="turn_record",
        cascade="all, delete-orphan",
    )


class TurnGuess(Base):
    """Correct guess recorded for a player in a specific round."""

    __tablename__ = "turn_guesses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    turn_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("turn_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    user: Mapped[User] = relationship()


class PromptList(Base):
    """Curated or custom prompt collection."""

    __tablename__ = "prompt_lists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    prompt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_bundled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

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

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    prompt_list_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("prompt_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(String(64), nullable=False)
    offer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pick_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_guess_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_guesser_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    prompt_list: Mapped[PromptList] = relationship(back_populates="prompts")
