"""A hung database must not pin the gate a seat is reconciled through.

Seat transitions hold the socket's seating gate, and its disconnect queues at
the same gate so that a socket dropping mid-entry reconciles against a seat
that already exists. An entry that never returns therefore holds the gate for
ever, and a socket that drops during it never reconciles - which is the leak
#480 closed, reopened by a stall.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from app.handlers.rooms import ENTRY_DB_TIMEOUT_SECONDS
from app.rooms import RoomManager
from tests.handlers.helpers import SessionStore


def build_stack(room_manager: RoomManager, **kwargs):
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager, **kwargs)
    sessions = SessionStore()
    sio.get_session = AsyncMock(side_effect=sessions.get)
    sio.save_session = AsyncMock(side_effect=sessions.save)
    sio.enter_room = AsyncMock()
    sio.leave_room = AsyncMock()
    sio.disconnect = AsyncMock()
    sio.emit = AsyncMock()
    return ctx, sio, sessions


def never_answers():
    """A database call that is not slow but stopped."""

    async def hang(*_args, **_kwargs):
        await asyncio.sleep(3600)

    return AsyncMock(side_effect=hang)


@pytest.mark.asyncio
async def test_a_hung_code_allocation_refuses_rather_than_hanging(monkeypatch):
    monkeypatch.setattr("app.handlers.rooms.ENTRY_DB_TIMEOUT_SECONDS", 0.05)
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_codes = SimpleNamespace(
        allocate=never_answers(),
        release_unpublished=AsyncMock(),
        retire_ephemeral=AsyncMock(),
        is_retired=AsyncMock(return_value=False),
    )
    await sessions.save("host-sid", {"user_id": "user-1"})

    answer = await asyncio.wait_for(
        sio.handlers["/"]["create_room"]("host-sid", {"nickname": "Host"}), timeout=5
    )

    assert answer["ok"] is False
    assert "database" in answer["error"]
    assert room_manager.rooms == {}


@pytest.mark.asyncio
async def test_a_socket_that_drops_during_a_stall_is_still_reconciled(monkeypatch):
    """The failure this is really about: the socket drops while the entry is
    stuck, and its disconnect is waiting at the same gate."""
    monkeypatch.setattr("app.handlers.rooms.ENTRY_DB_TIMEOUT_SECONDS", 0.05)
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_codes = SimpleNamespace(
        allocate=never_answers(),
        release_unpublished=AsyncMock(),
        retire_ephemeral=AsyncMock(),
        is_retired=AsyncMock(return_value=False),
    )
    await sessions.save("host-sid", {"user_id": "user-1"})

    entering = asyncio.create_task(
        sio.handlers["/"]["create_room"]("host-sid", {"nickname": "Host"})
    )
    await asyncio.sleep(0)
    dropping = asyncio.create_task(sio.handlers["/"]["disconnect"]("host-sid"))

    # Both finish: the entry gives up, and the disconnect it was blocking runs.
    await asyncio.wait_for(asyncio.gather(entering, dropping), timeout=5)

    assert room_manager.rooms == {}
    await ctx.timers.close()


def test_the_bound_matches_the_one_the_history_write_already_uses():
    """Not a new number: the same ten seconds a finished-game write allows."""
    from app.services.game_flow import HISTORY_WRITE_TIMEOUT_SECONDS

    assert ENTRY_DB_TIMEOUT_SECONDS == HISTORY_WRITE_TIMEOUT_SECONDS


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["join_room", "get_room_preview"])
async def test_a_hung_code_lookup_refuses_rather_than_raising(monkeypatch, command):
    """Both paths that ask whether a code has been retired reach the database,
    and a handler that raises answers nothing at all: the client waits out its
    acknowledgement instead of being told."""
    monkeypatch.setattr("app.handlers.rooms.ENTRY_DB_TIMEOUT_SECONDS", 0.05)
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_codes = SimpleNamespace(
        allocate=AsyncMock(return_value="CODE01"),
        release_unpublished=AsyncMock(),
        retire_ephemeral=AsyncMock(),
        is_retired=never_answers(),
    )
    await sessions.save("visitor-sid", {"user_id": "user-1"})

    answer = await asyncio.wait_for(
        sio.handlers["/"][command]("visitor-sid", {"code": "ABC123"}), timeout=5
    )

    assert answer["ok"] is False
    assert "database" in answer["error"]
