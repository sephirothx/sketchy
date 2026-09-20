"""The room is told which transport the drawing seat is on (R-DRAW-01, #887).

A viewer plays each received batch out over the interval that produced it, so
that the interval reads as a line rather than as steps (#559). While every
client flushed at 80 ms a viewer could assume its own cadence; a cadence of
its own for long-polling ended that, and nothing on the wire says what the
sender batched at. The server does know - it holds the drawer's socket - so it
says, on `turn_started` and on the `sync_game` a late arrival or a rebind
takes.

The *transport*, not the milliseconds it resolves to. The cadences themselves
are tunables an administrator can move while a turn is running, and the notice
that carries them already reaches every client at once; a viewer handed the
resolved number went on pacing at the old one until the next turn began.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from app.game import Phase
from tests.fake_game_history_repo import FakeGameHistoryRepository
from tests.handlers.helpers import build_context, build_room


def payloads(ctx, event: str) -> list[dict]:
    return [call.args[1] for call in ctx.sio.emit.await_args_list if call.args[0] == event]


def a_room(transport: str | None):
    """A room mid-turn, whose drawer's socket is on *transport*."""
    room_manager, room, _ = build_room(
        accounts={"Ann": "user-ann", "Bob": "user-bob", "Cid": "user-cid"}
    )
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    if transport is None:
        ctx.sio.transport = Mock(side_effect=KeyError("gone"))
    else:
        ctx.sio.transport = Mock(return_value=transport)
    return ctx, room


async def test_a_turn_tells_every_seat_the_drawers_transport():
    ctx, room = a_room("polling")

    await ctx.game_flow._start_fresh_game(room, list(room.player_list()))
    room.game.force_prompt_choice()
    ctx.sio.emit.reset_mock()
    await ctx.game_flow._begin_drawing(room)

    told = payloads(ctx, "turn_started")
    assert told, "the turn started"
    assert all(p["drawerTransport"] == "polling" for p in told), told
    # One drawer, one transport: not a lookup per recipient.
    assert ctx.sio.transport.call_count == 1


async def test_a_websocket_drawer_says_so_and_a_drawer_with_no_socket_says_nothing():
    # `None` is a seat between reconnects; the client reads anything that is
    # not "polling" as the baseline, so it needs no answer of its own.
    for transport, expected in (("websocket", "websocket"), (None, None)):
        ctx, room = a_room(transport)
        await ctx.game_flow._start_fresh_game(room, list(room.player_list()))
        room.game.force_prompt_choice()
        ctx.sio.emit.reset_mock()
        await ctx.game_flow._begin_drawing(room)

        told = payloads(ctx, "turn_started")
        assert told and all(p["drawerTransport"] == expected for p in told), (
            transport,
            told,
        )


async def test_a_socket_that_syncs_mid_turn_is_told_it_too():
    """A late arrival and a rebind both land here, and both mount a canvas
    that is about to start receiving the drawer's batches."""
    ctx, room = a_room("polling")
    await ctx.game_flow._start_fresh_game(room, list(room.player_list()))
    game = room.game
    game.force_prompt_choice()
    game.set_phase_deadline(game.drawing_seconds)
    game.phase = Phase.DRAWING
    watcher = next(p for p in room.player_list() if p.id != game.current_drawer)
    ctx.sio.emit = AsyncMock()

    await ctx.game_flow._sync_player_view(watcher.sid, room, watcher)

    [synced] = payloads(ctx, "sync_game")
    assert synced["drawerTransport"] == "polling", synced
