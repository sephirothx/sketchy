"""A command's log lines name the socket, the command, and the one invocation."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import socketio

from app import correlation
from app.handlers import register_all_handlers as register_handlers
from app.rooms import RoomManager


pytestmark = pytest.mark.asyncio


async def test_a_handler_runs_inside_its_own_correlation_context():
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, RoomManager())
    sio.emit = AsyncMock()
    seen: list[dict[str, str]] = []

    async def probe(sid, *args):
        await asyncio.sleep(0)
        seen.append(correlation.current())
        return {"ok": True}

    ctx.on("probe", probe)
    await sio.handlers["/"]["probe"]("sock-1", {})
    await sio.handlers["/"]["probe"]("sock-2", {})

    assert [entry["sid"] for entry in seen] == ["sock-1", "sock-2"]
    assert {entry["event"] for entry in seen} == {"probe"}
    ids = [entry["request_id"] for entry in seen]
    assert len(set(ids)) == 2
    assert all(str(UUID(rid)) == rid for rid in ids)


async def test_two_commands_in_flight_do_not_see_each_other():
    """The server runs handlers as separate tasks; the context must be too."""
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, RoomManager())
    sio.emit = AsyncMock()
    started = asyncio.Event()
    release = asyncio.Event()
    seen: dict[str, str | None] = {}

    async def slow(sid, *args):
        started.set()
        await release.wait()
        seen["slow"] = correlation.socket_sid.get()
        return {"ok": True}

    async def quick(sid, *args):
        seen["quick"] = correlation.socket_sid.get()
        return {"ok": True}

    ctx.on("slow", slow)
    ctx.on("quick", quick)
    task = asyncio.create_task(sio.handlers["/"]["slow"]("slow-sock", {}))
    await started.wait()
    await sio.handlers["/"]["quick"]("quick-sock", {})
    release.set()
    await task
    assert seen == {"slow": "slow-sock", "quick": "quick-sock"}
