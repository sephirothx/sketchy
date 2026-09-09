"""Daily profile-stat projections stay current and remain fully rebuildable."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os
from uuid import UUID

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import create_db_engine
from app.db.models import Base, User, UserStatsDaily, generate_uuid
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from app.services.user_stats_projection import rebuild_user_stats_projection

from tests.dbfixtures import create_test_db


pytestmark = pytest.mark.asyncio


async def _save_game(history, *, finished_at, first, second, first_wins):
    first_turn = str(generate_uuid())
    second_turn = str(generate_uuid())
    record = GameRecordInput(
        id=str(generate_uuid()),
        room_name="Projected stats",
        scoring_mode="default",
        hint_mode="none",
        drawing_seconds=90,
        total_rounds=1,
        player_count=2,
        started_at=finished_at - timedelta(minutes=5),
        finished_at=finished_at,
    )
    first_seat = str(generate_uuid())
    second_seat = str(generate_uuid())
    participants = [
        GameParticipantInput(
            user_id=first,
            final_score=100 if first_wins else 50,
            final_rank=1 if first_wins else 2,
            seat_id=first_seat,
        ),
        GameParticipantInput(
            user_id=second,
            final_score=50 if first_wins else 100,
            final_rank=2 if first_wins else 1,
            seat_id=second_seat,
        ),
    ]
    turns = [
        TurnRecordInput(
            id=first_turn,
            round_number=1,
            turn_number=1,
            drawer_user_id=first,
            drawer_seat_id=first_seat,
            prompt="anchor",
            duration_seconds=20,
            guesser_count=1,
            participant_outcomes=(
                TurnParticipantOutcomeInput(
                    seat_id=second_seat,
                    user_id=second,
                    eligible=True,
                    eligibility_reason="eligible",
                    outcome="no_attempt",
                    terminal_state="active",
                ),
            ),
        ),
        TurnRecordInput(
            id=second_turn,
            round_number=1,
            turn_number=2,
            drawer_user_id=second,
            drawer_seat_id=second_seat,
            prompt="bridge",
            duration_seconds=25,
            guesser_count=1,
            participant_outcomes=(
                TurnParticipantOutcomeInput(
                    seat_id=first_seat,
                    user_id=first,
                    eligible=True,
                    eligibility_reason="eligible",
                    outcome="correct",
                    terminal_state="active",
                    correct_guess_time_seconds=10,
                    points_awarded=50,
                ),
            ),
        ),
    ]
    game_id = await history.save_game(record, participants, turns)
    return game_id, record, participants, turns


async def test_daily_projection_is_incremental_idempotent_and_bounded_on_read():
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    try:
        first = await users.create_anonymous("First")
        second = await users.create_anonymous("Second")
        first_day = datetime(2026, 8, 20, 23, 30, tzinfo=timezone.utc)
        saved = await _save_game(
            history,
            finished_at=first_day,
            first=first.id,
            second=second.id,
            first_wins=True,
        )
        await _save_game(
            history,
            finished_at=first_day + timedelta(days=1),
            first=first.id,
            second=second.id,
            first_wins=False,
        )

        # An idempotent game retry must not increment the projection twice.
        game_id, record, participants, turns = saved
        assert await history.save_game(record, participants, turns) == game_id

        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.lower())

        event.listen(engine.sync_engine, "before_cursor_execute", capture)
        try:
            stats = await users.get_stats(first.id)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", capture)

        assert stats.games_played == 2
        assert stats.games_won == 1
        assert stats.win_rate == 0.5
        assert stats.total_score == 150
        assert stats.average_score == 75
        assert stats.turns_played == 4
        assert stats.prompts_guessed == 2
        assert stats.drawings_made == 2
        assert all("game_participants" not in statement for statement in statements)
        assert all("turn_records" not in statement for statement in statements)
        assert all("turn_guesses" not in statement for statement in statements)
        assert any("user_stats_daily" in statement for statement in statements)

        async with factory() as session:
            rows = (
                await session.scalars(
                    select(UserStatsDaily)
                    .where(UserStatsDaily.user_id == UUID(first.id))
                    .order_by(UserStatsDaily.stat_date)
                )
            ).all()
        assert [row.stat_date.isoformat() for row in rows] == [
            "2026-08-20",
            "2026-08-21",
        ]
        assert [row.games_played for row in rows] == [1, 1]
    finally:
        await engine.dispose()


async def test_projection_rebuild_restores_exact_source_derived_totals():
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    try:
        first = await users.create_anonymous("First")
        second = await users.create_anonymous("Second")
        await _save_game(
            history,
            finished_at=datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
            first=first.id,
            second=second.id,
            first_wins=True,
        )
        expected = await users.get_stats(first.id)

        async with factory() as session:
            async with session.begin():
                await session.execute(delete(UserStatsDaily))
        assert (await users.get_stats(first.id)).games_played == 0

        assert await rebuild_user_stats_projection(factory) == 2
        assert await users.get_stats(first.id) == expected

        # A targeted rebuild is safe and replaces, rather than increments, the
        # selected canonical account's daily rows.
        assert await rebuild_user_stats_projection(
            factory, user_id=UUID(first.id)
        ) == 1
        assert await users.get_stats(first.id) == expected
    finally:
        await engine.dispose()


async def test_concurrent_same_day_game_saves_cannot_lose_an_increment(tmp_path):
    engine = create_db_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'concurrent-projection.db'}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, checkfirst=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    try:
        first = await users.create_anonymous("First")
        second = await users.create_anonymous("Second")
        finished_at = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
        await asyncio.gather(
            _save_game(
                history,
                finished_at=finished_at,
                first=first.id,
                second=second.id,
                first_wins=True,
            ),
            _save_game(
                history,
                finished_at=finished_at + timedelta(hours=1),
                first=first.id,
                second=second.id,
                first_wins=False,
            ),
        )

        stats = await users.get_stats(first.id)
        assert stats.games_played == 2
        assert stats.games_won == 1
        assert stats.total_score == 150
        async with factory() as session:
            rows = (
                await session.scalars(
                    select(UserStatsDaily).where(
                        UserStatsDaily.user_id == UUID(first.id)
                    )
                )
            ).all()
        assert len(rows) == 1
        assert rows[0].games_played == 2
    finally:
        await engine.dispose()


# --- #609: rebuilds are bounded, locked, and safe beside saves and merges ---


ON_POSTGRESQL = bool(os.environ.get("TEST_DATABASE_URL"))


async def _totals(users, user_id: str) -> tuple[int, int, int, int, int]:
    stats = await users.get_stats(user_id)
    return (
        stats.games_played,
        stats.games_won,
        stats.total_score,
        stats.turns_played,
        stats.prompts_guessed,
    )


async def _recomputed(factory, users, user_id: str):
    """The trusted answer: a fresh full rebuild, read back the same way."""
    await rebuild_user_stats_projection(factory)
    return await _totals(users, user_id)


@pytest.mark.skipif(not ON_POSTGRESQL, reason="row locks are only real on PostgreSQL")
async def test_a_game_saved_during_a_rebuild_waits_for_it_and_is_then_counted(
    monkeypatch,
):
    """The rebuild locks the account rows before reading; a save that arrives
    while it holds them waits, then increments the rows the rebuild wrote."""
    import app.services.user_stats_projection as projection

    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    try:
        first = await users.create_anonymous("First")
        second = await users.create_anonymous("Second")
        day = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
        await _save_game(history, finished_at=day, first=first.id, second=second.id, first_wins=True)

        real_stream = projection._stream
        rebuild_holds_the_rows = asyncio.Event()
        let_the_rebuild_commit = asyncio.Event()
        paused_once = False

        async def paused_stream(session, statement):
            nonlocal paused_once
            async for row in real_stream(session, statement):
                yield row
            if not paused_once:
                paused_once = True
                rebuild_holds_the_rows.set()
                await let_the_rebuild_commit.wait()

        monkeypatch.setattr(projection, "_stream", paused_stream)
        rebuild = asyncio.create_task(
            rebuild_user_stats_projection(factory, user_id=UUID(first.id))
        )
        await rebuild_holds_the_rows.wait()
        save = asyncio.create_task(
            _save_game(
                history,
                finished_at=day + timedelta(hours=1),
                first=first.id,
                second=second.id,
                first_wins=False,
            )
        )
        await asyncio.sleep(0.3)
        assert not save.done(), "the save must wait for the rebuild's row lock"
        let_the_rebuild_commit.set()
        await asyncio.gather(rebuild, save)
        monkeypatch.setattr(projection, "_stream", real_stream)

        incremental = await _totals(users, first.id)
        assert incremental == (2, 1, 150, 4, 2)
        assert incremental == await _recomputed(factory, users, first.id)
    finally:
        await engine.dispose()


@pytest.mark.skipif(not ON_POSTGRESQL, reason="row locks are only real on PostgreSQL")
async def test_two_saves_in_opposite_seat_order_do_not_deadlock():
    """Users are locked and projection rows upserted in ascending id order,
    whatever order the seats came in."""
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    try:
        first = await users.create_anonymous("First")
        second = await users.create_anonymous("Second")
        day = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
        for _ in range(3):
            await asyncio.wait_for(
                asyncio.gather(
                    _save_game(history, finished_at=day, first=first.id, second=second.id, first_wins=True),
                    _save_game(history, finished_at=day, first=second.id, second=first.id, first_wins=False),
                ),
                timeout=10,
            )
        # `first` wins both games of every pair: as the winner of the first
        # and, with the seats swapped and first_wins=False, of the second.
        incremental = await _totals(users, first.id)
        assert incremental == (6, 6, 600, 12, 3)
        assert incremental == await _recomputed(factory, users, first.id)
    finally:
        await engine.dispose()


@pytest.mark.skipif(not ON_POSTGRESQL, reason="row locks are only real on PostgreSQL")
async def test_a_game_saved_during_a_guest_merge_waits_and_lands_on_the_account(
    monkeypatch,
):
    import app.repositories.sqlalchemy as repository

    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    try:
        guest = await users.create_anonymous("Guest")
        other = await users.create_anonymous("Other")
        account = await users.create_anonymous("Account")
        async with factory() as session:
            async with session.begin():
                row = await session.get(User, UUID(account.id))
                row.state = "registered"
                row.username = "account"
                row.password_hash = "hash"
        day = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
        await _save_game(history, finished_at=day, first=guest.id, second=other.id, first_wins=True)

        real_rebuild = repository.rebuild_user_stats_in_session
        merge_holds_the_rows = asyncio.Event()
        let_the_merge_commit = asyncio.Event()

        async def paused_rebuild(session, **kwargs):
            merge_holds_the_rows.set()
            await let_the_merge_commit.wait()
            return await real_rebuild(session, **kwargs)

        monkeypatch.setattr(repository, "rebuild_user_stats_in_session", paused_rebuild)
        merge = asyncio.create_task(users.merge_guest_into_account(guest.id, account.id))
        await merge_holds_the_rows.wait()
        save = asyncio.create_task(
            _save_game(history, finished_at=day + timedelta(hours=1), first=guest.id, second=other.id, first_wins=False)
        )
        await asyncio.sleep(0.3)
        assert not save.done(), "the save must wait for the merge's lock on the guest"
        let_the_merge_commit.set()
        await asyncio.gather(merge, save)

        incremental = await _totals(users, account.id)
        assert incremental == (2, 1, 150, 4, 2)
        assert incremental == await _recomputed(factory, users, account.id)
    finally:
        await engine.dispose()


async def test_a_full_rebuild_works_in_bounded_batches_of_accounts():
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    try:
        players = [await users.create_anonymous(f"Player {index}") for index in range(3)]
        day = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
        await _save_game(history, finished_at=day, first=players[0].id, second=players[1].id, first_wins=True)
        await _save_game(history, finished_at=day, first=players[1].id, second=players[2].id, first_wins=True)
        expected = [await _totals(users, player.id) for player in players]

        async with factory() as session:
            async with session.begin():
                await session.execute(delete(UserStatsDaily))
        rows = await rebuild_user_stats_projection(factory, batch_size=1)

        assert rows == 3
        assert [await _totals(users, player.id) for player in players] == expected
    finally:
        await engine.dispose()


async def test_an_account_with_more_games_than_a_statement_can_bind_still_rebuilds():
    """asyncpg binds at most 32,767 parameters; the old rebuild sent every
    game id of the account as one. The reads are keyed by identity now."""
    from sqlalchemy import insert

    from app.db.models import GameParticipant, GameRecord, TurnRecord

    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    try:
        player = await users.create_anonymous("Veteran")
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        games, seats, turns = [], [], []
        for index in range(33_000):
            game_id, seat_id = generate_uuid(), generate_uuid()
            finished_at = start + timedelta(minutes=index)
            games.append(
                {
                    "id": game_id,
                    "payload_hash": f"veteran-{index}",
                    "room_name": "Long ago",
                    "scoring_mode": "default",
                    "hint_mode": "none",
                    "drawing_seconds": 60,
                    "total_rounds": 1,
                    "player_count": 1,
                    "started_at": finished_at - timedelta(minutes=1),
                    "finished_at": finished_at,
                }
            )
            seats.append(
                {
                    "id": seat_id,
                    "game_id": game_id,
                    "user_id": UUID(player.id),
                    "display_name_snapshot": "Veteran",
                    "is_anonymous_snapshot": True,
                    "final_score": 10,
                    "final_rank": 1,
                }
            )
            turns.append(
                {
                    "id": generate_uuid(),
                    "game_id": game_id,
                    "round_number": 1,
                    "turn_number": 1,
                    "drawer_user_id": UUID(player.id),
                    "drawer_participant_id": seat_id,
                    "drawer_display_name_snapshot": "Veteran",
                    "drawer_is_anonymous_snapshot": True,
                    "prompt": "anchor",
                    "duration_seconds": 30,
                }
            )
        # Seeded in chunks. The point of this test is what the *rebuild* does
        # with 33,000 games, not what one INSERT does with them: sent whole,
        # each of these three is a single statement big enough to run past the
        # role's seven-second `statement_timeout` on a busy runner, and the
        # test then fails during its own setup with an error about the thing
        # it is not testing. It failed that way four times across three pull
        # requests before this. The rows, and the assertions over them, are
        # unchanged.
        for table, rows_in in (
            (GameRecord, games),
            (GameParticipant, seats),
            (TurnRecord, turns),
        ):
            for start_at in range(0, len(rows_in), 2_000):
                async with factory() as session:
                    async with session.begin():
                        await session.execute(
                            insert(table), rows_in[start_at : start_at + 2_000]
                        )

        rows = await rebuild_user_stats_projection(factory, user_id=UUID(player.id))

        assert rows == 23, "one row per UTC day of a minute-apart history"
        stats = await users.get_stats(player.id)
        assert stats.games_played == 33_000 and stats.turns_played == 33_000
    finally:
        await engine.dispose()
