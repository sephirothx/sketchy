"""Unit tests for SQLAlchemy models and database schema."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid
import warnings

import pytest
from sqlalchemy import Uuid, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError, SAWarning, StatementError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import (
    AppConfig,
    Base,
    DataExport,
    GameParticipant,
    GameRecord,
    TurnGuess,
    TurnRecord,
    User,
    UserSettings,
    Prompt,
    PromptList,
    generate_uuid,
)
from app.domain_values import (
    ACCOUNT_STATES,
    DATA_EXPORT_STATUSES,
    HINT_MODES,
    PROMPT_LANGUAGES,
    SCORING_MODES,
    TURN_END_REASONS,
    USER_ROLES,
    USER_THEMES,
    BRUSH_CURSOR_STYLES,
    AccountState,
    UserRole,
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
                config = AppConfig(key="feature_mode", value="safe")
                session.add(config)

        async with factory() as session:
            stmt = select(AppConfig).where(AppConfig.key == "feature_mode")
            result = await session.execute(stmt)
            loaded = result.scalar_one()
            assert loaded.key == "feature_mode"
            assert loaded.value == "safe"
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
            assert loaded.state == AccountState.REGISTERED.value
            assert loaded.role == UserRole.USER.value

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


@pytest.mark.parametrize("column,invalid", [("state", "lost"), ("role", "owner")])
async def test_user_state_and_role_are_database_constrained(column, invalid):
    factory, engine = await create_test_db()
    try:
        values = {
            "id": generate_uuid(),
            "display_name": "Guest",
            "state": AccountState.ANONYMOUS.value,
            "role": UserRole.USER.value,
        }
        values[column] = invalid
        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    session.add(User(**values))
    finally:
        await engine.dispose()


async def test_account_state_and_role_constants_cover_database_values():
    assert ACCOUNT_STATES == ("anonymous", "registered", "merged", "deleted")
    assert USER_ROLES == ("user", "moderator", "admin")
    assert DATA_EXPORT_STATUSES == ("pending", "processing", "ready", "failed")
    assert USER_THEMES == ("light", "dark", "system")
    assert BRUSH_CURSOR_STYLES == ("crosshair", "circle")


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


async def test_boolean_server_default_is_valid_postgresql():
    """Boolean defaults must compile as Boolean literals, not integers."""
    default = TurnRecord.__table__.c.prompt_auto_picked.server_default

    assert default is not None
    rendered = str(default.arg.compile(dialect=postgresql.dialect()))
    assert rendered == "false"


async def test_entity_ids_are_time_ordered_uuidv7_with_native_postgresql_type():
    generated = [generate_uuid() for _ in range(20)]

    assert all(isinstance(value, uuid.UUID) for value in generated)
    assert all(value.version == 7 for value in generated)
    assert generated == sorted(generated)

    entity_id_columns = (
        User.id,
        DataExport.id,
        DataExport.user_id,
        UserSettings.user_id,
        GameRecord.id,
        GameParticipant.id,
        GameParticipant.game_id,
        GameParticipant.user_id,
        TurnRecord.id,
        TurnRecord.game_id,
        TurnRecord.drawer_user_id,
        TurnGuess.id,
        TurnGuess.turn_id,
        TurnGuess.user_id,
        PromptList.id,
        Prompt.id,
        Prompt.prompt_list_id,
    )
    for attribute in entity_id_columns:
        column_type = attribute.property.columns[0].type
        assert isinstance(column_type, Uuid)
        assert column_type.as_uuid is True
        assert column_type.native_uuid is True

    id_type = User.__table__.c.id.type
    assert id_type.compile(dialect=postgresql.dialect()) == "UUID"
    assert id_type.compile(dialect=sqlite.dialect()) == "CHAR(32)"


async def test_timestamp_type_normalizes_sqlite_results_to_aware_utc():
    factory, engine = await create_test_db()
    source_timezone = timezone(timedelta(hours=5, minutes=30))
    source_started_at = datetime(2026, 8, 22, 12, 0, tzinfo=source_timezone)
    game_id = generate_uuid()

    try:
        async with factory() as session:
            async with session.begin():
                session.add(
                    GameRecord(
                        id=game_id,
                        room_name="UTC room",
                        scoring_mode="default",
                        hint_mode="checkpoints",
                        drawing_seconds=90,
                        total_rounds=1,
                        player_count=1,
                        started_at=source_started_at,
                        finished_at=source_started_at + timedelta(minutes=5),
                    )
                )

        async with factory() as session:
            loaded = await session.get(GameRecord, game_id)
            assert loaded is not None
            assert loaded.started_at == source_started_at.astimezone(timezone.utc)
            assert loaded.started_at.tzinfo is timezone.utc
            assert loaded.finished_at.tzinfo is timezone.utc

        with pytest.raises(StatementError, match="requires an aware datetime"):
            async with factory() as session:
                async with session.begin():
                    session.add(
                        GameRecord(
                            id=generate_uuid(),
                            room_name="Naive time",
                            scoring_mode="default",
                            hint_mode="checkpoints",
                            drawing_seconds=90,
                            total_rounds=1,
                            player_count=1,
                            started_at=datetime(2026, 8, 22, 12, 0),
                            finished_at=datetime(2026, 8, 22, 12, 5),
                        )
                    )
    finally:
        await engine.dispose()


async def test_postgresql_pool_configuration_is_bounded_and_overridable(monkeypatch):
    from app.db import get_engine_pool_options

    for name in (
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT_SECONDS",
        "DB_POOL_RECYCLE_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    assert get_engine_pool_options("postgresql+asyncpg://db/sketchy") == {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 5,
        "pool_timeout": 10,
        "pool_recycle": 1_800,
    }
    assert get_engine_pool_options("sqlite+aiosqlite:///sketchy.db") == {}

    monkeypatch.setenv("DB_POOL_SIZE", "8")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "3")
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("DB_POOL_RECYCLE_SECONDS", "900")
    configured = get_engine_pool_options("postgresql+asyncpg://db/sketchy")
    assert configured == {
        "pool_pre_ping": True,
        "pool_size": 8,
        "max_overflow": 3,
        "pool_timeout": 7,
        "pool_recycle": 900,
    }


async def test_sqlite_engine_enforces_foreign_keys_and_uses_wal(tmp_path):
    """Raw SQL must enforce cascades and history-preserving SET NULL rules."""
    from app.db import SQLITE_BUSY_TIMEOUT_MS, create_db_engine

    db_file = tmp_path / "configured.db"
    engine = create_db_engine(f"sqlite+aiosqlite:///{db_file}")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    user_id = generate_uuid()
    game_id = generate_uuid()
    turn_id = generate_uuid()

    try:
        async with engine.begin() as conn:
            foreign_keys = (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one()
            journal_mode = (await conn.execute(text("PRAGMA journal_mode"))).scalar_one()
            busy_timeout = (await conn.execute(text("PRAGMA busy_timeout"))).scalar_one()
            await conn.run_sync(Base.metadata.create_all)

        assert foreign_keys == 1
        assert journal_mode == "wal"
        assert busy_timeout == SQLITE_BUSY_TIMEOUT_MS

        async with factory() as session:
            async with session.begin():
                session.add(User(id=user_id, display_name="Cascade test"))
                session.add(
                    GameRecord(
                        id=game_id,
                        room_name="Cascade room",
                        scoring_mode="default",
                        hint_mode="checkpoints",
                        drawing_seconds=90,
                        total_rounds=1,
                        player_count=1,
                        started_at=datetime.now(timezone.utc),
                        finished_at=datetime.now(timezone.utc),
                    )
                )
                session.add(
                    GameParticipant(
                        id=generate_uuid(),
                        game_id=game_id,
                        user_id=user_id,
                        display_name_snapshot="Cascade test",
                        final_score=0,
                        final_rank=1,
                    )
                )
                session.add(
                    TurnRecord(
                        id=turn_id,
                        game_id=game_id,
                        round_number=1,
                        turn_number=1,
                        drawer_user_id=user_id,
                        drawer_display_name_snapshot="Cascade test",
                        prompt="anchor",
                        duration_seconds=10,
                    )
                )
                session.add(
                    TurnGuess(
                        id=generate_uuid(),
                        turn_id=turn_id,
                        user_id=user_id,
                        display_name_snapshot="Cascade test",
                        points_awarded=10,
                        guess_time_seconds=5,
                    )
                )

        # Bypass ORM cascades: this succeeds only if SQLite itself applies the
        # on-delete rule declared by the schema.
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id.hex},
            )
            participant = (
                await conn.execute(
                    text(
                        "SELECT user_id, display_name_snapshot FROM game_participants"
                    )
                )
            ).one()
            turn = (
                await conn.execute(
                    text(
                        "SELECT drawer_user_id, drawer_display_name_snapshot FROM turn_records"
                    )
                )
            ).one()
            guess = (
                await conn.execute(
                    text("SELECT user_id, display_name_snapshot FROM turn_guesses")
                )
            ).one()
        assert participant == (None, "Cascade test")
        assert turn == (None, "Cascade test")
        assert guess == (None, "Cascade test")
    finally:
        await engine.dispose()


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

                r1 = TurnRecord(
                    id=generate_uuid(),
                    game_id=game_id,
                    round_number=1,
                    turn_number=1,
                    drawer_user_id=u1_id,
                    prompt="banana",
                    duration_seconds=45.5,
                )
                session.add(r1)

                g1 = TurnGuess(
                    id=generate_uuid(),
                    turn_id=r1.id,
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


async def test_game_history_natural_keys_reject_duplicate_rows():
    factory, engine = await create_test_db()
    game_id = generate_uuid()
    drawer_id = generate_uuid()
    guesser_id = generate_uuid()
    turn_id = generate_uuid()
    now = datetime.now(timezone.utc)

    try:
        async with factory() as session:
            async with session.begin():
                session.add_all(
                    [
                        User(id=drawer_id, display_name="Drawer"),
                        User(id=guesser_id, display_name="Guesser"),
                        GameRecord(
                            id=game_id,
                            room_name="Invariant room",
                            scoring_mode="default",
                            hint_mode="checkpoints",
                            drawing_seconds=90,
                            total_rounds=1,
                            player_count=2,
                            started_at=now,
                            finished_at=now,
                        ),
                        GameParticipant(
                            id=generate_uuid(),
                            game_id=game_id,
                            user_id=drawer_id,
                            final_score=300,
                            final_rank=1,
                        ),
                        TurnRecord(
                            id=turn_id,
                            game_id=game_id,
                            round_number=1,
                            turn_number=1,
                            drawer_user_id=drawer_id,
                            prompt="anchor",
                            duration_seconds=30,
                        ),
                        TurnGuess(
                            id=generate_uuid(),
                            turn_id=turn_id,
                            user_id=guesser_id,
                            points_awarded=200,
                            guess_time_seconds=10,
                        ),
                    ]
                )

        duplicates = (
            GameParticipant(
                id=generate_uuid(),
                game_id=game_id,
                user_id=drawer_id,
                final_score=999,
                final_rank=1,
            ),
            TurnRecord(
                id=generate_uuid(),
                game_id=game_id,
                round_number=1,
                turn_number=1,
                drawer_user_id=drawer_id,
                prompt="duplicate",
                duration_seconds=20,
            ),
            TurnGuess(
                id=generate_uuid(),
                turn_id=turn_id,
                user_id=guesser_id,
                points_awarded=999,
                guess_time_seconds=1,
            ),
        )
        for duplicate in duplicates:
            with pytest.raises(IntegrityError):
                async with factory() as session:
                    async with session.begin():
                        session.add(duplicate)
    finally:
        await engine.dispose()


async def test_database_rejects_unknown_modes_statuses_and_languages():
    factory, engine = await create_test_db()
    now = datetime.now(timezone.utc)
    valid_game_id = generate_uuid()
    drawer_id = generate_uuid()

    try:
        invalid_rows = (
            GameRecord(
                id=generate_uuid(),
                room_name="Bad scoring",
                scoring_mode="typo",
                hint_mode="none",
                drawing_seconds=90,
                total_rounds=1,
                player_count=1,
                started_at=now,
                finished_at=now,
            ),
            GameRecord(
                id=generate_uuid(),
                room_name="Bad hints",
                scoring_mode="default",
                hint_mode="mystery",
                drawing_seconds=90,
                total_rounds=1,
                player_count=1,
                started_at=now,
                finished_at=now,
            ),
            PromptList(
                id=generate_uuid(),
                slug="unsupported-language",
                name="Unsupported language",
                language="xx",
            ),
        )
        for invalid_row in invalid_rows:
            with pytest.raises(IntegrityError):
                async with factory() as session:
                    async with session.begin():
                        session.add(invalid_row)

        async with factory() as session:
            async with session.begin():
                session.add(User(id=drawer_id, display_name="Drawer"))
                session.add(
                    GameRecord(
                        id=valid_game_id,
                        room_name="Valid game",
                        scoring_mode="default",
                        hint_mode="none",
                        drawing_seconds=90,
                        total_rounds=1,
                        player_count=1,
                        started_at=now,
                        finished_at=now,
                    )
                )

        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    session.add(
                        TurnRecord(
                            id=generate_uuid(),
                            game_id=valid_game_id,
                            round_number=1,
                            turn_number=1,
                            drawer_user_id=drawer_id,
                            prompt="anchor",
                            duration_seconds=30,
                            end_reason="drawer_vanished",
                        )
                    )

        expected_values = {
            "ck_game_records_scoring_mode": SCORING_MODES,
            "ck_game_records_hint_mode": HINT_MODES,
            "ck_turn_records_end_reason": TURN_END_REASONS,
            "ck_prompt_lists_language": PROMPT_LANGUAGES,
        }
        constraints = {
            constraint.name: str(constraint.sqltext)
            for table in (GameRecord, TurnRecord, PromptList)
            for constraint in table.__table__.constraints
            if constraint.name in expected_values
        }
        for name, values in expected_values.items():
            assert name in constraints
            assert all(repr(value) in constraints[name] for value in values)
    finally:
        await engine.dispose()


async def test_word_list_and_word_uniqueness():
    factory, engine = await create_test_db()
    try:
        wl_id = generate_uuid()
        async with factory() as session:
            async with session.begin():
                wl = PromptList(
                    id=wl_id,
                    slug="animals",
                    name="Animals",
                    description="Animal words",
                    language="en",
                    version=1,
                )
                session.add(wl)

                w1 = Prompt(id=generate_uuid(), prompt_list_id=wl_id, text="dog")
                w2 = Prompt(id=generate_uuid(), prompt_list_id=wl_id, text="cat")
                session.add_all([w1, w2])

        async with factory() as session:
            stmt = select(Prompt).where(Prompt.prompt_list_id == wl_id)
            words = (await session.execute(stmt)).scalars().all()
            assert len(words) == 2

        # Attempt duplicate prompt text in same list
        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    dup = Prompt(id=generate_uuid(), prompt_list_id=wl_id, text="dog")
                    session.add(dup)
    finally:
        await engine.dispose()


async def test_prompt_server_defaults_apply_to_raw_inserts():
    factory, engine = await create_test_db()
    prompt_list_id = generate_uuid()
    prompt_id = generate_uuid()

    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO prompt_lists (id, slug, name) "
                    "VALUES (:id, :slug, :name)"
                ),
                {
                    "id": prompt_list_id.hex,
                    "slug": "raw-list",
                    "name": "Raw list",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO prompts (id, prompt_list_id, text) "
                    "VALUES (:id, :prompt_list_id, :text)"
                ),
                {
                    "id": prompt_id.hex,
                    "prompt_list_id": prompt_list_id.hex,
                    "text": "anchor",
                },
            )

        async with factory() as session:
            prompt_list = await session.get(PromptList, prompt_list_id)
            prompt = await session.get(Prompt, prompt_id)

        assert prompt_list is not None
        assert prompt_list.description == ""
        assert prompt_list.language == "en"
        assert prompt_list.is_bundled is True
        assert prompt_list.version == 1
        assert prompt is not None
        assert prompt.offer_count == 0
        assert prompt.pick_count == 0
        assert prompt.correct_guess_count == 0
        assert prompt.total_guesser_count == 0
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


async def test_non_sqlite_startup_verifies_without_migrating(monkeypatch):
    from app import db

    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    verify = AsyncMock()
    upgrade = AsyncMock()
    monkeypatch.setattr(db, "verify_database_head", verify)
    monkeypatch.setattr(db, "upgrade_database", upgrade)

    await db.init_db(engine)

    verify.assert_awaited_once_with(engine)
    upgrade.assert_not_awaited()


async def test_database_head_verification_reports_stale_schema(tmp_path):
    from app.db import DatabaseRevisionError, upgrade_database, verify_database_head

    db_file = tmp_path / "revision-check.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    try:
        await upgrade_database(engine)
        await verify_database_head(engine)

        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM alembic_version"))

        with pytest.raises(DatabaseRevisionError, match="python -m app.db.migrate"):
            await verify_database_head(engine)
    finally:
        await engine.dispose()


async def test_migrations_match_the_models(tmp_path):
    """A fresh upgrade must leave nothing for autogenerate to add.

    The historical migrations were squashed into a foundation before data
    existed. Later revisions now form a replayable chain; this focused check
    still proves a fresh SQLite upgrade describes the models. Drift here means
    a model changed without a migration, and the next deployment gets a schema
    the code does not expect.

    Note what this cannot see: the username and email expression indexes are
    invisible to autogenerate on SQLite, so dropping either from a migration
    would not fail this test. See `User.__table_args__`.
    """
    from alembic import command as alembic_command
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db import get_alembic_config
    from app.db.models import Base

    db_file = tmp_path / "fresh.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    engine = create_async_engine(url)
    config = get_alembic_config()
    config.set_main_option("sqlalchemy.url", url)

    def upgrade(connection):
        config.attributes["connection"] = connection
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r".*ix_users_(?:username|email)_lower.*",
                category=SAWarning,
            )
            alembic_command.upgrade(config, "head")

    def diff(connection):
        context = MigrationContext.configure(connection)
        return compare_metadata(context, Base.metadata)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(upgrade)
        # Both SQLAlchemy and Alembic say out loud that they are skipping the
        # expression index, once each, every run. That is the blind spot the
        # docstring above names rather than news, so it is filtered by name -
        # any other reflection warning still gets through.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r".*ix_users_(?:username|email)_lower.*",
                category=SAWarning,
            )
            warnings.filterwarnings(
                "ignore",
                message=r".*ix_users_(?:username|email)_lower.*",
                category=UserWarning,
            )
            async with engine.connect() as connection:
                differences = await connection.run_sync(diff)
    finally:
        await engine.dispose()

    assert differences == [], f"models and migrations have drifted: {differences}"
