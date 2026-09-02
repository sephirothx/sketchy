"""Every client command timed and counted at the one door they all use."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import socketio
from socketio.exceptions import ConnectionRefusedError

from app.handlers import context as context_module
from app.handlers import register_all_handlers as register_handlers
from app.handlers.budgets import CommandBudgetPolicy, CommandBudgets
from app.rooms import RoomManager
from app.services.telemetry import Telemetry
from tests.handlers.helpers import SessionStore


pytestmark = pytest.mark.asyncio


@pytest.fixture
def env(monkeypatch):
    store = Telemetry()
    monkeypatch.setattr(context_module, "telemetry", store)
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    sessions = SessionStore()
    sio.get_session = AsyncMock(side_effect=sessions.get)
    sio.save_session = AsyncMock(side_effect=sessions.save)
    sio.enter_room = AsyncMock()
    sio.leave_room = AsyncMock()
    sio.disconnect = AsyncMock()
    sio.emit = AsyncMock()
    return ctx, sio, sessions, store


async def test_a_command_that_succeeds_is_timed_under_ok(env):
    ctx, sio, sessions, store = env
    await sessions.save("host", {"user_id": "user-host"})
    created = await sio.handlers["/"]["create_room"]("host", {"nickname": "Host"})
    assert created["ok"] is True
    assert store.socket_events.get(("create_room", "ok")) == 1
    assert store.socket_duration.count() == 1


async def test_a_refusal_the_handler_chose_is_its_own_outcome(env):
    ctx, sio, sessions, store = env
    # No seat, no room: the handler answers `ok: False` rather than raising.
    answer = await sio.handlers["/"]["start_game"]("nobody", {})
    assert isinstance(answer, dict) and answer["ok"] is False
    assert store.socket_events.get(("start_game", "refused")) == 1
    assert store.socket_events.get(("start_game", "error")) == 0


async def test_a_handler_that_raises_is_counted_before_the_exception_escapes(env):
    ctx, sio, sessions, store = env

    async def explode(sid, *args):
        raise RuntimeError("bug")

    ctx.on("explode", explode)
    with pytest.raises(RuntimeError):
        await sio.handlers["/"]["explode"]("someone", {})
    assert store.socket_events.get(("explode", "error")) == 1
    assert store.socket_duration.count() == 1


async def test_a_throttled_command_is_counted_without_a_duration(env, monkeypatch):
    ctx, sio, sessions, store = env
    policy = CommandBudgetPolicy()
    monkeypatch.setattr(ctx, "command_budgets", policy)
    monkeypatch.setattr(ctx, "_command_windows", CommandBudgets())
    budget = policy.for_command("guess")
    answered = 0
    for _ in range(budget.limit + 5):
        answer = await sio.handlers["/"]["guess"]("flooder", {"text": "x"})
        if answer and "quickly" in answer.get("error", ""):
            answered += 1
    assert answered >= 1
    throttled = store.socket_events.get(("guess", "throttled"))
    assert throttled == answered
    # Refused before any handler ran, so nothing to time.
    assert store.socket_duration.count() == budget.limit


async def test_handshakes_are_counted_by_how_they_ended(env, monkeypatch):
    ctx, sio, sessions, store = env
    from app.handlers import connection as connection_module

    monkeypatch.setattr(connection_module, "telemetry", store)
    connect = sio.handlers["/"]["connect"]

    await connect("s1", {}, None)
    assert store.socket_connections.get(("accepted",)) == 1

    monkeypatch.setattr(ctx.room_capacity, "sockets", 1)
    await connect("s2", {}, None)
    assert store.socket_connections.get(("full",)) == 1

    async def refuse(*_args, **_kwargs):
        raise ConnectionRefusedError("suspended")

    # A refusal raised out of the body still reaches the ledger.
    monkeypatch.setattr(ctx.room_capacity, "sockets", 100)
    monkeypatch.setattr(ctx.sio, "save_session", AsyncMock(side_effect=refuse))
    with pytest.raises(ConnectionRefusedError):
        await connect("s3", {}, None)
    assert store.socket_connections.get(("refused",)) == 1
