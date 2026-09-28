"""An undo is a drawing action, and drawing ends with the turn (#1283).

`undo_stroke` checked that its sender was the drawer and not that anybody was
still drawing. The drawer stays the drawer through the results, and the
turn's recap is captured the moment drawing ends - so a delayed or modified
client's undo after that boundary changed the live canvas and left the saved
drawing as it was.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import socketio

from app.game import Game, Phase
from app.handlers import register_all_handlers as register_handlers
from app.live_drawing import encode_live_drawing
from app.refusals import ErrorCode
from app.rooms import RoomManager

from tests.handlers.helpers import canvas_action


async def drawing_room():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    drawer.sid = "drawer-sid"
    guesser = room_manager.add_player(room, "Guesser")
    guesser.sid = "guesser-sid"
    room.state = "playing"
    room.game = Game(turn_order=[drawer.id, guesser.id], prompt_pool=["panda", "otter"])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()
    room.game.set_phase_deadline(room.game.drawing_seconds)
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id})
    sio.emit = AsyncMock()
    draw = sio.handlers["/"]["draw"]
    await draw(
        "drawer-sid",
        encode_live_drawing("draw_start", {"x": 0.1, "y": 0.1, "color": "#000000", "width": 4}),
        canvas_action(room.game, 1),
    )
    await draw("drawer-sid", encode_live_drawing("draw_end"))
    assert len(room.game.canvas.history) == 1
    return room, sio, ctx


def undo_request(canvas, sequence):
    return [canvas.generation, sequence, canvas.revision, canvas.hash]


def canvas_state(canvas):
    return (len(canvas.history), canvas.revision, canvas.sequence, canvas.hash)


def undo_events(sio):
    return [call for call in sio.emit.await_args_list if call.args and call.args[0] == "canvas_undo"]


async def test_an_undo_after_the_turn_ended_changes_neither_the_canvas_nor_its_recap():
    room, sio, ctx = await drawing_room()
    try:
        # The real ending: scores, the results screen, and the recap taken.
        assert await ctx.game_flow.end_turn_now(room)
        assert room.game.phase == Phase.TURN_RESULTS
        canvas = room.game.canvas
        before = canvas_state(canvas)
        recap = room.last_game_drawings[-1]
        assert recap.canvas_history == canvas.sync_payload()

        # Correctly sequenced, against the right revision and hash: only
        # the phase is wrong.
        answer = await sio.handlers["/"]["undo_stroke"]("drawer-sid", undo_request(canvas, canvas.sequence + 1))

        assert answer == {"ok": False, "errorCode": ErrorCode.DRAWER_ONLY, "error": "The drawing has ended"}
        assert canvas_state(canvas) == before
        assert recap.canvas_history == canvas.sync_payload()
        assert undo_events(sio) == []
    finally:
        await ctx.timers.close()


async def test_an_undo_after_the_game_ended_is_refused_too():
    room, sio, ctx = await drawing_room()
    try:
        room.game.phase = Phase.GAME_END
        before = canvas_state(room.game.canvas)
        answer = await sio.handlers["/"]["undo_stroke"](
            "drawer-sid", undo_request(room.game.canvas, room.game.canvas.sequence + 1)
        )
        assert answer["ok"] is False and answer["errorCode"] == ErrorCode.DRAWER_ONLY
        assert canvas_state(room.game.canvas) == before
    finally:
        await ctx.timers.close()


async def test_a_retried_undo_made_while_drawing_is_still_answered_after_it():
    room, sio, ctx = await drawing_room()
    try:
        undo = sio.handlers["/"]["undo_stroke"]
        canvas = room.game.canvas
        request = undo_request(canvas, canvas.sequence + 1)
        assert await undo("drawer-sid", request) == {"ok": True}
        assert len(canvas.history) == 0

        assert await ctx.game_flow.end_turn_now(room)
        after = canvas_state(canvas)
        # The same undo again, its acknowledgement lost: answered as it was,
        # and nothing moves.
        assert await undo("drawer-sid", request) == {"ok": True}
        assert canvas_state(canvas) == after
        assert room.last_game_drawings[-1].canvas_history == canvas.sync_payload()
    finally:
        await ctx.timers.close()


async def test_a_stale_generation_is_still_named_as_such():
    room, sio, ctx = await drawing_room()
    try:
        request = undo_request(room.game.canvas, room.game.canvas.sequence + 1)
        request[0] += 1
        answer = await sio.handlers["/"]["undo_stroke"]("drawer-sid", request)
        assert answer["errorCode"] == ErrorCode.CANVAS_STALE_GENERATION
        assert len(room.game.canvas.history) == 1
    finally:
        await ctx.timers.close()


async def test_a_turns_recap_entry_says_whether_its_drawer_was_a_guest():
    """The recap credits a guest drawer in the guest style, as every other
    place names a guest (#1279); it printed the bare name, upright, in a
    colour a guest never chose."""
    room, sio, ctx = await drawing_room()
    try:
        drawer = room.players[room.game.current_drawer]
        assert drawer.is_anonymous
        assert await ctx.game_flow.end_turn_now(room)
        assert room.last_game_drawings[-1].drawer_is_anonymous is True
        assert room.last_game_drawings[-1].metadata(0)["drawerIsAnonymous"] is True
    finally:
        await ctx.timers.close()
