"""Unit tests for SQLAlchemy models and database schema."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid
import warnings

import pytest
from sqlalchemy import UniqueConstraint, Uuid, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError, SAWarning, StatementError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import (
    IdentityAlias,
    AppConfig,
    Base,
    DataExport,
    Friendship,
    GameParticipant,
    GameRecord,
    PlayerReport,
    RoomMessage,
    TurnGuess,
    TurnParticipantOutcome,
    TurnRecord,
    User,
    UserStatsDaily,
    UserSettings,
    UserBan,
    UserBlock,
    RuntimeEvent,
    Prompt,
    PromptConcept,
    PromptList,
    PromptVersion,
    ScoreEvent,
    generate_uuid,
)
from app.domain_values import (
    ACCOUNT_STATES,
    AccountState,
    BRUSH_CURSOR_STYLES,
    DATA_EXPORT_STATUSES,
    FRIENDSHIP_STATES,
    FriendshipState,
    HINT_MODES,
    NEAR_MISS_KINDS,
    PROMPT_LANGUAGES,
    REPORT_REASONS,
    REPORT_STATUSES,
    RETAINED_MESSAGE_AUDIENCES,
    RETAINED_MESSAGE_KINDS,
    SCORE_EVENT_TYPES,
    SCORING_MODES,
    TURN_END_REASONS,
    USER_ROLES,
    USER_THEMES,
    UserRole,
)

from tests.dbfixtures import (
    SQLITE_MEMORY_URL,
    ForeignKeysOffError,
    _assert_foreign_keys_enforced,
    create_test_db,
    create_test_engine,
)

pytestmark = pytest.mark.asyncio




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
            assert loaded.created_at is not None
            assert loaded.created_at.tzinfo is not None
            assert loaded.updated_at is not None
            assert loaded.updated_at.tzinfo is not None
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
    assert FRIENDSHIP_STATES == ("pending", "accepted", "declined")
    assert DATA_EXPORT_STATUSES == ("pending", "processing", "ready", "failed")
    assert USER_THEMES == ("light", "dark", "system")
    assert BRUSH_CURSOR_STYLES == ("crosshair", "circle")
    assert REPORT_REASONS == (
        "harassment",
        "offensive_drawing",
        "inappropriate_name",
        "cheating",
        "spam",
        "inappropriate_avatar",
    )
    assert REPORT_STATUSES == ("pending", "resolved", "dismissed")
    assert RETAINED_MESSAGE_KINDS == ("chat", "wrong_guess", "correct_guess")
    assert RETAINED_MESSAGE_AUDIENCES == ("room", "prompt_aware", "lobby")
    assert NEAR_MISS_KINDS == ("close", "partial")


async def test_retained_messages_enforce_kind_context_and_expiry():
    factory, engine = await create_test_db()
    sender_id = generate_uuid()
    now = datetime.now(timezone.utc)
    common = {
        "room_instance_id": generate_uuid(),
        "sender_user_id": sender_id,
        "sender_player_id": generate_uuid(),
        "sender_display_name_snapshot": "Sender",
        "sender_is_anonymous_snapshot": False,
        "is_spectator": False,
        "audience": "room",
        "audience_user_ids": [str(sender_id)],
        "created_at": now,
        "expires_at": now + timedelta(days=30),
    }
    try:
        async with factory() as session:
            async with session.begin():
                session.add(User(id=sender_id, display_name="Sender"))
                await session.flush()
                session.add(
                    RoomMessage(
                        id=generate_uuid(),
                        message_kind="chat",
                        text="valid room chat",
                        **common,
                    )
                )

        invalid_rows = (
            RoomMessage(
                id=generate_uuid(),
                message_kind="unknown",
                text="invalid kind",
                **common,
            ),
            RoomMessage(
                id=generate_uuid(),
                message_kind="wrong_guess",
                text="missing game and turn",
                **common,
            ),
            RoomMessage(
                id=generate_uuid(),
                message_kind="chat",
                near_miss_kind="close",
                text="chat cannot be a near miss",
                **common,
            ),
            RoomMessage(
                id=generate_uuid(),
                message_kind="chat",
                audience="private",
                text="invalid audience",
                **{key: value for key, value in common.items() if key != "audience"},
            ),
            RoomMessage(
                id=generate_uuid(),
                message_kind="chat",
                text="invalid expiry",
                **{
                    key: (now if key == "expires_at" else value)
                    for key, value in common.items()
                },
            ),
        )
        for invalid_row in invalid_rows:
            with pytest.raises(IntegrityError):
                async with factory() as session:
                    async with session.begin():
                        session.add(invalid_row)
    finally:
        await engine.dispose()


async def test_daily_user_stats_projection_rejects_impossible_counts():
    factory, engine = await create_test_db()
    user_id = generate_uuid()
    try:
        async with factory() as session:
            async with session.begin():
                session.add(User(id=user_id, display_name="Projected"))
                session.add(
                    UserStatsDaily(
                        user_id=user_id,
                        stat_date=date(2026, 8, 23),
                        games_played=2,
                        games_won=1,
                        total_score=150,
                        turns_played=4,
                        prompts_guessed=2,
                        drawings_made=2,
                    )
                )

        invalid_rows = (
            UserStatsDaily(
                user_id=user_id,
                stat_date=date(2026, 8, 24),
                games_played=1,
                games_won=2,
            ),
            UserStatsDaily(
                user_id=user_id,
                stat_date=date(2026, 8, 25),
                games_played=-1,
            ),
        )
        for invalid_row in invalid_rows:
            with pytest.raises(IntegrityError):
                async with factory() as session:
                    async with session.begin():
                        session.add(invalid_row)
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
        PlayerReport.id,
        PlayerReport.reporter_user_id,
        PlayerReport.reported_user_id,
        PlayerReport.game_id,
        PlayerReport.turn_id,
        PlayerReport.reviewed_by_user_id,
        UserBan.id,
        UserBan.user_id,
        UserBan.banned_by_user_id,
        UserBan.revoked_by_user_id,
        UserBlock.blocker_user_id,
        UserBlock.blocked_user_id,
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
                seat_id = generate_uuid()
                session.add(
                    GameParticipant(
                        id=seat_id,
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
                        drawer_participant_id=seat_id,
                        drawer_display_name_snapshot="Cascade test",
                        prompt="anchor",
                        duration_seconds=10,
                    )
                )
                outcome_id = generate_uuid()
                session.add(
                    TurnParticipantOutcome(
                        id=outcome_id,
                        game_id=game_id,
                        turn_id=turn_id,
                        participant_id=seat_id,
                        eligible=True,
                        eligibility_reason="eligible",
                        outcome="correct",
                        terminal_state="active",
                        correct_guess_time_seconds=5,
                    )
                )
                session.add(
                    TurnGuess(
                        id=generate_uuid(),
                        turn_id=turn_id,
                        user_id=user_id,
                        participant_id=seat_id,
                        outcome_id=outcome_id,
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
                    drawer_participant_id=p1.id,
                    prompt="banana",
                    duration_seconds=45.5,
                )
                session.add(r1)

                o1 = TurnParticipantOutcome(
                    id=generate_uuid(),
                    game_id=game_id,
                    turn_id=r1.id,
                    participant_id=p2.id,
                    eligible=True,
                    eligibility_reason="eligible",
                    outcome="correct",
                    terminal_state="active",
                    correct_guess_time_seconds=12.3,
                )
                session.add(o1)
                g1 = TurnGuess(
                    id=generate_uuid(),
                    turn_id=r1.id,
                    user_id=u2_id,
                    participant_id=p2.id,
                    outcome_id=o1.id,
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
    drawer_seat_id = generate_uuid()
    guesser_seat_id = generate_uuid()
    turn_id = generate_uuid()
    outcome_id = generate_uuid()
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
                            id=drawer_seat_id,
                            game_id=game_id,
                            user_id=drawer_id,
                            final_score=300,
                            final_rank=1,
                        ),
                        GameParticipant(
                            id=guesser_seat_id,
                            game_id=game_id,
                            user_id=guesser_id,
                            final_score=200,
                            final_rank=2,
                        ),
                        TurnRecord(
                            id=turn_id,
                            game_id=game_id,
                            round_number=1,
                            turn_number=1,
                            drawer_user_id=drawer_id,
                            drawer_participant_id=drawer_seat_id,
                            prompt="anchor",
                            duration_seconds=30,
                        ),
                        TurnParticipantOutcome(
                            id=outcome_id,
                            game_id=game_id,
                            turn_id=turn_id,
                            participant_id=guesser_seat_id,
                            eligible=True,
                            eligibility_reason="eligible",
                            outcome="correct",
                            terminal_state="active",
                            correct_guess_time_seconds=10,
                        ),
                        TurnGuess(
                            id=generate_uuid(),
                            turn_id=turn_id,
                            user_id=guesser_id,
                            participant_id=guesser_seat_id,
                            outcome_id=outcome_id,
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
                drawer_participant_id=drawer_seat_id,
                prompt="duplicate",
                duration_seconds=20,
            ),
            # Reuses the original outcome: one correct outcome cannot have two
            # scoring children, and the same seat cannot guess twice in a turn.
            TurnGuess(
                id=generate_uuid(),
                turn_id=turn_id,
                user_id=guesser_id,
                participant_id=guesser_seat_id,
                outcome_id=outcome_id,
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


async def test_turn_participant_outcomes_enforce_identity_and_state_invariants():
    factory, engine = await create_test_db()
    game_id = generate_uuid()
    turn_id = generate_uuid()
    drawer_user_id = generate_uuid()
    guesser_user_id = generate_uuid()
    drawer_seat_id = generate_uuid()
    guesser_seat_id = generate_uuid()
    now = datetime.now(timezone.utc)
    try:
        async with factory() as session:
            async with session.begin():
                session.add_all(
                    [
                        User(id=drawer_user_id, display_name="Drawer"),
                        User(id=guesser_user_id, display_name="Guesser"),
                        GameRecord(
                            id=game_id,
                            room_name="Outcomes",
                            scoring_mode="default",
                            hint_mode="none",
                            drawing_seconds=90,
                            total_rounds=1,
                            player_count=2,
                            started_at=now,
                            finished_at=now,
                        ),
                        GameParticipant(
                            id=drawer_seat_id,
                            game_id=game_id,
                            user_id=drawer_user_id,
                            final_score=100,
                            final_rank=1,
                        ),
                        GameParticipant(
                            id=guesser_seat_id,
                            game_id=game_id,
                            user_id=guesser_user_id,
                            final_score=50,
                            final_rank=2,
                        ),
                        TurnRecord(
                            id=turn_id,
                            game_id=game_id,
                            round_number=1,
                            turn_number=1,
                            drawer_user_id=drawer_user_id,
                            drawer_participant_id=drawer_seat_id,
                            prompt="anchor",
                            duration_seconds=30,
                        ),
                        TurnParticipantOutcome(
                            id=generate_uuid(),
                            game_id=game_id,
                            turn_id=turn_id,
                            participant_id=guesser_seat_id,
                            eligible=True,
                            eligibility_reason="eligible",
                            outcome="correct",
                            terminal_state="active",
                            correct_guess_time_seconds=10,
                        ),
                    ]
                )

        invalid_rows = (
            TurnParticipantOutcome(
                id=generate_uuid(),
                game_id=game_id,
                turn_id=turn_id,
                participant_id=guesser_seat_id,
                eligible=True,
                eligibility_reason="eligible",
                outcome="no_attempt",
                terminal_state="active",
            ),
            TurnParticipantOutcome(
                id=generate_uuid(),
                game_id=game_id,
                turn_id=turn_id,
                participant_id=drawer_seat_id,
                eligible=True,
                eligibility_reason="joined_late",
                outcome="no_attempt",
                terminal_state="active",
            ),
        )
        for invalid_row in invalid_rows:
            with pytest.raises(IntegrityError):
                async with factory() as session:
                    async with session.begin():
                        session.add(invalid_row)
    finally:
        await engine.dispose()


async def test_score_events_constrain_order_reason_direction_and_corrections():
    factory, engine = await create_test_db()
    game_id = generate_uuid()
    turn_id = generate_uuid()
    user_id = generate_uuid()
    seat_id = generate_uuid()
    event_id = generate_uuid()
    now = datetime.now(timezone.utc)
    try:
        async with factory() as session:
            async with session.begin():
                session.add_all(
                    [
                        User(id=user_id, display_name="Scorer"),
                        GameRecord(
                            id=game_id,
                            room_name="Ledger",
                            scoring_mode="default",
                            scoring_version=1,
                            score_ledger_version=1,
                            rule_snapshot_version=1,
                            hint_mode="none",
                            drawing_seconds=90,
                            total_rounds=1,
                            player_count=1,
                            started_at=now,
                            finished_at=now,
                        ),
                        GameParticipant(
                            id=seat_id,
                            game_id=game_id,
                            user_id=user_id,
                            final_score=100,
                            final_rank=1,
                        ),
                        TurnRecord(
                            id=turn_id,
                            game_id=game_id,
                            round_number=1,
                            turn_number=1,
                            drawer_user_id=user_id,
                            drawer_participant_id=seat_id,
                            prompt="anchor",
                            duration_seconds=30,
                        ),
                        ScoreEvent(
                            id=event_id,
                            game_id=game_id,
                            participant_id=seat_id,
                            turn_id=turn_id,
                            event_order=1,
                            event_type="guess_award",
                            points_delta=100,
                            scoring_version=1,
                            rule_snapshot_version=1,
                        ),
                    ]
                )

        invalid_rows = (
            ScoreEvent(
                id=generate_uuid(),
                game_id=game_id,
                participant_id=seat_id,
                turn_id=turn_id,
                event_order=2,
                event_type="hint_charge",
                points_delta=10,
                scoring_version=1,
                rule_snapshot_version=1,
            ),
            ScoreEvent(
                id=generate_uuid(),
                game_id=game_id,
                participant_id=seat_id,
                event_order=2,
                event_type="correction",
                points_delta=-10,
                scoring_version=1,
                rule_snapshot_version=1,
            ),
            ScoreEvent(
                id=generate_uuid(),
                game_id=game_id,
                participant_id=seat_id,
                turn_id=turn_id,
                event_order=1,
                event_type="drawer_bonus",
                points_delta=1,
                scoring_version=1,
                rule_snapshot_version=1,
            ),
        )
        for invalid_row in invalid_rows:
            with pytest.raises(IntegrityError):
                async with factory() as session:
                    async with session.begin():
                        session.add(invalid_row)

        async with factory() as session:
            async with session.begin():
                session.add(
                    ScoreEvent(
                        id=generate_uuid(),
                        game_id=game_id,
                        participant_id=seat_id,
                        event_order=2,
                        event_type="correction",
                        points_delta=-10,
                        scoring_version=1,
                        rule_snapshot_version=1,
                        corrects_event_id=event_id,
                    )
                )
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
            "ck_score_events_event_type": SCORE_EVENT_TYPES,
            "ck_prompt_lists_language": PROMPT_LANGUAGES,
        }
        constraints = {
            constraint.name: str(constraint.sqltext)
            for table in (GameRecord, TurnRecord, ScoreEvent, PromptList)
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
                await session.flush()

                def _identified(text_value):
                    concept = PromptConcept(id=generate_uuid())
                    version = PromptVersion(
                        id=generate_uuid(),
                        concept_id=concept.id,
                        language="en",
                        version=1,
                        canonical_answer=text_value,
                        match_key=text_value,
                    )
                    prompt = Prompt(
                        id=generate_uuid(),
                        prompt_list_id=wl_id,
                        concept_id=concept.id,
                        prompt_version_id=version.id,
                        text=text_value,
                    )
                    return concept, version, prompt

                c1, v1, w1 = _identified("dog")
                c2, v2, w2 = _identified("cat")
                session.add_all([c1, c2])
                await session.flush()
                session.add_all([v1, v2])
                await session.flush()
                session.add_all([w1, w2])

        async with factory() as session:
            stmt = select(Prompt).where(Prompt.prompt_list_id == wl_id)
            words = (await session.execute(stmt)).scalars().all()
            assert len(words) == 2

        # Attempt duplicate prompt text in same list
        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    dup_concept = PromptConcept(id=generate_uuid())
                    dup_version = PromptVersion(
                        id=generate_uuid(),
                        concept_id=dup_concept.id,
                        language="en",
                        version=1,
                        canonical_answer="dog",
                        match_key="dog-2",
                    )
                    dup = Prompt(
                        id=generate_uuid(),
                        prompt_list_id=wl_id,
                        concept_id=dup_concept.id,
                        prompt_version_id=dup_version.id,
                        text="dog",
                    )
                    session.add_all([dup_concept, dup_version, dup])
    finally:
        await engine.dispose()


async def test_prompt_server_defaults_apply_to_raw_inserts():
    factory, engine = await create_test_db()
    prompt_list_id = generate_uuid()
    prompt_id = generate_uuid()
    concept_id = generate_uuid()
    version_id = generate_uuid()

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
                text("INSERT INTO prompt_concepts (id) VALUES (:id)"),
                {"id": concept_id.hex},
            )
            await connection.execute(
                text(
                    "INSERT INTO prompt_versions (id, concept_id, language, "
                    "version, canonical_answer, match_key) VALUES "
                    "(:id, :concept_id, 'en', 1, 'anchor', 'anchor')"
                ),
                {"id": version_id.hex, "concept_id": concept_id.hex},
            )
            await connection.execute(
                text(
                    "INSERT INTO prompts (id, prompt_list_id, concept_id, "
                    "prompt_version_id, text) "
                    "VALUES (:id, :prompt_list_id, :concept_id, :version_id, :text)"
                ),
                {
                    "id": prompt_id.hex,
                    "prompt_list_id": prompt_list_id.hex,
                    "concept_id": concept_id.hex,
                    "version_id": version_id.hex,
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
        assert prompt.text == "anchor"
        assert prompt.created_at is not None
        assert prompt.created_at.tzinfo is not None
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
    would not fail this test. See `User.__table_args__`. SQLite also fails to
    reflect ON DELETE options for references added inline with ADD COLUMN; the
    migration replay suite asserts their actual PRAGMA values directly. That
    suite also exercises the trigger equivalent of the cross-column prompt
    identity check that SQLite cannot add without rebuilding the parent table.
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

    inline_reference_columns = {
        # SQLite does not reflect ON DELETE for a reference added inline with
        # ADD COLUMN. The migration replay suite asserts the PRAGMA directly.
        ("user_bans", "source_report_id"),
        ("turn_records", "prompt_version_id"),
        ("turn_records", "drawer_participant_id"),
        ("turn_guesses", "participant_id"),
        ("turn_guesses", "outcome_id"),
    }
    differences = [
        difference
        for difference in differences
        if not (
            (
                difference[0] in {"add_fk", "remove_fk"}
                and (
                    difference[1].table.name,
                    next(iter(difference[1].column_keys)),
                )
                in inline_reference_columns
            )
                or (
                    difference[0] == "add_constraint"
                    and difference[1].name
                    in {
                        "ck_turn_records_prompt_identity",
                        "ck_game_records_score_ledger_version",
                    }
                )
        )
    ]
    assert differences == [], f"models and migrations have drifted: {differences}"


async def test_history_bounds_reject_impossible_rows():
    """game_records and turn_records carry the same numeric floors the
    room-settings tables have always pinned, plus event-time ordering."""
    factory, engine = await create_test_db()
    now = datetime.now(timezone.utc)

    def game_row(**overrides):
        values = dict(
            id=generate_uuid(),
            room_name="Bounds room",
            scoring_mode="default",
            hint_mode="none",
            drawing_seconds=90,
            total_rounds=1,
            player_count=2,
            started_at=now,
            finished_at=now,
        )
        values.update(overrides)
        return GameRecord(**values)

    try:
        for bad in (
            game_row(player_count=0),
            game_row(total_rounds=0),
            game_row(drawing_seconds=0),
            game_row(started_at=now, finished_at=now - timedelta(seconds=1)),
        ):
            with pytest.raises(IntegrityError):
                async with factory() as session:
                    async with session.begin():
                        session.add(bad)

        game_id = generate_uuid()
        seat_id = generate_uuid()
        async with factory() as session:
            async with session.begin():
                session.add(game_row(id=game_id))
                session.add(
                    GameParticipant(
                        id=seat_id,
                        game_id=game_id,
                        final_score=100,
                        # Null is the abandoned-game shape and must be legal.
                        final_rank=None,
                    )
                )
        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    session.add(
                        TurnRecord(
                            id=generate_uuid(),
                            game_id=game_id,
                            round_number=1,
                            turn_number=1,
                            drawer_participant_id=seat_id,
                            prompt="anchor",
                            duration_seconds=0,
                        )
                    )
        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    session.add(
                        GameParticipant(
                            id=generate_uuid(),
                            game_id=game_id,
                            final_score=0,
                            final_rank=0,
                        )
                    )
    finally:
        await engine.dispose()


async def test_history_rows_cannot_reference_another_game(tmp_path):
    """The same-game constraints, exercised: a score event, outcome, or guess
    naming a row from a different game is a violation, not a plausible lie.

    Uses the real engine factory so SQLite actually enforces foreign keys -
    the plain fixture engine leaves them off.
    """
    from app.db import create_db_engine

    engine = create_db_engine(f"sqlite+aiosqlite:///{tmp_path / 'coherence.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)

    def game_row(gid):
        return GameRecord(
            id=gid,
            room_name="Coherence room",
            scoring_mode="default",
            hint_mode="none",
            drawing_seconds=90,
            total_rounds=1,
            player_count=1,
            started_at=now,
            finished_at=now,
        )

    game_a, game_b = generate_uuid(), generate_uuid()
    seat_a, seat_b = generate_uuid(), generate_uuid()
    turn_a, turn_b = generate_uuid(), generate_uuid()
    outcome_a = generate_uuid()
    try:
        async with factory() as session:
            async with session.begin():
                session.add_all([game_row(game_a), game_row(game_b)])
                for gid, sid, tid in (
                    (game_a, seat_a, turn_a),
                    (game_b, seat_b, turn_b),
                ):
                    session.add(
                        GameParticipant(
                            id=sid, game_id=gid, final_score=0, final_rank=1
                        )
                    )
                    session.add(
                        TurnRecord(
                            id=tid,
                            game_id=gid,
                            round_number=1,
                            turn_number=1,
                            drawer_participant_id=sid,
                            prompt="anchor",
                            duration_seconds=10,
                        )
                    )
                session.add(
                    TurnParticipantOutcome(
                        id=outcome_a,
                        game_id=game_a,
                        turn_id=turn_a,
                        participant_id=seat_a,
                        eligible=True,
                        eligibility_reason="eligible",
                        outcome="correct",
                        terminal_state="active",
                        correct_guess_time_seconds=5,
                    )
                )

        incoherent_rows = (
            # A turn whose drawer seat belongs to the other game.
            TurnRecord(
                id=generate_uuid(),
                game_id=game_a,
                round_number=1,
                turn_number=2,
                drawer_participant_id=seat_b,
                prompt="bridge",
                duration_seconds=10,
            ),
            # An award to a seat from the other game.
            ScoreEvent(
                id=generate_uuid(),
                game_id=game_a,
                participant_id=seat_b,
                turn_id=turn_a,
                event_order=1,
                event_type="guess_award",
                points_delta=10,
                scoring_version=1,
                rule_snapshot_version=1,
            ),
            # A charge against the other game's turn.
            ScoreEvent(
                id=generate_uuid(),
                game_id=game_a,
                participant_id=seat_a,
                turn_id=turn_b,
                event_order=1,
                event_type="guess_award",
                points_delta=10,
                scoring_version=1,
                rule_snapshot_version=1,
            ),
            # An outcome whose seat belongs to the other game.
            TurnParticipantOutcome(
                id=generate_uuid(),
                game_id=game_a,
                turn_id=turn_a,
                participant_id=seat_b,
                eligible=True,
                eligibility_reason="eligible",
                outcome="no_attempt",
                terminal_state="active",
            ),
            # A guess scoring an outcome from a different turn.
            TurnGuess(
                id=generate_uuid(),
                turn_id=turn_b,
                participant_id=seat_b,
                outcome_id=outcome_a,
                points_awarded=10,
                guess_time_seconds=5,
            ),
        )
        for incoherent in incoherent_rows:
            with pytest.raises(IntegrityError):
                async with factory() as session:
                    async with session.begin():
                        session.add(incoherent)
    finally:
        await engine.dispose()


async def test_absent_json_is_sql_null_not_a_stored_token():
    """A Python None must reach the database as SQL NULL. SQLAlchemy's JSON
    type persists it as the JSON value `null` by default - a four-character
    token in a column that reads back as absent, and larger than the `{}` it
    was meant to replace."""
    factory, engine = await create_test_db()
    try:
        async with factory() as session:
            async with session.begin():
                session.add(
                    RuntimeEvent(
                        event_type="room.created",
                        occurred_at=datetime.now(timezone.utc),
                        details=None,
                    )
                )
        async with engine.begin() as connection:
            stored = (
                await connection.execute(
                    text(
                        "SELECT details IS NULL FROM runtime_events"
                    )
                )
            ).scalar_one()
        assert stored, "absent details is SQL NULL, not the token 'null'"
        async with factory() as session:
            event = await session.scalar(select(RuntimeEvent))
        assert event.details is None
    finally:
        await engine.dispose()


async def test_no_index_duplicates_the_leading_column_of_a_composite():
    """The convention, executable.

    A composite key already serves every lookup and range scan on its own
    prefix, so a standalone index on that leading column is a second B-tree
    covering a strict subset of the first: storage, plus one more index to
    maintain on every write. This census has drifted three times - twelve
    entries originally, nineteen once an audit found the pairs it had missed
    and two new tables arrived carrying the same shape, seventeen after two
    became primary keys - which is why the rule is asserted here rather than
    only written down.

    Two kinds of single-column index are **not** redundant and are skipped:
    one that is unique or partial enforces an invariant rather than
    accelerating a lookup, and a composite prefix cannot replace it; and a
    partner that is itself partial covers only the rows matching its
    predicate, so it serves no lookup across the rest.
    """

    def is_partial(index):
        return (
            index.dialect_options.get("postgresql", {}).get("where") is not None
            or index.dialect_options.get("sqlite", {}).get("where") is not None
        )

    offenders = []
    for table in Base.metadata.sorted_tables:
        leading = {}
        for index in table.indexes:
            columns = list(index.columns)
            if len(columns) > 1:
                leading.setdefault(
                    columns[0].name, (f"index {index.name}", is_partial(index))
                )
        for constraint in table.constraints:
            if (
                isinstance(constraint, UniqueConstraint)
                and len(constraint.columns) > 1
            ):
                leading.setdefault(
                    list(constraint.columns)[0].name,
                    (f"unique constraint {constraint.name}", False),
                )
        primary_key = list(table.primary_key.columns)
        if len(primary_key) > 1:
            leading.setdefault(primary_key[0].name, ("the primary key", False))

        for index in table.indexes:
            columns = list(index.columns)
            if len(columns) != 1 or index.unique or is_partial(index):
                continue
            covered_by = leading.get(columns[0].name)
            if covered_by is not None and not covered_by[1]:
                offenders.append(
                    f"{table.name}.{columns[0].name} ({index.name}) "
                    f"duplicates the leading column of {covered_by[0]}"
                )

    assert offenders == [], (
        "these indexes cover a strict subset of a composite that already "
        "leads with the same column: " + "; ".join(offenders)
    )


async def _two_accounts(factory):
    """A pair of accounts, returned in the canonical order the table wants."""
    low, high = sorted([generate_uuid(), generate_uuid()])
    async with factory() as session:
        async with session.begin():
            for index, user_id in enumerate((low, high)):
                session.add(
                    User(id=user_id, display_name=f"Player{index}", username=f"p{index}")
                )
    return low, high


async def test_a_friendship_is_stored_once_in_a_canonical_order():
    """The ordering is the identity, so the database has to enforce it.

    And it has to enforce it the *same way* on both engines: PostgreSQL
    compares `uuid` as sixteen bytes while SQLite compares the hex string
    SQLAlchemy stores, and this table's whole shape rests on those two orders
    agreeing. They do - both are big-endian over the same bytes - but "they
    do" is a claim about two databases, so this module was added to the
    PostgreSQL job in CI rather than left to prove it on SQLite alone.
    """
    factory, engine = await create_test_db()
    try:
        low, high = await _two_accounts(factory)
        async with factory() as session:
            async with session.begin():
                session.add(
                    Friendship(
                        user_low_id=low,
                        user_high_id=high,
                        requested_by_id=low,
                        status=FriendshipState.PENDING.value,
                    )
                )
        # The pair written the wrong way round is a different row to the
        # primary key and the same relationship to a person, which is exactly
        # what the CHECK exists to make impossible.
        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    session.add(
                        Friendship(
                            user_low_id=high,
                            user_high_id=low,
                            requested_by_id=low,
                            status=FriendshipState.PENDING.value,
                        )
                    )
    finally:
        await engine.dispose()


async def test_a_friendship_cannot_be_with_yourself_or_a_stranger():
    factory, engine = await create_test_db()
    try:
        low, high = await _two_accounts(factory)
        outsider = generate_uuid()
        async with factory() as session:
            async with session.begin():
                session.add(User(id=outsider, display_name="Outsider", username="out"))

        # `x < x` is false, so the ordering constraint forbids a self-friendship
        # without a second constraint saying so.
        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    session.add(
                        Friendship(
                            user_low_id=low,
                            user_high_id=low,
                            requested_by_id=low,
                            status=FriendshipState.PENDING.value,
                        )
                    )

        # Somebody outside the pair cannot be the one who asked - the column
        # that makes an incoming request tellable from an outgoing one would
        # otherwise be able to name a third party.
        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    session.add(
                        Friendship(
                            user_low_id=low,
                            user_high_id=high,
                            requested_by_id=outsider,
                            status=FriendshipState.PENDING.value,
                        )
                    )
    finally:
        await engine.dispose()


async def test_a_friendship_status_is_database_constrained():
    factory, engine = await create_test_db()
    try:
        low, high = await _two_accounts(factory)
        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    session.add(
                        Friendship(
                            user_low_id=low,
                            user_high_id=high,
                            requested_by_id=low,
                            status="besties",
                        )
                    )
    finally:
        await engine.dispose()



async def test_a_lobby_line_has_no_room_and_no_seat_and_nothing_else_does():
    """A null scope is a statement - this was said in the lobby - never a room
    line that lost its room; and the lobby holds chat, not guesses."""
    factory, engine = await create_test_db()
    sender_id = generate_uuid()
    now = datetime.now(timezone.utc)
    common = {
        "sender_user_id": sender_id,
        "sender_display_name_snapshot": "Sender",
        "sender_is_anonymous_snapshot": False,
        "is_spectator": False,
        "audience_user_ids": [],
        "created_at": now,
        "expires_at": now + timedelta(days=30),
    }
    try:
        async with factory() as session:
            async with session.begin():
                session.add(User(id=sender_id, display_name="Sender"))
                await session.flush()
                session.add(
                    RoomMessage(
                        id=generate_uuid(),
                        message_kind="chat",
                        audience="lobby",
                        room_instance_id=None,
                        sender_player_id=None,
                        text="valid lobby chat",
                        **common,
                    )
                )

        invalid_rows = (
            RoomMessage(
                id=generate_uuid(),
                message_kind="chat",
                audience="lobby",
                room_instance_id=generate_uuid(),
                sender_player_id=None,
                text="a lobby line with a room",
                **common,
            ),
            RoomMessage(
                id=generate_uuid(),
                message_kind="chat",
                audience="lobby",
                room_instance_id=None,
                sender_player_id=generate_uuid(),
                text="a lobby line with a seat",
                **common,
            ),
            RoomMessage(
                id=generate_uuid(),
                message_kind="chat",
                audience="room",
                room_instance_id=None,
                sender_player_id=generate_uuid(),
                text="a room line with no room",
                **common,
            ),
            RoomMessage(
                id=generate_uuid(),
                message_kind="chat",
                audience="prompt_aware",
                room_instance_id=generate_uuid(),
                sender_player_id=None,
                text="a room line with no seat",
                **common,
            ),
            RoomMessage(
                id=generate_uuid(),
                message_kind="wrong_guess",
                audience="lobby",
                room_instance_id=None,
                sender_player_id=None,
                game_id=generate_uuid(),
                turn_id=generate_uuid(),
                text="a guess in the lobby",
                **common,
            ),
        )
        for invalid_row in invalid_rows:
            with pytest.raises(IntegrityError):
                async with factory() as session:
                    async with session.begin():
                        session.add(invalid_row)
    finally:
        await engine.dispose()


async def test_the_shared_fixture_rejects_a_dangling_reference_and_a_restricted_delete():
    """A suite whose database ignores foreign keys proves nothing about deletion.

    #612 found the persistence fixtures running SQLite with `foreign_keys`
    off, so list and account deletions that violate RESTRICT constraints
    passed anyway. Every fixture now comes from `tests.dbfixtures`, and this
    is the proof that the database it hands out enforces both directions:
    an insert naming a missing parent, and a delete a child forbids.
    """
    factory, engine = await create_test_db()
    try:
        async with factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    session.add(
                        RoomMessage(
                            id=generate_uuid(),
                            room_instance_id=generate_uuid(),
                            sender_user_id=generate_uuid(),
                            sender_player_id=generate_uuid(),
                            sender_display_name_snapshot="Nobody",
                            sender_is_anonymous_snapshot=True,
                            is_spectator=False,
                            message_kind="chat",
                            audience="room",
                            audience_user_ids=[],
                            text="from an account that does not exist",
                            created_at=datetime.now(timezone.utc),
                            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                        )
                    )

        guest_id, account_id = generate_uuid(), generate_uuid()
        async with factory() as session:
            async with session.begin():
                session.add_all(
                    [
                        User(id=guest_id, display_name="Guest"),
                        User(id=account_id, display_name="Account"),
                    ]
                )
                await session.flush()
                session.add(
                    IdentityAlias(source_user_id=guest_id, target_user_id=account_id)
                )

        async with factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    await session.execute(
                        text("DELETE FROM users WHERE id = :id"),
                        {"id": account_id.hex if engine.dialect.name == "sqlite" else account_id},
                    )
    finally:
        await engine.dispose()


def test_the_fixture_refuses_a_sqlite_connection_with_foreign_keys_off():
    """The per-connection check is what makes the fixture's promise checkable."""
    import sqlite3

    raw = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ForeignKeysOffError):
            _assert_foreign_keys_enforced(raw, None)
        raw.execute("PRAGMA foreign_keys=ON")
        _assert_foreign_keys_enforced(raw, None)
    finally:
        raw.close()


async def test_every_fixture_engine_is_configured_like_the_application():
    """What `create_test_engine` hands out carries the production pragmas."""
    engine = create_test_engine(SQLITE_MEMORY_URL)
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
    finally:
        await engine.dispose()
