"""Unit tests for SQLAlchemy models and database schema."""
from __future__ import annotations

from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import (
    AppConfig,
    Base,
    GameParticipant,
    GameRecord,
    RoundGuess,
    RoundRecord,
    User,
    Word,
    WordList,
    generate_uuid,
)

pytestmark = pytest.mark.asyncio


async def create_test_db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return factory, engine


async def test_app_config_crud():
    factory, engine = await create_test_db()
    try:
        async with factory() as session:
            async with session.begin():
                config = AppConfig(key="jwt_secret", value="super-secret-key-1234")
                session.add(config)

        async with factory() as session:
            stmt = select(AppConfig).where(AppConfig.key == "jwt_secret")
            result = await session.execute(stmt)
            loaded = result.scalar_one()
            assert loaded.key == "jwt_secret"
            assert loaded.value == "super-secret-key-1234"
    finally:
        await engine.dispose()


async def test_user_creation_and_unique_username():
    factory, engine = await create_test_db()
    try:
        async with factory() as session:
            async with session.begin():
                user1 = User(
                    id=generate_uuid(),
                    username="alice",
                    password_hash="hash123",
                    display_name="Alice",
                    name_color="#ff0000",
                    is_anonymous=False,
                )
                session.add(user1)

        async with factory() as session:
            stmt = select(User).where(User.username == "alice")
            result = await session.execute(stmt)
            loaded = result.scalar_one()
            assert loaded.display_name == "Alice"
            assert loaded.is_anonymous is False

        # Attempt duplicate username with different casing in new session (DB level case-insensitive uniqueness)
        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    user2 = User(
                        id=generate_uuid(),
                        username="ALICE",
                        password_hash="hash456",
                        display_name="Alice2",
                    )
                    session.add(user2)
    finally:
        await engine.dispose()


async def test_get_database_url_normalization(monkeypatch):
    from app.db import get_database_url

    monkeypatch.setenv("DATABASE_URL", "sqlite:///./relative.db")
    assert get_database_url() == "sqlite+aiosqlite:///./relative.db"

    monkeypatch.setenv("DATABASE_URL", "sqlite:////absolute/path.db")
    assert get_database_url() == "sqlite+aiosqlite:////absolute/path.db"

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
    assert get_database_url() == "postgresql+asyncpg://user:pass@localhost:5432/db"

    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@localhost:5432/db")
    assert get_database_url() == "postgresql+asyncpg://user:pass@localhost:5432/db"


async def test_game_record_cascade_and_relationships():
    factory, engine = await create_test_db()
    try:
        now = datetime.now(timezone.utc)
        game_id = generate_uuid()
        u1_id = generate_uuid()
        u2_id = generate_uuid()

        async with factory() as session:
            async with session.begin():
                u1 = User(id=u1_id, display_name="Player 1")
                u2 = User(id=u2_id, display_name="Player 2")
                session.add_all([u1, u2])

                game = GameRecord(
                    id=game_id,
                    room_name="Party Room",
                    scoring_mode="default",
                    hint_mode="checkpoints",
                    drawing_seconds=90,
                    total_rounds=3,
                    player_count=2,
                    started_at=now,
                    finished_at=now,
                )
                session.add(game)

                p1 = GameParticipant(
                    id=generate_uuid(),
                    game_id=game_id,
                    user_id=u1_id,
                    final_score=500,
                    final_rank=1,
                )
                p2 = GameParticipant(
                    id=generate_uuid(),
                    game_id=game_id,
                    user_id=u2_id,
                    final_score=300,
                    final_rank=2,
                )
                session.add_all([p1, p2])

                r1 = RoundRecord(
                    id=generate_uuid(),
                    game_id=game_id,
                    round_number=1,
                    turn_number=1,
                    drawer_user_id=u1_id,
                    word="banana",
                    duration_seconds=45.5,
                )
                session.add(r1)

                g1 = RoundGuess(
                    id=generate_uuid(),
                    round_id=r1.id,
                    user_id=u2_id,
                    points_awarded=250,
                    guess_time_seconds=12.3,
                )
                session.add(g1)

        async with factory() as session:
            stmt = select(GameRecord).where(GameRecord.id == game_id)
            res = await session.execute(stmt)
            loaded_game = res.scalar_one()
            assert loaded_game.room_name == "Party Room"
    finally:
        await engine.dispose()


async def test_word_list_and_word_uniqueness():
    factory, engine = await create_test_db()
    try:
        wl_id = generate_uuid()
        async with factory() as session:
            async with session.begin():
                wl = WordList(
                    id=wl_id,
                    slug="animals",
                    name="Animals",
                    description="Animal words",
                    language="en",
                    word_count=2,
                    version=1,
                )
                session.add(wl)

                w1 = Word(id=generate_uuid(), word_list_id=wl_id, text="dog")
                w2 = Word(id=generate_uuid(), word_list_id=wl_id, text="cat")
                session.add_all([w1, w2])

        async with factory() as session:
            stmt = select(Word).where(Word.word_list_id == wl_id)
            words = (await session.execute(stmt)).scalars().all()
            assert len(words) == 2

        # Attempt duplicate word text in same list
        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    dup = Word(id=generate_uuid(), word_list_id=wl_id, text="dog")
                    session.add(dup)
    finally:
        await engine.dispose()


async def test_init_db_runs_alembic_migrations(tmp_path):
    from app.db import init_db
    db_file = tmp_path / "test_migration.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    try:
        await init_db(engine)
        # Verify tables exist by querying app_config
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            async with session.begin():
                session.add(AppConfig(key="migrated", value="yes"))
            res = await session.execute(select(AppConfig).where(AppConfig.key == "migrated"))
            assert res.scalar_one().value == "yes"
    finally:
        await engine.dispose()

