"""The AFK check where it meets the wire: the stamp, the answer, the host.

`tests/test_afk.py` covers the rule and the sweep against a fake clock. These
go through the real command door, because the thing most likely to break is
not the rule - it is a command that stops counting as activity, or a socket
whose stamp outlives it.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import socketio

from app.flow_timing import FlowTiming
from app.handlers import register_all_handlers as register_handlers
from app.rooms import RoomManager
from app.services.afk import AfkWatch


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


TIMING = FlowTiming(afk_inactivity_seconds=300, afk_check_seconds=25)


def build(*, nicknames=("Ann", "Bob")):
    room_manager = RoomManager()
    room = room_manager.create_room(name="Studio", is_public=True)
    players = {}
    for nickname in nicknames:
        player = room_manager.add_player(room, nickname)
        player.sid = f"sid-{nickname.lower()}"
        players[nickname] = player

    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    sessions = {
        p.sid: {"room_id": room.id, "player_id": p.id} for p in players.values()
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.save_session = AsyncMock()
    sio.emit = AsyncMock()
    return sio, ctx, room_manager, room, players


def rewire(ctx, room_manager, sio, clock):
    """Give the watch the test's clock, and the ledger with it."""
    ctx.activity._clock = clock
    watch = AfkWatch(
        sio, room_manager, ctx.activity, ctx.game_flow, timing=TIMING, clock=clock
    )
    ctx.afk_watch = watch
    return watch


@pytest.mark.asyncio
async def test_a_guess_counts_as_activity_and_the_heartbeat_does_not():
    """The whole rule rests on which commands reach the ledger."""
    clock = FakeClock()
    sio, ctx, room_manager, room, players = build()
    rewire(ctx, room_manager, sio, clock)
    ann = players["Ann"]
    ctx.activity.note(ann.sid)

    clock.advance(100)
    await sio.handlers["/"]["session_ping"](ann.sid, None)
    assert ctx.activity.idle_seconds(ann.sid) == 100, "a heartbeat is not a person"

    await sio.handlers["/"]["send_chat"](ann.sid, {"text": "hello"})
    assert ctx.activity.idle_seconds(ann.sid) == 0, "a chat line is"


@pytest.mark.asyncio
async def test_answering_the_check_keeps_the_seat_and_says_nothing_to_the_room():
    """The common answer must not put a `room_state` on the wire per window."""
    clock = FakeClock()
    sio, ctx, room_manager, room, players = build()
    watch = rewire(ctx, room_manager, sio, clock)
    ann = players["Ann"]
    ctx.activity.note(ann.sid)
    ctx.activity.note(players["Bob"].sid)

    clock.advance(300)
    await watch.flush()
    asked = {c.kwargs["to"] for c in sio.emit.await_args_list if c.args[0] == "afk_check"}
    assert ann.sid in asked

    sio.emit.reset_mock()
    result = await sio.handlers["/"]["toggle_afk"](ann.sid, {"afk": False})

    assert result == {"ok": True, "isAfk": False}
    assert not any(c.args[0] == "room_state" for c in sio.emit.await_args_list), (
        "an unchanged flag is not news"
    )

    # Bob never answered, so he is marked; Ann, who did, is not. That
    # contrast is the whole test.
    clock.advance(30)
    await watch.flush()
    assert not ann.is_afk
    assert players["Bob"].is_afk
    assert watch.open_checks == 0


@pytest.mark.asyncio
async def test_an_unanswered_check_marks_the_seat_and_tells_the_room():
    clock = FakeClock()
    sio, ctx, room_manager, room, players = build()
    watch = rewire(ctx, room_manager, sio, clock)
    ann = players["Ann"]
    for player in players.values():
        ctx.activity.note(player.sid)

    clock.advance(300)
    await watch.flush()
    sio.emit.reset_mock()
    clock.advance(25)
    await watch.flush()

    assert ann.is_afk
    assert any(c.args[0] == "room_state" for c in sio.emit.await_args_list)


@pytest.mark.asyncio
async def test_a_disconnect_takes_the_stamp_and_the_open_check_with_it():
    """A stamp that outlived its socket would mark whoever inherits the id."""
    clock = FakeClock()
    sio, ctx, room_manager, room, players = build()
    watch = rewire(ctx, room_manager, sio, clock)
    ann = players["Ann"]
    ctx.activity.note(ann.sid)
    clock.advance(300)
    await watch.flush()
    assert watch.open_checks == 1

    await sio.handlers["/"]["disconnect"](ann.sid)

    assert ctx.activity.idle_seconds(ann.sid) == 0.0, "forgotten, not ancient"
    assert watch.open_checks == 0


# --------------------------------------------------------------------------
# The host
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unanswered_check_passes_the_host_role_on():
    """`start_game` is host-only, so an absent host is a room nobody can start."""
    clock = FakeClock()
    sio, ctx, room_manager, room, players = build()
    watch = rewire(ctx, room_manager, sio, clock)
    ann, bob = players["Ann"], players["Bob"]
    assert ann.is_host and not bob.is_host

    for player in players.values():
        ctx.activity.note(player.sid)
    clock.advance(300)
    await watch.flush()
    ctx.activity.note(bob.sid)
    clock.advance(25)
    await watch.flush()

    assert ann.is_afk
    assert not ann.is_host and bob.is_host


@pytest.mark.asyncio
async def test_setting_afk_on_yourself_keeps_the_room():
    """Only the automatic path moves the role: a self-toggle is reversible."""
    _, ctx, _, room, players = build()
    ann = players["Ann"]

    await ctx.sio.handlers["/"]["toggle_afk"](ann.sid, {"afk": True})

    assert ann.is_afk and ann.is_host
    assert not players["Bob"].is_host


@pytest.mark.asyncio
async def test_a_host_alone_with_a_spectator_keeps_the_role():
    """A spectator can neither start a game nor be asked to give it back."""
    clock = FakeClock()
    sio, ctx, room_manager, room, players = build(nicknames=("Ann",))
    watch = rewire(ctx, room_manager, sio, clock)
    watcher = room_manager.add_player(room, "Cam", is_spectator=True)
    watcher.sid = "sid-cam"
    ann = players["Ann"]
    ctx.activity.note(ann.sid)

    clock.advance(300)
    await watch.flush()
    clock.advance(25)
    await watch.flush()

    assert ann.is_afk
    assert ann.is_host and not watcher.is_host


@pytest.mark.asyncio
async def test_the_role_never_lands_back_on_the_seat_it_was_taken_from():
    """The seat being released is not a candidate to inherit from itself.

    With every other seat disconnected there is no active successor, and the
    fallback is "longest seated". Without excluding the seat being released,
    that fallback is the absent host, the role is handed back to them, and the
    room is left exactly as stuck as before with a `True` saying it moved.
    """
    clock = FakeClock()
    sio, ctx, room_manager, room, players = build()
    watch = rewire(ctx, room_manager, sio, clock)
    ann, bob = players["Ann"], players["Bob"]
    bob.connected = False

    ctx.activity.note(ann.sid)
    clock.advance(300)
    await watch.flush()
    clock.advance(25)
    await watch.flush()

    assert ann.is_afk
    assert not ann.is_host, "the absent host cannot inherit from themselves"
    assert bob.is_host


@pytest.mark.asyncio
async def test_the_role_goes_to_somebody_who_can_answer():
    """Handing a stuck room to another absent seat changes nothing about it."""
    clock = FakeClock()
    sio, ctx, room_manager, room, players = build(nicknames=("Ann", "Bob", "Cid"))
    watch = rewire(ctx, room_manager, sio, clock)
    ann, bob, cid = players["Ann"], players["Bob"], players["Cid"]
    bob.connected = False

    for player in players.values():
        ctx.activity.note(player.sid)
    clock.advance(300)
    await watch.flush()
    ctx.activity.note(cid.sid)
    clock.advance(25)
    await watch.flush()

    assert ann.is_afk and not ann.is_host
    assert cid.is_host and not bob.is_host
