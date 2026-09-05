"""Daily profile-stat projections stay current and remain fully rebuildable."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import create_db_engine
from app.db.models import Base, UserStatsDaily, generate_uuid
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    TurnGuessInput,
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
                ),
            ),
        ),
    ]
    guesses = [
        TurnGuessInput(
            turn_id=second_turn,
            user_id=first,
            seat_id=first_seat,
            points_awarded=50,
            guess_time_seconds=10,
        )
    ]
    game_id = await history.save_game(record, participants, turns, guesses)
    return game_id, record, participants, turns, guesses


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
        game_id, record, participants, turns, guesses = saved
        assert await history.save_game(record, participants, turns, guesses) == game_id

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
        await connection.run_sync(Base.metadata.create_all)
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
