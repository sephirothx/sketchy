"""Every retention sweep is bounded, scheduled, observable and fault-isolated (#550)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import event, func, select

import app.auth.retention as retention
from app.auth.retention import (
    Sweep,
    purge_stale_anonymous_accounts,
    run_retention_loop,
    run_retention_sweeps,
)
from app.auth.tokens import AuthTokenPurpose, issue_token, purge_expired_tokens
from app.db.models import AuthToken, RoomMessage, User, generate_uuid
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.rooms import RoomManager
from app.services.message_retention import (
    MessageRetentionService,
    purge_expired_room_messages,
)
from app.services.readiness import LoopHealth
from app.services.sweeps import SweepBudget, SweepReport, sweep_budget_from_env

from tests.dbfixtures import create_test_db


def _capture_sql(engine) -> list[str]:
    statements: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    return statements


async def _messages(factory, count: int, *, expired: bool, now: datetime) -> None:
    speaker = generate_uuid()
    async with factory() as session:
        async with session.begin():
            if await session.get(User, speaker) is None:
                session.add(User(id=speaker, display_name="Speaker"))
            await session.flush()
            session.add_all(
                RoomMessage(
                    id=generate_uuid(),
                    room_instance_id=None,
                    sender_user_id=speaker,
                    sender_player_id=None,
                    sender_display_name_snapshot="Speaker",
                    sender_is_anonymous_snapshot=True,
                    is_spectator=False,
                    message_kind="chat",
                    audience="lobby",
                    audience_user_ids=[],
                    text=f"line {index}",
                    created_at=now - timedelta(days=31 if expired else 1, minutes=index),
                    expires_at=now - timedelta(days=1, minutes=index)
                    if expired
                    else now + timedelta(days=29),
                )
                for index in range(count)
            )


async def _count(factory, column) -> int:
    async with factory() as session:
        return await session.scalar(select(func.count(column)))


async def test_the_chat_insert_carries_no_delete():
    """The purge left the writer's transaction: a purge backlog can no longer
    be the reason a room's lines are dropped."""
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        talker = await users.create_anonymous("Talker")
        room_manager = RoomManager()
        room = room_manager.create_room(name="Quiet")
        player = room_manager.add_player(room, "Talker", user_id=talker.id)
        player.sid = "sid"
        statements = _capture_sql(engine)
        service = MessageRetentionService(factory)
        for index in range(3):
            assert (
                await service.record(
                    room=room,
                    player=player,
                    text=f"hello {index}",
                    message_kind="chat",
                    audience="room",
                    recipient_sids=[player.sid],
                )
                is not None
            )
            await service.drain()
        await service.aclose()
        assert not [s for s in statements if s.lstrip().upper().startswith("DELETE")]
        assert await _count(factory, RoomMessage.id) == 3
    finally:
        await engine.dispose()


async def test_a_sweep_stops_at_its_budget_says_so_and_catches_up_next_time():
    factory, engine = await create_test_db()
    try:
        now = datetime.now(timezone.utc)
        await _messages(factory, 7, expired=True, now=now)
        await _messages(factory, 2, expired=False, now=now)
        budget = SweepBudget(rows=4, batch=3, seconds=30)

        first = await purge_expired_room_messages(factory, now=now, budget=budget)
        assert first == 4 and isinstance(first, SweepReport)
        assert first.batches == 2 and first.exhausted
        assert first.oldest_overdue_seconds is not None and first.oldest_overdue_seconds > 0
        assert await _count(factory, RoomMessage.id) == 5

        second = await purge_expired_room_messages(factory, now=now, budget=budget)
        assert second == 3 and not second.exhausted and second.batches == 1
        # Rows inside their window are untouched however many sweeps run.
        assert await _count(factory, RoomMessage.id) == 2
        third = await purge_expired_room_messages(factory, now=now, budget=budget)
        assert third == 0 and third.batches == 0 and not third.exhausted
    finally:
        await engine.dispose()


async def test_a_sweep_stops_when_its_time_is_spent():
    factory, engine = await create_test_db()
    try:
        now = datetime.now(timezone.utc)
        await _messages(factory, 5, expired=True, now=now)
        ticks = iter([0.0, 0.0, 100.0, 100.0, 100.0])
        from app.services.sweeps import delete_in_batches
        from sqlalchemy import delete

        report = await delete_in_batches(
            factory,
            name="room_messages",
            candidates=select(RoomMessage.id).order_by(RoomMessage.id),
            delete_for=lambda ids: delete(RoomMessage).where(RoomMessage.id.in_(ids)),
            budget=SweepBudget(rows=100, batch=2, seconds=10),
            clock=lambda: next(ticks),
        )
        assert report == 2 and report.batches == 1 and report.exhausted
    finally:
        await engine.dispose()


async def test_one_failing_sweep_skips_nothing_after_it_and_is_counted():
    factory, engine = await create_test_db()
    try:
        now = datetime.now(timezone.utc)
        await _messages(factory, 3, expired=True, now=now)
        ran: list[str] = []

        async def broken(session_factory, *, budget):
            raise RuntimeError("this table is on fire")

        async def messages(session_factory, *, budget):
            ran.append("messages")
            return await purge_expired_room_messages(session_factory, budget=budget)

        health = LoopHealth("retention_sweep")
        reports = await run_retention_sweeps(
            factory,
            sweeps=(Sweep("broken", broken), Sweep("room_messages", messages)),
            budget=SweepBudget(rows=10, batch=10, seconds=5),
            health=health,
        )

        assert ran == ["messages"]
        assert reports["broken"]["failed"] is True
        # A failing table still reports the policy it is held to and how often
        # it has failed: the alert names the table, and the operator reading
        # the page should not have to look the allowance up elsewhere.
        assert reports["broken"]["failures_total"] == 1
        assert reports["broken"]["sla_seconds"] == retention.STANDARD_SLA_SECONDS
        assert reports["room_messages"]["rows"] == 3
        assert reports["room_messages"]["failed"] is False
        assert health.consecutive_failures == 1 and health.last_success is None
        assert health.snapshot()["detail"]["sweeps"]["broken"]["failed"] is True
        assert await _count(factory, RoomMessage.id) == 0
    finally:
        await engine.dispose()


async def test_a_sweep_that_ran_out_of_budget_brings_the_loop_back_sooner(monkeypatch):
    factory, engine = await create_test_db()
    try:
        now = datetime.now(timezone.utc)
        await _messages(factory, 5, expired=True, now=now)
        slept: list[float] = []

        async def note_sleep(seconds):
            slept.append(seconds)
            if len(slept) == 3:
                raise asyncio.CancelledError

        monkeypatch.setattr(retention.asyncio, "sleep", note_sleep)
        monkeypatch.setattr(
            retention,
            "retention_sweeps",
            lambda: (Sweep("room_messages", purge_expired_room_messages),),
        )
        monkeypatch.setattr(
            retention, "sweep_budget_from_env", lambda: SweepBudget(rows=2, batch=2, seconds=5)
        )
        with pytest.raises(asyncio.CancelledError):
            await run_retention_loop(factory, interval_seconds=3600, catch_up_seconds=5)

        # Two catch-up ticks while behind (2 + 2 rows), then the last row
        # goes and the loop settles back to its interval.
        assert slept == [5, 5, 3600]
        assert await _count(factory, RoomMessage.id) == 0
    finally:
        await engine.dispose()


async def test_a_flood_of_unused_guests_cannot_starve_the_played_tier():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        now = datetime(2026, 8, 22, tzinfo=timezone.utc)
        from sqlalchemy import update

        from app.db.models import GameParticipant, GameRecord

        for index in range(12):
            guest = await users.create_anonymous(f"Unused {index}")
            async with factory() as session:
                async with session.begin():
                    await session.execute(
                        update(User)
                        .where(User.id == UUID(guest.id))
                        .values(last_active_at=now - timedelta(days=40, minutes=index))
                    )
        played = [await users.create_anonymous(f"Played {index}") for index in range(3)]
        async with factory() as session:
            async with session.begin():
                for guest in played:
                    game_id = generate_uuid()
                    session.add(
                        GameRecord(
                            id=game_id,
                            room_name="Old",
                            scoring_mode="default",
                            hint_mode="none",
                            drawing_seconds=60,
                            total_rounds=1,
                            player_count=1,
                            started_at=now - timedelta(days=400),
                            finished_at=now - timedelta(days=400),
                        )
                    )
                    await session.flush()
                    session.add(
                        GameParticipant(
                            id=generate_uuid(),
                            game_id=game_id,
                            user_id=UUID(guest.id),
                            final_score=0,
                            final_rank=1,
                        )
                    )
                    await session.execute(
                        update(User)
                        .where(User.id == UUID(guest.id))
                        .values(last_active_at=now - timedelta(days=370))
                    )

        result = await purge_stale_anonymous_accounts(factory, now=now, batch_size=10, apply=True)

        assert result.player_accounts == 3, "the played tier gets its share of the batch"
        assert result.unused_accounts == 7
    finally:
        await engine.dispose()


async def test_expired_tokens_are_swept_rather_than_kept_until_a_purge_nobody_ran():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        account = await users.create_anonymous("Forgetful")
        issued_at = datetime.now(timezone.utc) - timedelta(days=2)
        async with factory() as session:
            async with session.begin():
                await issue_token(
                    session,
                    user_id=UUID(account.id),
                    purpose=AuthTokenPurpose.PASSWORD_RESET,
                    now=issued_at,
                )
        assert await _count(factory, AuthToken.token_hash) == 1
        assert await purge_expired_tokens(factory) == 1
        assert await _count(factory, AuthToken.token_hash) == 0
        assert any(sweep.name == "auth_tokens" for sweep in retention.retention_sweeps())
    finally:
        await engine.dispose()


def test_the_budget_comes_from_the_environment_with_safe_fallbacks():
    assert sweep_budget_from_env({}) == SweepBudget()
    assert sweep_budget_from_env(
        {
            "RETENTION_SWEEP_ROW_BUDGET": "200",
            "RETENTION_SWEEP_BATCH_ROWS": "50",
            "RETENTION_SWEEP_SECONDS_BUDGET": "2.5",
        }
    ) == SweepBudget(rows=200, batch=50, seconds=2.5)
    assert sweep_budget_from_env(
        {"RETENTION_SWEEP_ROW_BUDGET": "-1", "RETENTION_SWEEP_BATCH_ROWS": "lots"}
    ) == SweepBudget()
    with pytest.raises(ValueError):
        SweepBudget(rows=0)


async def test_every_scheduled_sweep_runs_to_completion_under_the_budget():
    """The loop hands every sweep its budget, and a sweep that cannot take
    one fails every hour behind the fault isolation that keeps the rest
    running - which is how the retired-list reclaim never ran at all."""
    factory, engine = await create_test_db()
    try:
        health = LoopHealth("retention")
        reports = await run_retention_sweeps(
            factory, budget=SweepBudget(rows=50, batch=10), health=health
        )
        assert [name for name, report in reports.items() if report.get("failed")] == []
        assert health.consecutive_failures == 0
        assert "retired_prompt_lists" in reports
    finally:
        await engine.dispose()


async def test_the_reclaim_sweep_takes_no_more_lists_than_the_budget_has_rows():
    from app.services.prompt_reclaim import reclaim_retired_prompt_lists

    factory, engine = await create_test_db()
    try:
        result = await reclaim_retired_prompt_lists(
            factory, limit=25, budget=SweepBudget(rows=1, batch=1)
        )
        assert result.lists_examined <= 1
    finally:
        await engine.dispose()


def test_every_scheduled_sweep_is_registered_once():
    names = [sweep.name for sweep in retention.retention_sweeps()]
    assert len(names) == len(set(names))
    assert set(names) >= {
        "room_messages",
        "email_outbox",
        "auth_tokens",
        "auth_sessions",
        "data_exports",
        "shutdown_abandonments",
        "auth_rate_limit_buckets",
        "room_code_reservations",
        "runtime_events",
        "bug_report_screenshots",
        "retired_prompt_lists",
        "anonymous_accounts",
    }
