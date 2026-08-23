"""Socket boundaries stop admitting room/game work during a deploy drain."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import socketio

from app.game import Game
from app.handlers import register_all_handlers as register_handlers
from app.handlers import restart
from app.rooms import RestartVote, RoomManager


class DrainingShutdown:
    is_draining = True

    def __init__(self):
        self.notified = False

    def notify_game_state_changed(self):
        self.notified = True

    @staticmethod
    def rejection_acknowledgement():
        return {
            "ok": False,
            "error": "Server update in progress; try again shortly",
            "serverDraining": True,
        }

    @staticmethod
    def notice_payload():
        return {
            "contractVersion": 1,
            "reason": "deployment",
            "drainSeconds": 30,
            "startedAt": "2026-08-23T12:00:00+00:00",
        }


@pytest.mark.asyncio
async def test_create_room_and_game_start_are_rejected_without_mutation():
    rooms = RoomManager()
    room = rooms.create_room(name="Existing", is_public=True)
    host = rooms.add_player(room, "Host")
    guest = rooms.add_player(room, "Guest")
    host.sid, guest.sid = "host", "guest"
    sio = socketio.AsyncServer(async_mode="asgi")
    shutdown = DrainingShutdown()
    register_handlers(sio, rooms, shutdown=shutdown)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": host.id}
    )

    create = await sio.handlers["/"]["create_room"](
        "new-sid", {"nickname": "NewHost"}
    )
    start = await sio.handlers["/"]["start_game"]("host")

    assert create["serverDraining"] is True
    assert start == create
    assert list(rooms.rooms) == [room.id]
    assert room.game is None
    assert room.state == "waiting"


@pytest.mark.asyncio
async def test_new_connection_receives_current_versioned_shutdown_notice():
    rooms = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    shutdown = DrainingShutdown()
    register_handlers(sio, rooms, shutdown=shutdown)
    sio.save_session = AsyncMock()
    sio.emit = AsyncMock()

    await sio.handlers["/"]["connect"]("sid", {}, None)

    sio.emit.assert_awaited_once_with(
        "server_shutdown", shutdown.notice_payload(), to="sid"
    )


@pytest.mark.asyncio
async def test_an_approved_restart_is_cancelled_once_the_drain_starts(monkeypatch):
    """The vote passed before the drain, so the room is told, not restarted."""

    monkeypatch.setattr(restart, "RESTART_DELAY_SECONDS", 0)
    rooms = RoomManager()
    room = rooms.create_room(name="Live", is_public=True)
    host = rooms.add_player(room, "Host")
    guest = rooms.add_player(room, "Guest")
    host.sid, guest.sid = "host", "guest"
    room.state = "playing"
    room.game = Game(turn_order=[host.id, guest.id])
    sio = socketio.AsyncServer(async_mode="asgi")
    sio.emit = AsyncMock()
    shutdown = DrainingShutdown()
    ctx = register_handlers(sio, rooms, shutdown=shutdown)
    vote = RestartVote(
        proposer_id=host.id,
        proposer_nickname="Host",
        eligible_voter_ids=(host.id, guest.id),
        votes={host.id: True, guest.id: True},
        expires_at=time.time() + 20,
        status="approved",
    )
    room.restart_vote = vote

    restart._schedule_restart(ctx, room, vote)
    await ctx.timers.restart_timers[room.id]

    assert room.game is None
    assert room.state == "waiting"
    assert room.restart_vote is None
    assert room.restart_vote_cooldown_until > time.time()
    # The drain waits on live games, so it has to hear that this one ended.
    assert shutdown.notified is True


@pytest.mark.asyncio
async def test_a_persistent_room_is_not_materialized_during_a_drain():
    """Opening a durable room is new live work, so the drain refuses it."""

    rooms = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    shutdown = DrainingShutdown()
    ctx = register_handlers(sio, rooms, shutdown=shutdown)
    ctx.persistent_rooms = SimpleNamespace(materialize=AsyncMock())

    preview = await sio.handlers["/"]["get_room_preview"]("sid", {"code": "ABC123"})
    join = await sio.handlers["/"]["join_room"](
        "sid", {"code": "ABC123", "nickname": "Guest"}
    )

    assert preview["serverDraining"] is True
    assert join["serverDraining"] is True
    ctx.persistent_rooms.materialize.assert_not_awaited()
    assert rooms.rooms == {}
