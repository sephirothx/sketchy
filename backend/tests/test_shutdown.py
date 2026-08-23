"""Planned deploys drain finished games and record only deadline leftovers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, GameRecord, PlannedShutdownAbandonment
from app.game import Game
from app.rooms import RoomManager
from app.services.shutdown import (
    ABANDONMENT_RETENTION,
    ShutdownCoordinator,
    purge_expired_shutdown_abandonments,
)


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    rooms = RoomManager()
    coordinator = ShutdownCoordinator(factory, rooms)
    yield factory, rooms, coordinator
    await engine.dispose()


def live_game(rooms: RoomManager):
    room = rooms.create_room(name="Sensitive room name", is_public=False)
    host = rooms.add_player(room, "Private player one")
    other = rooms.add_player(room, "Private player two")
    spectator = rooms.add_player(room, "Private spectator", is_spectator=True)
    host.sid, other.sid, spectator.sid = "host", "other", "spectator"
    room.state = "playing"
    room.game = Game(turn_order=[host.id, other.id])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    return room, room.game


async def test_zero_deadline_records_privacy_safe_abandonment_not_partial_history(env):
    factory, rooms, coordinator = env
    room, game = live_game(rooms)
    sio = AsyncMock()
    coordinator.begin_startup(drain_seconds=0)
    coordinator.mark_ready()

    result = await coordinator.begin_shutdown(sio)

    assert result.abandoned_game_count == 1
    assert result.drained_game_count == 0
    assert result.timed_out is True
    assert coordinator.state == "stopped"
    sio.emit.assert_awaited_once()
    event, payload = sio.emit.await_args.args
    assert event == "server_shutdown"
    assert payload == {
        "contractVersion": 1,
        "reason": "deployment",
        "drainSeconds": 0,
        "startedAt": payload["startedAt"],
    }

    async with factory() as session:
        row = await session.scalar(select(PlannedShutdownAbandonment))
        assert row is not None
        assert str(row.game_id) == game.id
        assert str(row.room_instance_id) == room.retention_scope_id
        assert row.reason == "drain_timeout"
        assert row.phase == "choosing_prompt"
        assert row.round_number == 1
        assert row.completed_turn_count == 0
        assert row.seated_player_count == 2
        assert row.connected_player_count == 2
        assert row.spectator_count == 1
        assert row.canvas_action_count == 0
        assert await session.scalar(select(func.count(GameRecord.id))) == 0
        serialized = " ".join(str(value) for value in row.__dict__.values())
        assert "Sensitive room name" not in serialized
        assert "Private player" not in serialized


async def test_game_that_finishes_inside_window_is_not_abandoned(env):
    factory, rooms, coordinator = env
    room, _ = live_game(rooms)
    coordinator.begin_startup(drain_seconds=1)
    coordinator.mark_ready()
    sio = AsyncMock()

    draining = asyncio.create_task(coordinator.begin_shutdown(sio))
    while not coordinator.is_draining:  # noqa: ASYNC110 - spin until the
        await asyncio.sleep(0)  # drain task reaches its first await
    room.state = "waiting"
    room.game = None
    coordinator.notify_game_state_changed()
    result = await draining

    assert result.drained_game_count == 1
    assert result.abandoned_game_count == 0
    assert result.timed_out is False
    async with factory() as session:
        assert await session.scalar(
            select(func.count(PlannedShutdownAbandonment.id))
        ) == 0


async def test_abandonment_retention_is_ninety_days(env):
    factory, rooms, coordinator = env
    _, game = live_game(rooms)
    coordinator.begin_startup(drain_seconds=0)
    coordinator.mark_ready()
    await coordinator.begin_shutdown(AsyncMock())
    now = datetime.now(timezone.utc)
    async with factory() as session:
        async with session.begin():
            row = await session.scalar(select(PlannedShutdownAbandonment))
            assert row is not None and str(row.game_id) == game.id
            row.observed_at = now - ABANDONMENT_RETENTION - timedelta(seconds=1)

    assert await purge_expired_shutdown_abandonments(factory, now=now) == 1
    async with factory() as session:
        assert await session.scalar(select(PlannedShutdownAbandonment.id)) is None


async def test_a_forced_exit_cuts_the_drain_short(env):
    """A second termination signal must not wait out the configured window."""

    factory, rooms, coordinator = env
    live_game(rooms)
    coordinator.begin_startup(drain_seconds=300)
    coordinator.mark_ready()

    result = await asyncio.wait_for(
        coordinator.begin_shutdown(AsyncMock(), should_abort=lambda: True),
        timeout=5,
    )

    assert result.aborted is True
    assert result.timed_out is False
    assert result.abandoned_game_count == 1
    assert coordinator.state == "stopped"
    async with factory() as session:
        # Diagnostics are skipped on a forced exit; the operator asked to leave.
        assert await session.scalar(
            select(func.count(PlannedShutdownAbandonment.id))
        ) == 0


async def test_an_existing_abandonment_fact_is_not_duplicated(env, caplog):
    """The runtime game ID is the idempotency key for the diagnostic row."""

    factory, rooms, coordinator = env
    room, game = live_game(rooms)
    from uuid import UUID

    async with factory() as session:
        async with session.begin():
            session.add(
                PlannedShutdownAbandonment(
                    game_id=UUID(game.id),
                    room_instance_id=UUID(room.retention_scope_id),
                    reason="drain_timeout",
                    phase="drawing",
                    round_number=1,
                    completed_turn_count=0,
                    seated_player_count=2,
                    connected_player_count=2,
                    spectator_count=1,
                    canvas_action_count=0,
                    game_started_at=game.started_at,
                    observed_at=datetime.now(timezone.utc),
                )
            )

    coordinator.begin_startup(drain_seconds=0)
    coordinator.mark_ready()
    with caplog.at_level(logging.ERROR, logger="sketchy.shutdown"):
        result = await coordinator.begin_shutdown(AsyncMock())

    # A duplicate insert would be swallowed by the bounded-shutdown guard, so
    # the absence of that error is what proves the row was skipped on purpose.
    assert caplog.records == []
    assert result.abandoned_game_count == 1
    async with factory() as session:
        assert await session.scalar(
            select(func.count(PlannedShutdownAbandonment.id))
        ) == 1
        row = await session.scalar(select(PlannedShutdownAbandonment))
        assert row.phase == "drawing"
