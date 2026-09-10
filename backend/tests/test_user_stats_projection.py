"""Daily profile-stat projections stay current and remain fully rebuildable."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os
from uuid import UUID

import pytest
from sqlalchemy import delete, event, select, update
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

        real_fold = repository.fold_identity_into_account
        merge_holds_the_rows = asyncio.Event()
        let_the_merge_commit = asyncio.Event()

        async def paused_rebuild(session, **kwargs):
            merge_holds_the_rows.set()
            await let_the_merge_commit.wait()
            return await real_fold(session, **kwargs)

        monkeypatch.setattr(repository, "fold_identity_into_account", paused_rebuild)
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


def _bound_parameter_counts(engine):
    """Record how wide each statement's parameter list is, until released.

    Not a count of statements or of rows: the regression below was one
    statement whose bind list grew with the account's history, so the width
    of the widest list is exactly what says whether it is back.
    """
    counts: list[int] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        # An executemany binds one row's parameters over and over, which is
        # bounded by the batch rather than by the query. The driver's limit
        # is on what a single statement binds.
        if not executemany and parameters is not None:
            counts.append(len(parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", record)

    def release():
        event.remove(engine.sync_engine, "before_cursor_execute", record)

    return counts, release


async def _seed_finished_games(factory, user_id: UUID, count: int, *, start: datetime) -> None:
    """`count` finished games for one account, one seat and one turn each.

    Always across the same two UTC days, so that two seedings of different
    sizes differ in the number of games and in nothing else - the day count
    is what the projection's own writes are bound by.
    """
    from sqlalchemy import insert

    from app.db.models import GameParticipant, GameRecord, TurnRecord

    games, seats, turns = [], [], []
    for index in range(count):
        game_id, seat_id = generate_uuid(), generate_uuid()
        finished_at = start + timedelta(days=index % 2, minutes=index)
        games.append(
            {
                "id": game_id,
                "payload_hash": f"veteran-{user_id}-{index}",
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
                "user_id": user_id,
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
                "drawer_user_id": user_id,
                "drawer_participant_id": seat_id,
                "drawer_display_name_snapshot": "Veteran",
                "drawer_is_anonymous_snapshot": True,
                "prompt": "anchor",
                "duration_seconds": 30,
            }
        )
    async with factory() as session:
        async with session.begin():
            for table, rows in (
                (GameRecord, games),
                (GameParticipant, seats),
                (TurnRecord, turns),
            ):
                await session.execute(insert(table), rows)


async def test_no_statement_of_a_rebuild_widens_with_the_history():
    """asyncpg binds at most 32,767 parameters, and the rebuild used to send
    every game id of the account as one.

    What must hold is not "33,000 games fit" but that every statement is
    keyed by identity, so nothing they bind grows with the history at all -
    which is what `_rebuild_accounts` says it does, reading the account's
    games as a subquery rather than a bind list. Two small histories and a
    count of what each statement binds pin that exactly.

    This test used to seed 33,000 games to cross the driver's bound. It was
    the largest in the suite by a factor of twenty-five, it took between 9 s
    and 100 s on CI with nothing to say why, and it was the whole difference
    between a fast and a slow PostgreSQL job. It also could not have caught a
    rebuild that bound twenty thousand ids, which is the same defect one
    account short of the limit.

    The maintenance role is kept because that is the engine production
    rebuilds on: `_run_cli` opens `maintenance_engine()`.
    """
    factory, engine = await create_test_db(role="maintenance")
    users = SqlAlchemyUserRepository(factory)
    try:
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        widest = {}
        for count in (4, 40):
            player = await users.create_anonymous(f"Veteran{count}")
            await _seed_finished_games(factory, UUID(player.id), count, start=start)

            counts, release = _bound_parameter_counts(engine)
            try:
                rows = await rebuild_user_stats_projection(
                    factory, user_id=UUID(player.id)
                )
            finally:
                release()

            assert rows == 2, "one row per UTC day of the seeded history"
            stats = await users.get_stats(player.id)
            assert stats.games_played == count and stats.turns_played == count
            widest[count] = max(counts)

        assert widest[4] == widest[40], (
            "a statement widened with the account's history: "
            f"{widest[4]} parameters over 4 games, {widest[40]} over 40"
        )
    finally:
        await engine.dispose()


async def _daily_rows(factory, user_id: str) -> dict:
    """Every projection row of one identity, by day."""
    async with factory() as session:
        rows = (
            await session.scalars(
                select(UserStatsDaily).where(UserStatsDaily.user_id == UUID(user_id))
            )
        ).all()
    return {
        row.stat_date: (
            row.games_played,
            row.games_won,
            row.total_score,
            row.turns_played,
            row.drawings_made,
        )
        for row in rows
    }


async def test_a_merge_replaces_only_the_days_the_guest_has_facts_on():
    """The work a sign-in pays for is the guest's history, not the account's.

    A merge cannot change the account's total for a day the guest was not
    playing on, so those days are not read and not rewritten (#709). The
    account's row on an untouched day is left deliberately wrong here: a
    rebuild that reached it would repair it, and the point is that it does
    not reach it. Drift is the full rebuild's job, not a login's.
    """
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    try:
        holder = await users.create_anonymous("Account")
        account = await users.claim_account(holder.id, "account", "hash")
        guest = await users.create_anonymous("Guest")
        other = await users.create_anonymous("Other")
        long_ago = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
        shared_day = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
        guest_only_day = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)
        await _save_game(history, finished_at=long_ago, first=account.id, second=other.id, first_wins=True)
        await _save_game(history, finished_at=shared_day, first=account.id, second=other.id, first_wins=True)
        await _save_game(history, finished_at=shared_day + timedelta(hours=2), first=guest.id, second=other.id, first_wins=False)
        await _save_game(history, finished_at=guest_only_day, first=guest.id, second=other.id, first_wins=True)

        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(UserStatsDaily)
                    .where(
                        UserStatsDaily.user_id == UUID(account.id),
                        UserStatsDaily.stat_date == long_ago.date(),
                    )
                    .values(games_played=99, total_score=9_999)
                )

        await users.merge_guest_into_account(guest.id, account.id)

        merged = await _daily_rows(factory, account.id)
        assert merged[long_ago.date()][0] == 99, "an untouched day is not read or rewritten"
        assert merged[shared_day.date()] == (2, 1, 150, 4, 2)
        assert merged[guest_only_day.date()] == (1, 1, 100, 2, 1)
        assert await _daily_rows(factory, guest.id) == {}

        # The days it did replace hold exactly what a full rebuild computes;
        # the day it left alone is the only one that changes.
        await rebuild_user_stats_projection(factory)
        repaired = await _daily_rows(factory, account.id)
        assert repaired[shared_day.date()] == merged[shared_day.date()]
        assert repaired[guest_only_day.date()] == merged[guest_only_day.date()]
        assert repaired[long_ago.date()] == (1, 1, 100, 2, 1)
    finally:
        await engine.dispose()


async def test_a_merge_takes_a_guest_row_whose_facts_are_gone_with_it():
    """A guest's days come from its rows as well as its games.

    A projection row outliving the facts behind it - a game erased under
    retention, a hand-run repair - would otherwise be left keyed by an
    identity nothing resolves to any more, counted by nobody and cleared by
    nothing short of a full rebuild.
    """
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    try:
        holder = await users.create_anonymous("Account")
        account = await users.claim_account(holder.id, "account", "hash")
        guest = await users.create_anonymous("Guest")
        orphaned = datetime(2026, 8, 20, tzinfo=timezone.utc).date()
        async with factory() as session:
            async with session.begin():
                session.add(
                    UserStatsDaily(
                        user_id=UUID(guest.id),
                        stat_date=orphaned,
                        games_played=3,
                        games_won=1,
                        total_score=120,
                    )
                )

        await users.merge_guest_into_account(guest.id, account.id)

        assert await _daily_rows(factory, guest.id) == {}
        assert await _daily_rows(factory, account.id) == {}
    finally:
        await engine.dispose()


async def test_a_merge_of_a_guest_that_never_played_leaves_the_account_alone():
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    try:
        holder = await users.create_anonymous("Account")
        account = await users.claim_account(holder.id, "account", "hash")
        guest = await users.create_anonymous("Guest")
        other = await users.create_anonymous("Other")
        day = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
        await _save_game(history, finished_at=day, first=account.id, second=other.id, first_wins=True)
        before = await _daily_rows(factory, account.id)

        await users.merge_guest_into_account(guest.id, account.id)

        assert await _daily_rows(factory, account.id) == before
        assert (await users.get_by_id(guest.id)).id == account.id
    finally:
        await engine.dispose()
