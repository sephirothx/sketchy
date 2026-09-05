"""The `react_to_drawing` command: who may react, to what, and what the room hears."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.game import Phase
from app.services.drawing_reactions import (
    NOT_ACCEPTED,
    NOT_RECORDED,
    NOT_VISIBLE,
    OWN_DRAWING,
    STILL_SAVING,
)
from app.handlers.reactions import GUESTS_CANNOT_REACT, SPECTATORS_CANNOT_REACT
from tests.fake_game_history_repo import FakeGameHistoryRepository
from tests.handlers.helpers import (
    build_context,
    build_room,
    contains_secret,
    play_to_completion,
)

pytestmark = pytest.mark.asyncio


def wire(ctx, room, players):
    """Bind each player's socket to their seat and mark the accounts registered."""
    sessions = {
        player.sid: {"room_id": room.id, "player_id": player.id}
        for player in players.values()
    }
    ctx.sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    for player in players.values():
        if player.user_id is not None:
            player.is_anonymous = False
    return ctx.sio.handlers["/"]["react_to_drawing"]


async def start_drawing(ctx, room):
    await ctx.game_flow._start_fresh_game(room, list(room.player_list()))
    room.game.force_prompt_choice()
    assert room.game.phase == Phase.DRAWING
    return room.game


def emitted(ctx, event):
    return [call.args[1] for call in ctx.sio.emit.await_args_list if call.args[0] == event]


def guesser(room, players):
    return next(p for p in players.values() if p.id != room.game.current_drawer)


async def test_a_guesser_reacts_and_the_whole_room_hears_it():
    room_manager, room, players = build_room(rounds=1)
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    react = wire(ctx, room, players)
    game = await start_drawing(ctx, room)
    reactor = guesser(room, players)

    answer = await react(reactor.sid, {"turnId": game.current_turn_id, "emoji": "heart"})

    assert answer == {
        "ok": True,
        "turnId": game.current_turn_id,
        "emoji": "heart",
        "tally": {"heart": 1},
    }
    [broadcast] = emitted(ctx, "drawing_reaction")
    assert broadcast == {
        "turnId": game.current_turn_id,
        "playerId": reactor.id,
        "nickname": reactor.nickname,
        "nameColor": reactor.name_color,
        "isAnonymous": False,
        "emoji": "heart",
        "tally": {"heart": 1},
    }
    assert not contains_secret(broadcast, reactor.user_id), "an account id on a room payload"
    # The drawer is in the room too, so `room=` rather than a filtered fan-out.
    call = next(c for c in ctx.sio.emit.await_args_list if c.args[0] == "drawing_reaction")
    assert call.kwargs.get("room") == room.id


async def test_a_reaction_can_be_changed_and_taken_back():
    room_manager, room, players = build_room(rounds=1)
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    react = wire(ctx, room, players)
    game = await start_drawing(ctx, room)
    reactor = guesser(room, players)
    turn_id = game.current_turn_id

    await react(reactor.sid, {"turnId": turn_id, "emoji": "heart"})
    changed = await react(reactor.sid, {"turnId": turn_id, "emoji": "fire"})
    assert changed["tally"] == {"fire": 1}, "a change is not a second reaction"
    removed = await react(reactor.sid, {"turnId": turn_id, "emoji": None})
    assert removed == {"ok": True, "turnId": turn_id, "emoji": None, "tally": {}}
    assert room.drawing_reactions == {}
    assert emitted(ctx, "drawing_reaction")[-1]["emoji"] is None


async def test_guests_spectators_and_the_drawer_cannot_react():
    room_manager, room, players = build_room(
        rounds=1,
        accounts={"Ann": "user-ann", "Bob": "user-bob", "Gus": "user-gus", "Cid": None},
    )
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    react = wire(ctx, room, players)
    players["Gus"].is_anonymous = True
    watcher = room_manager.add_player(room, "Wat", user_id="user-wat", is_spectator=True)
    watcher.sid = "sid-wat"
    watcher.is_anonymous = False
    ctx.sio.get_session.side_effect = None
    sessions = {
        p.sid: {"room_id": room.id, "player_id": p.id}
        for p in list(players.values()) + [watcher]
    }
    ctx.sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    game = await start_drawing(ctx, room)
    payload = {"turnId": game.current_turn_id, "emoji": "wow"}
    drawer = room.players[game.current_drawer]

    assert (await react("sid-gus", payload))["error"] == GUESTS_CANNOT_REACT
    assert (await react("sid-cid", payload))["error"] == GUESTS_CANNOT_REACT
    assert (await react("sid-wat", payload))["error"] == SPECTATORS_CANNOT_REACT
    assert (await react(drawer.sid, payload))["error"] == OWN_DRAWING
    assert (await react("sid-nobody", payload))["error"] == "Not in this room"
    assert emitted(ctx, "drawing_reaction") == []
    assert room.drawing_reactions == {}


async def test_a_seat_that_cannot_guess_can_still_react():
    """AFK or disconnected at freeze, they can see the drawing, so they may."""
    room_manager, room, players = build_room(rounds=1)
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    react = wire(ctx, room, players)
    game = await start_drawing(ctx, room)
    reactor = guesser(room, players)
    reactor.is_afk = True
    game.snapshot_turn_participants({reactor.id: "afk"})
    assert not game.is_turn_eligible(reactor.id)

    answer = await react(reactor.sid, {"turnId": game.current_turn_id, "emoji": "laugh"})

    assert answer["ok"] is True


async def test_only_the_drawing_on_screen_can_be_reacted_to():
    room_manager, room, players = build_room(rounds=2)
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    react = wire(ctx, room, players)
    game = await start_drawing(ctx, room)
    reactor = guesser(room, players)
    first_turn = game.current_turn_id

    stale = await react(reactor.sid, {"turnId": "not-this-turn", "emoji": "heart"})
    assert stale == {"ok": False, "error": NOT_VISIBLE}

    # Turn results still show the drawing.
    await ctx.game_flow._end_turn(room)
    assert game.phase == Phase.TURN_RESULTS
    assert (await react(reactor.sid, {"turnId": first_turn, "emoji": "heart"}))["ok"]

    # Choosing the next prompt shows nothing yet, and the previous one is gone.
    ctx.timers.cancel_phase_timer(room.id)
    await ctx.game_flow._finish_or_next(room)
    assert game.phase == Phase.CHOOSING_PROMPT
    other = next(p for p in players.values() if p.id != game.current_drawer)
    assert (await react(other.sid, {"turnId": game.current_turn_id, "emoji": "heart"}))[
        "error"
    ] == NOT_VISIBLE
    assert (await react(other.sid, {"turnId": first_turn, "emoji": "heart"}))[
        "error"
    ] == NOT_VISIBLE
    await ctx.timers.close()


async def test_a_drawer_who_rejoined_still_cannot_react_to_their_own_drawing():
    room_manager, room, players = build_room(rounds=1)
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    wire(ctx, room, players)
    game = await start_drawing(ctx, room)
    drawer = room.players[game.current_drawer]
    # The same account comes back on a fresh token, mid-turn.
    rejoined = room_manager.add_player(room, drawer.nickname, user_id=drawer.user_id)
    rejoined.sid = "sid-again"
    rejoined.is_anonymous = False
    sessions = {"sid-again": {"room_id": room.id, "player_id": rejoined.id}}
    ctx.sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    react = ctx.sio.handlers["/"]["react_to_drawing"]

    answer = await react("sid-again", {"turnId": game.current_turn_id, "emoji": "wow"})

    assert answer == {"ok": False, "error": OWN_DRAWING}


async def test_live_reactions_ride_on_the_turn_payloads_and_into_history():
    """A reconnect sees the tally and its own pick; the finished game keeps them."""
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    react = wire(ctx, room, players)
    game = await start_drawing(ctx, room)
    reactor = guesser(room, players)
    turn_id = game.current_turn_id
    await react(reactor.sid, {"turnId": turn_id, "emoji": "fire"})

    await ctx.game_flow._sync_player_view(reactor.sid, room, reactor)
    [synced] = emitted(ctx, "sync_game")
    assert synced["turnId"] == turn_id
    assert synced["reactions"] == [{"playerId": reactor.id, "emoji": "fire"}]

    await ctx.game_flow._end_turn(room)
    ended = emitted(ctx, "turn_ended")[-1]
    assert ended["turnId"] == turn_id
    assert ended["reactions"] == [{"playerId": reactor.id, "emoji": "fire"}]

    ctx.timers.cancel_phase_timer(room.id)
    await ctx.game_flow._finish_or_next(room)
    # Two players, one round: the other player's turn is still to come.
    while room.game is not None:
        room.game.force_prompt_choice()
        await ctx.game_flow._end_turn(room)
        ctx.timers.cancel_phase_timer(room.id)
        await ctx.game_flow._finish_or_next(room)
    await ctx.timers.close()
    [saved] = history.saved
    seat = next(p for p in saved.participants if p.user_id == reactor.user_id)
    assert [(r.turn_id, r.seat_id, r.user_id, r.emoji) for r in saved.reactions] == [
        (turn_id, seat.seat_id, reactor.user_id, "fire")
    ]
    game_ended = emitted(ctx, "game_ended")[-1]
    assert game_ended["drawings"][0]["turnId"] == turn_id
    assert game_ended["drawings"][0]["reactions"] == [
        {"playerId": reactor.id, "emoji": "fire"}
    ]
    assert room.last_game_id == saved.record.id
    assert room.last_game_history == "recorded"


async def test_a_late_write_from_an_earlier_game_does_not_speak_for_the_newer_one():
    """The write is bounded at ten seconds; a rematch can start and stop inside
    that. When the old write finally lands - or fails - the room has moved on,
    and its verdict belongs to a game the room no longer calls its last."""
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    wire(ctx, room, players)
    await play_to_completion(ctx, room, players)
    assert room.last_game_history == "recorded"
    newer = room.last_game_id

    stale = SimpleNamespace(
        record=SimpleNamespace(id="an-earlier-game"),
        participants=[], turns=[], guesses=[], score_events=[], drawings=[], reactions=[],
    )
    history.fail = True
    await ctx.game_flow._persist_game_history(room, stale)
    assert (room.last_game_id, room.last_game_history) == (newer, "recorded")

    history.fail = False
    room.last_game_history = "pending"
    await ctx.game_flow._persist_game_history(room, stale)
    assert room.last_game_history == "pending", "a stale success must not open the recap"


async def test_an_abandoned_game_carries_its_reactions_too():
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    react = wire(ctx, room, players)
    game = await start_drawing(ctx, room)
    reactor = guesser(room, players)
    await react(reactor.sid, {"turnId": game.current_turn_id, "emoji": "heart"})
    await ctx.game_flow._end_turn(room)
    ctx.timers.cancel_phase_timer(room.id)

    assert await ctx.game_flow.record_abandoned_game(room) is True
    await ctx.timers.close()

    [saved] = history.saved
    assert saved.record.outcome == "abandoned"
    assert [r.emoji for r in saved.reactions] == ["heart"]
    assert room.last_game_history == "recorded"


# ------------------------------------------------------------------ recap


async def finished(history=None, *, guests: bool = False):
    room_manager, room, players = build_room(rounds=1)
    history = history or FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    react = wire(ctx, room, players)
    await play_to_completion(ctx, room, players)
    assert room.game is None and room.last_game_drawings
    ctx.sio.emit.reset_mock()
    return ctx, room, players, history, react


def recap_target(room, players):
    """A recap entry and a player who did not draw it."""
    entry = room.last_game_drawings[0]
    reactor = next(p for p in players.values() if p.id != entry.drawer_id)
    return entry, reactor


async def test_a_recap_reaction_is_written_to_the_finished_game_then_shown():
    ctx, room, players, history, react = await finished()
    history.accept_reactions = True
    entry, reactor = recap_target(room, players)

    answer = await react(reactor.sid, {"turnId": entry.turn_id, "emoji": "wow"})

    assert answer["ok"] is True and answer["tally"] == {"wow": 1}
    [write] = history.reaction_writes
    assert (write.game_id, write.turn_id, write.requesting_user_id, write.emoji) == (
        room.last_game_id,
        entry.turn_id,
        reactor.user_id,
        "wow",
    )
    assert room.drawing_reactions == {entry.turn_id: {reactor.id: "wow"}}
    events = [call.args[0] for call in ctx.sio.emit.await_args_list]
    assert events.index("drawing_reaction") < events.index("room_state")
    state = emitted(ctx, "room_state")[0]
    assert state["lastGameDrawings"][0]["reactions"] == [
        {"playerId": reactor.id, "emoji": "wow"}
    ]
    most = next(h for h in state["lastGameHighlights"] if h["kind"] == "most_reacted_drawing")
    assert most["reactionCount"] == 1 and most["drawingIndex"] == 0
    assert most["turnId"] == entry.turn_id


async def test_a_recap_reaction_the_database_refuses_leaves_no_trace():
    ctx, room, players, history, react = await finished()
    entry, reactor = recap_target(room, players)

    answer = await react(reactor.sid, {"turnId": entry.turn_id, "emoji": "wow"})

    assert answer == {"ok": False, "error": NOT_ACCEPTED}
    assert room.drawing_reactions == {}
    assert ctx.sio.emit.await_args_list == []


async def test_the_recap_refuses_while_the_game_is_still_being_saved():
    ctx, room, players, history, react = await finished()
    entry, reactor = recap_target(room, players)
    room.last_game_history = "pending"

    answer = await react(reactor.sid, {"turnId": entry.turn_id, "emoji": "wow"})

    assert answer == {"ok": False, "error": STILL_SAVING}
    assert history.reaction_writes == []


async def test_a_game_that_was_never_recorded_takes_no_recap_reactions():
    ctx, room, players, history, react = await finished(FakeGameHistoryRepository(fail=True))
    assert room.last_game_history == "failed"
    entry, reactor = recap_target(room, players)

    answer = await react(reactor.sid, {"turnId": entry.turn_id, "emoji": "wow"})

    assert answer == {"ok": False, "error": NOT_RECORDED}


async def test_the_recap_drawer_cannot_react_to_their_own_and_unknown_turns_are_refused():
    ctx, room, players, history, react = await finished()
    history.accept_reactions = True
    entry = room.last_game_drawings[0]
    drawer = room.players[entry.drawer_id]

    assert (await react(drawer.sid, {"turnId": entry.turn_id, "emoji": "wow"}))[
        "error"
    ] == OWN_DRAWING
    assert (await react(drawer.sid, {"turnId": "elsewhere", "emoji": "wow"}))[
        "error"
    ] == NOT_VISIBLE
    assert history.reaction_writes == []


async def test_the_payload_is_validated_before_anything_else():
    room_manager, room, players = build_room(rounds=1)
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    react = wire(ctx, room, players)

    assert (await react("sid-ann", {"turnId": "x", "emoji": "thumbs_down"}))["ok"] is False
    assert (await react("sid-ann", {"turnId": "", "emoji": "heart"}))["ok"] is False
    assert (await react("sid-ann", {"emoji": "heart"}))["ok"] is False
    assert (await react("sid-ann", {"turnId": "x", "emoji": "heart", "extra": 1}))["ok"] is False
    assert (await react("sid-ann", "heart"))["ok"] is False
