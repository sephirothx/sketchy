import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock

import socketio

from app.identifiers import generate_uuid7
from app.canvas_history import PackedCanvasHistory
from app.handlers import register_all_handlers as register_handlers
from app.game import Game
from app.rooms import DrawingRecapEntry, RoomManager


async def test_explicit_drawer_leave_starts_next_survivor_turn():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, rounds=2)
    drawer = room_manager.add_player(room, "Drawer")
    next_player = room_manager.add_player(room, "Next")
    drawer.sid = "drawer-sid"
    next_player.sid = "next-sid"
    room.state = "playing"
    room.game = Game(turn_order=list(room.players), rounds_total=2)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id})
    sio.leave_room = AsyncMock()
    sio.save_session = AsyncMock()
    sio.emit = AsyncMock()
    leave_room = sio.handlers["/"]["leave_room"]

    await leave_room(drawer.sid)

    assert room.game.current_drawer == next_player.id
    assert room.game.phase.value == "choosing_prompt"
    assert room.game.round_number == 1

    timer = timers.phase_timers.pop(room.id)
    timer.cancel()
    with suppress(asyncio.CancelledError):
        await timer

async def test_starting_new_game_clears_previous_drawing_recap():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    host = room_manager.add_player(room, "Host")
    guest = room_manager.add_player(room, "Guest")
    host.sid = "host-sid"
    guest.sid = "guest-sid"
    room.last_game_drawings.append(
        DrawingRecapEntry(
            turn_id=str(generate_uuid7()),
            round_number=1,
            turn_number=1,
            drawer_id=host.id,
            drawer_nickname=host.nickname,
            drawer_name_color=host.name_color,
            prompt="old",
            action_count=0,
            canvas_history=PackedCanvasHistory().binary_payload(),
        )
    )

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": host.id},
    )
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["start_game"](host.sid)

    assert response == {"ok": True}
    assert room.last_game_drawings == []
    # The game's start is said by its first turn_starting (#880).
    assert any(
        call.args[0] == "turn_starting" and call.args[1].get("gameStarted") is True
        for call in sio.emit.await_args_list
    )
    assert not any(call.args[0] in {"game_started", "canvas_reset"} for call in sio.emit.await_args_list)

    timer = timers.phase_timers.pop(room.id)
    timer.cancel()
    with suppress(asyncio.CancelledError):
        await timer

async def test_schedule_hint_checkpoints_emits_unmasked_word_to_drawer():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid, guesser.sid = "drawer-sid", "guesser-sid"

    room.game = Game(turn_order=[drawer.id, guesser.id], prompt_pool=["banana"], rounds_total=1, hint_mode="checkpoints", drawing_seconds=0.05)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sessions = {
        "drawer-sid": {"room_id": room.id, "player_id": drawer.id},
        "guesser-sid": {"room_id": room.id, "player_id": guesser.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    select_prompt = sio.handlers["/"]["select_prompt"]
    rejected = await select_prompt("drawer-sid", {"prompt": "not-a-choice"})
    assert rejected == {"ok": False, "errorCode": "prompt_unavailable", "error": "That prompt is no longer available"}

    accepted = await select_prompt("drawer-sid", {"prompt": "banana"})
    assert accepted == {"ok": True}
    await asyncio.sleep(0.1)

    drawer_hints = [call for call in sio.emit.await_args_list if call.args[0] == "hint_revealed" and call.kwargs.get("to") == "drawer-sid"]
    guesser_hints = [call for call in sio.emit.await_args_list if call.args[0] == "hint_revealed" and call.kwargs.get("to") == "guesser-sid"]

    assert len(drawer_hints) >= 1
    assert drawer_hints[0].args[1]["maskedPrompt"] == "banana"

    assert len(guesser_hints) >= 1
    assert guesser_hints[0].args[1]["maskedPrompt"] != "banana"

    timer = timers.phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer


# --- a seat released inside a fan-out (#1004) ----------------------------------


def _watch_scheduling(flow):
    scheduled = []
    real = flow.schedule_phase_timer

    def watched(room, seconds):
        scheduled.append((room.game.phase.value if room.game else None, seconds))
        return real(room, seconds)

    flow.schedule_phase_timer = watched
    return scheduled


async def test_a_drawer_released_during_turn_started_leaves_the_next_turn_its_own_timer():
    """Every per-seat emit is an await the game can move through. The seat
    released there abandoned the turn and the nested `_start_turn` armed the
    next turn's choosing timer - which the outer call then replaced with the
    drawing timer it was about to arm: a 15 s choice against a 90-300 s clock
    (#1004)."""
    from unittest.mock import AsyncMock

    from app.flow_timing import timing
    from app.game import Phase
    from tests.fake_game_history_repo import FakeGameHistoryRepository
    from tests.handlers.helpers import build_context, build_room

    room_manager, room, players = build_room(rounds=3, accounts={"Ann": "ua", "Bob": "ub", "Cat": "uc"})
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    sessions = {p.sid: {"room_id": room.id, "player_id": p.id, "user_id": p.user_id} for p in players.values()}
    ctx.sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    ctx.sio.leave_room = AsyncMock()
    flow = ctx.game_flow
    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    drawer = room.players[game.current_drawer]
    first_turn = game.current_turn_id
    released = {"done": False}
    real_emit = ctx.sio.emit

    async def emit(event, *args, **kwargs):
        if event == "turn_started" and not released["done"]:
            released["done"] = True
            await flow.release_seat(drawer.sid, room, drawer)
        return await real_emit(event, *args, **kwargs)

    ctx.sio.emit = emit
    scheduled = _watch_scheduling(flow)
    game.force_prompt_choice()

    await flow._begin_drawing(room)

    assert game.current_turn_id != first_turn and game.phase == Phase.CHOOSING_PROMPT
    assert scheduled == [("choosing_prompt", timing.choose_prompt_seconds)]
    assert game.remaining_seconds() <= timing.choose_prompt_seconds + 1
    assert not ctx.timers.hint_timers.get(room.id)
    await ctx.timers.close()


async def test_a_drawer_released_during_turn_ended_does_not_shorten_the_next_choice():
    from unittest.mock import AsyncMock

    from app.flow_timing import timing
    from app.game import Phase
    from tests.fake_game_history_repo import FakeGameHistoryRepository
    from tests.handlers.helpers import build_context, build_room

    room_manager, room, players = build_room(rounds=3, accounts={"Ann": "ua", "Bob": "ub", "Cat": "uc"})
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    sessions = {p.sid: {"room_id": room.id, "player_id": p.id, "user_id": p.user_id} for p in players.values()}
    ctx.sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    ctx.sio.leave_room = AsyncMock()
    flow = ctx.game_flow
    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    drawer = room.players[game.current_drawer]
    game.force_prompt_choice()
    await flow._begin_drawing(room)
    ctx.timers.cancel_phase_timer(room.id)
    released = {"done": False}
    real_emit = ctx.sio.emit

    async def emit(event, *args, **kwargs):
        if event == "turn_ended" and not released["done"]:
            released["done"] = True
            await flow.release_seat(drawer.sid, room, drawer)
        return await real_emit(event, *args, **kwargs)

    ctx.sio.emit = emit
    scheduled = _watch_scheduling(flow)

    await flow._end_turn(room)

    # Whatever the release did with the results screen, exactly one timer
    # is armed, and it is the one for the phase in play: on main the outer
    # call armed the 5 s results timer over the next turn's 15 s choice.
    assert len(scheduled) == 1, scheduled
    phase, seconds = scheduled[0]
    assert phase == game.phase.value
    assert seconds == (
        timing.choose_prompt_seconds
        if game.phase == Phase.CHOOSING_PROMPT
        else timing.turn_results_seconds
    )
    await ctx.timers.close()
