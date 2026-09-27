import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest
import socketio

from app.identifiers import generate_uuid7
from app.canvas_history import PackedCanvasHistory
from app.handlers import register_all_handlers as register_handlers
from app.game import Game, Phase
from app.rooms import DrawingRecapEntry, RoomManager


async def test_explicit_drawer_leave_starts_next_survivor_turn():
    # Three seats: with two, the drawer leaving ends the game (#1005).
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, rounds=2)
    drawer = room_manager.add_player(room, "Drawer")
    next_player = room_manager.add_player(room, "Next")
    third = room_manager.add_player(room, "Third")
    drawer.sid = "drawer-sid"
    next_player.sid = "next-sid"
    third.sid = "third-sid"
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
    # One prompt in the pool, so one offer: the third position is not there.
    rejected = await select_prompt("drawer-sid", {"index": 2})
    assert rejected == {"ok": False, "errorCode": "prompt_unavailable", "error": "That prompt is no longer available"}

    # A position is valid in every turn's offers, so a pick naming an older
    # turn is refused rather than taken among offers the drawer never saw.
    stale = await select_prompt("drawer-sid", {"index": 0, "turnId": "an-earlier-turn"})
    assert stale == {"ok": False, "errorCode": "prompt_unavailable", "error": "That prompt is no longer available"}
    assert room.game.prompt is None

    accepted = await select_prompt(
        "drawer-sid", {"index": 0, "turnId": room.game.current_turn_id}
    )
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


# --- too few to go on (#1005) ------------------------------------------------


async def test_a_turn_nobody_can_guess_ends_at_once():
    """Eligibility is frozen when drawing begins; with every other seat AFK
    the drawer used to draw the full clock to an empty room (#1005)."""
    from tests.fake_game_history_repo import FakeGameHistoryRepository
    from tests.handlers.helpers import build_context, build_room

    room_manager, room, players = build_room(rounds=2, accounts={"Ann": "ua", "Bob": "ub", "Cat": "uc"})
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    flow = ctx.game_flow
    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    for player in players.values():
        if player.id != game.current_drawer:
            player.is_afk = True
    game.force_prompt_choice()

    await flow._begin_drawing(room)

    events = [call.args[0] for call in ctx.sio.emit.await_args_list]
    assert "turn_started" not in events
    assert "turn_ended" in events
    assert len(game.completed_turns) == 1
    assert game.completed_turns[0].end_reason == "timeout"
    # Read off the drawing deadline, not the choosing one: a turn that lasted
    # nothing is not most of a drawing phase, and the record refuses zero.
    assert 0 < game.completed_turns[0].duration_seconds < 1
    await ctx.timers.close()


async def test_a_seat_going_afk_that_leaves_one_active_player_ends_the_game():
    """The minimum counts active seats, as the start does: a two-player game
    whose guesser goes AFK is a game one person is playing (#1005)."""
    from tests.fake_game_history_repo import FakeGameHistoryRepository
    from tests.handlers.helpers import build_context, build_room

    room_manager, room, players = build_room(rounds=3)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    flow = ctx.game_flow
    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    game.force_prompt_choice()
    await flow._begin_drawing(room)
    guesser = next(p for p in players.values() if p.id != game.current_drawer)

    guesser.is_afk = True
    await flow.apply_afk_consequences(room, guesser)

    assert room.game is None and room.state == "waiting"
    await ctx.timers.close()


async def test_a_game_ends_as_abandoned_when_fewer_than_two_remain():
    """A two-player game whose opponent left used to go on: the survivor
    drew every remaining turn to nobody (#1005)."""
    from app.announcements import Announcement
    from tests.fake_game_history_repo import FakeGameHistoryRepository
    from tests.handlers.helpers import build_context, build_room, replay_staged

    room_manager, room, players = build_room(rounds=3)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    flow = ctx.game_flow
    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    game.force_prompt_choice()
    await flow._begin_drawing(room)
    leaver = next(p for p in players.values() if p.id != game.current_drawer)

    room_manager.remove_player(room, leaver.id)
    await flow._remove_player_from_game(room, leaver.id)

    assert room.game is None and room.state == "waiting"
    said = [call.args[1] for call in ctx.sio.emit.await_args_list if call.args[0] == "chat_message"]
    assert any(line.get("code") == Announcement.GAME_ENDED_TOO_FEW_PLAYERS.value for line in said), said
    await ctx.timers.close()
    await replay_staged(ctx)
    [saved] = history.saved
    assert saved.record.id == game.id and saved.record.outcome == "abandoned"


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
    drawing timer it was about to arm: a 15 s choice (R-GAME-01) against a
    90-300 s clock (#1004). And the seats not yet reached were still told the
    departed drawer's turn had started."""
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
    stale = [
        call for call in real_emit.await_args_list
        if call.args[0] == "turn_started" and call.args[1]["turnId"] == first_turn
    ]
    assert len(stale) == 1, "only the seat reached before the release heard the old turn"
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


@pytest.mark.parametrize(
    "payload",
    [{"index": True}, {"index": "0"}, {"index": 0.0}, {"index": -1}, {"index": 3},
     {"prompt": "banana"}, {"index": 0, "prompt": "banana"}, {}],
)
async def test_a_pick_is_a_plain_position_and_nothing_else(payload):
    """Strict: a boolean, a string or a float is not a position, and the text
    the pick used to be is refused rather than ignored."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid, guesser.sid = "drawer-sid", "guesser-sid"
    room.game = Game(turn_order=[drawer.id, guesser.id], prompt_pool=["banana"], rounds_total=1)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": drawer.id})
    sio.emit = AsyncMock()

    response = await sio.handlers["/"]["select_prompt"]("drawer-sid", payload)

    assert response["ok"] is False
    assert response["errorCode"] == "invalid_payload"
    assert room.game.phase == Phase.CHOOSING_PROMPT
