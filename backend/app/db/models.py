"""SQLAlchemy ORM models for Sketchy database tables."""
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
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

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    username: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(32), nullable=False)
    name_color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    participants: Mapped[list[GameParticipant]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
    )
    rounds: Mapped[list[RoundRecord]] = relationship(
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

    game: Mapped[GameRecord] = relationship(back_populates="participants")
    user: Mapped[User] = relationship()


class RoundRecord(Base):
    """Individual round turn details within a finished game."""

    __tablename__ = "round_records"

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
    word: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)

    game: Mapped[GameRecord] = relationship(back_populates="rounds")
    drawer: Mapped[User] = relationship()
    guesses: Mapped[list[RoundGuess]] = relationship(
        back_populates="round_record",
        cascade="all, delete-orphan",
    )


class RoundGuess(Base):
    """Correct guess recorded for a player in a specific round."""

    __tablename__ = "round_guesses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    round_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("round_records.id", ondelete="CASCADE"),
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

    round_record: Mapped[RoundRecord] = relationship(back_populates="guesses")
    user: Mapped[User] = relationship()


class WordList(Base):
    """Curated or custom word collection."""

    __tablename__ = "word_lists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_bundled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    words: Mapped[list[Word]] = relationship(
        back_populates="word_list",
        cascade="all, delete-orphan",
    )


class Word(Base):
    """Individual word belonging to a word list with usage statistics."""

    __tablename__ = "words"

    __table_args__ = (
        UniqueConstraint("word_list_id", "text", name="uq_word_list_text"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    word_list_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("word_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(String(64), nullable=False)
    offer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pick_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_guess_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_guesser_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    word_list: Mapped[WordList] = relationship(back_populates="words")
