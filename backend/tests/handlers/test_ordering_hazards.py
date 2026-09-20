"""Three orderings a client can be caught by (#883).

Each is a gap between a room changing and the room being told, and each shows
up as the client holding two facts that were never true together: a kicked
seat handed the next turn, a turn whose player list still holds the player
who left it, a prompt re-masked after it was revealed. None is frequent;
all three are cheap to close and hard to find once a room is busy.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from app.game import Phase
from tests.fake_game_history_repo import FakeGameHistoryRepository
from tests.handlers.helpers import build_context, build_room


def calls(ctx, event: str) -> list:
    return [call for call in ctx.sio.emit.await_args_list if call.args[0] == event]


async def start_a_turn(ctx, room, players):
    """A game in its drawing phase, with a prompt and a live turn."""
    await ctx.game_flow._start_fresh_game(room, list(room.player_list()))
    game = room.game
    game.force_prompt_choice()
    game.snapshot_turn_participants(
        {p.id: "eligible" for p in room.player_list() if p.id != game.current_drawer}
    )
    game.set_phase_deadline(game.drawing_seconds)
    game.phase = Phase.DRAWING
    return game


async def test_a_kicked_seat_leaves_the_room_before_the_game_moves_on():
    """It used to be told it was out and then handed the next turn: the socket
    was still in the room while the removal's consequences were broadcast."""
    room_manager, room, players = build_room(
        rounds=2, accounts={"Ann": "user-ann", "Bob": "user-bob", "Cid": "user-cid"}
    )
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    game = await start_a_turn(ctx, room, players)
    drawer = next(p for p in room.player_list() if p.id == game.current_drawer)
    ctx.sio.leave_room = AsyncMock()
    order: list[str] = []
    ctx.sio.leave_room.side_effect = lambda sid, room_id: order.append(f"left:{sid}")
    real_emit = ctx.sio.emit.side_effect

    async def note(event, *args, **kwargs):
        if kwargs.get("room") == room.id:
            order.append(f"emit:{event}")
        if real_emit is not None:
            return await real_emit(event, *args, **kwargs)

    ctx.sio.emit.side_effect = note

    await ctx.evict_player(room, drawer.id, notice=("kicked", {"reason": "votes"}))

    assert f"left:{drawer.sid}" in order, "the kicked socket never left the room"
    broadcasts = [i for i, step in enumerate(order) if step.startswith("emit:")]
    assert broadcasts, "the removal was broadcast to the room"
    assert order.index(f"left:{drawer.sid}") < broadcasts[0], order


async def test_the_roster_is_sent_before_the_turn_the_leaver_caused():
    """Losing the drawer starts the next turn. The player list has to be told
    first, or the client holds a turn whose roster still has the leaver."""
    room_manager, room, players = build_room(
        rounds=2, accounts={"Ann": "user-ann", "Bob": "user-bob", "Cid": "user-cid"}
    )
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    game = await start_a_turn(ctx, room, players)
    drawer = next(p for p in room.player_list() if p.id == game.current_drawer)
    ctx.sio.emit.reset_mock()

    await ctx.game_flow.release_seat(drawer.sid, room, drawer)

    events = [call.args[0] for call in ctx.sio.emit.await_args_list]
    assert "turn_starting" in events, "the turn moved on"
    without_the_leaver = next(
        index
        for index, call in enumerate(ctx.sio.emit.await_args_list)
        if call.args[0] == "room_state"
        and drawer.id not in [player["playerId"] for player in call.args[1]["players"]]
    )
    assert without_the_leaver < events.index("turn_starting"), events


async def test_a_timed_hint_is_dropped_when_the_turn_ends_between_two_seats():
    """The loop checked the phase once and then awaited per seat. A turn that
    ended in one of those gaps re-masked the prompt it had just revealed."""
    room_manager, room, players = build_room(
        accounts={"Ann": "user-ann", "Bob": "user-bob", "Cid": "user-cid"}
    )
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    game = await start_a_turn(ctx, room, players)
    game.drawing_seconds = 0.2
    game.hint_mode = "checkpoints"

    hints: list = []
    real_emit = ctx.sio.emit.side_effect

    async def end_the_turn_after_the_first_hint(event, *args, **kwargs):
        if event == "hint_revealed":
            hints.append(kwargs.get("to"))
            game.phase = Phase.TURN_RESULTS
        if real_emit is not None:
            return await real_emit(event, *args, **kwargs)

    ctx.sio.emit.side_effect = end_the_turn_after_the_first_hint
    ctx.game_flow.schedule_hint_checkpoints(room)
    await asyncio.sleep(0.35)

    assert len(hints) == 1, "the rest of the room was told after the turn had ended"
    [hint] = calls(ctx, "hint_revealed")
    assert hint.args[1]["turnId"] == game.current_turn_id, "a hint names its turn"
