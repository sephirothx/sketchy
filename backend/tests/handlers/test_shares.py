"""The `share_drawing` command (#1430): who may share, from where, and what the
room and the finished game keep."""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

from app.game import Phase
from app.handlers.shares import SPECTATORS_CANNOT_SHARE
from app.repositories.interfaces import DrawingShareResult
from app.services.drawing_shares import (
    NOT_ACCEPTED,
    NOT_SHAREABLE,
    NOT_VISIBLE,
    PRIVATE_ROOM,
    STILL_SAVING,
    WITHDRAWN,
)
from tests.fake_game_history_repo import FakeGameHistoryRepository
from tests.handlers.helpers import (
    build_context,
    build_room,
    contains_secret,
    play_to_completion,
    replay_staged,
)


def wire(ctx, room, players, extra=()):
    sessions = {
        player.sid: {"room_id": room.id, "player_id": player.id}
        for player in [*players.values(), *extra]
    }
    ctx.sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    return ctx.sio.handlers["/"]["share_drawing"]


def emitted(ctx, event):
    return [call.args[1] for call in ctx.sio.emit.await_args_list if call.args[0] == event]


def ink(room, game, strokes: int = 4) -> None:
    """The turn that just ended had something on it: the tests' drawers never
    draw, and a blank drawing is not shareable (R-SHARE-03)."""
    room.last_game_drawings[-1] = replace(room.last_game_drawings[-1], action_count=strokes)
    game.completed_turns[-1] = replace(game.completed_turns[-1], stroke_count=strokes)


async def to_results(ctx, room, *, strokes: int = 4):
    """A fresh game, drawn and ended: its first turn's results are up."""
    await ctx.game_flow._start_fresh_game(room, list(room.player_list()))
    game = room.game
    game.force_prompt_choice()
    await ctx.game_flow._end_turn(room)
    assert game.phase == Phase.TURN_RESULTS
    ink(room, game, strokes)
    return game


def guesser(room, players):
    return next(p for p in players.values() if p.id != room.game.current_drawer)


async def finish(ctx, room):
    """Play the rest of the game out, inking every turn, and record it."""
    ctx.timers.cancel_phase_timer(room.id)
    await ctx.game_flow._finish_or_next(room)
    while room.game is not None:
        game = room.game
        game.force_prompt_choice()
        await ctx.game_flow._end_turn(room)
        ink(room, game)
        ctx.timers.cancel_phase_timer(room.id)
        await ctx.game_flow._finish_or_next(room)
    await ctx.timers.close()
    await replay_staged(ctx)


async def test_a_guest_shares_from_the_results_and_the_room_hears_it():
    room_manager, room, players = build_room(rounds=1)
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    share = wire(ctx, room, players)
    game = await to_results(ctx, room)
    sharer = guesser(room, players)
    sharer.is_anonymous = True

    answer = await share(sharer.sid, {"turnId": game.current_turn_id, "shared": True})

    assert answer == {
        "ok": True,
        "turnId": game.current_turn_id,
        "shares": [sharer.id],
        "shareWithdrawn": False,
    }
    [broadcast] = emitted(ctx, "drawing_shared")
    assert broadcast == {
        "turnId": game.current_turn_id,
        "playerId": sharer.id,
        "nickname": sharer.nickname,
        "nameColor": sharer.name_color,
        "isAnonymous": True,
        "shared": True,
        "shares": [sharer.id],
        "shareWithdrawn": False,
    }
    assert not contains_secret(broadcast, sharer.user_id), "an account id on a room payload"
    await ctx.game_flow._sync_player_view(sharer.sid, room, sharer)
    synced = emitted(ctx, "turn_ended")[-1]
    assert synced["shares"] == [sharer.id], "a reconnect sees the control as it stands"
    await ctx.timers.close()


async def test_only_the_finished_turns_results_can_be_shared_from_a_live_game():
    room_manager, room, players = build_room(rounds=2)
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    share = wire(ctx, room, players)
    await ctx.game_flow._start_fresh_game(room, list(room.player_list()))
    game = room.game
    game.force_prompt_choice()
    sharer = guesser(room, players)
    drawing = await share(sharer.sid, {"turnId": game.current_turn_id, "shared": True})
    assert drawing["error"] == NOT_VISIBLE, "not while it is still being drawn"

    await ctx.game_flow._end_turn(room)
    first = game.current_turn_id
    assert (await share(sharer.sid, {"turnId": first, "shared": True}))["error"] == NOT_SHAREABLE, (
        "a blank drawing is nothing to show"
    )
    ink(room, game)
    assert (await share(sharer.sid, {"turnId": first, "shared": True}))["ok"]

    ctx.timers.cancel_phase_timer(room.id)
    await ctx.game_flow._finish_or_next(room)
    assert (await share(sharer.sid, {"turnId": first, "shared": False}))["error"] == NOT_VISIBLE
    await ctx.timers.close()
    await replay_staged(ctx)


async def test_a_private_room_shares_only_by_its_artist_and_spectators_never():
    room_manager, room, players = build_room(rounds=1)
    room.is_public = False
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    watcher = room_manager.add_player(room, "Wat", user_id="user-wat", is_spectator=True)
    watcher.sid = "sid-wat"
    share = wire(ctx, room, players, extra=[watcher])
    game = await to_results(ctx, room)
    payload = {"turnId": game.current_turn_id, "shared": True}
    drawer = room.players[game.current_drawer]

    assert (await share(guesser(room, players).sid, payload))["error"] == PRIVATE_ROOM
    assert (await share("sid-wat", payload))["error"] == SPECTATORS_CANNOT_SHARE
    assert (await share("sid-nobody", payload))["error"] == "Not in this room"
    assert (await share(drawer.sid, payload))["shares"] == [drawer.id]
    await ctx.timers.close()


async def test_the_drawers_withdrawal_holds_in_the_room_until_they_share_again():
    room_manager, room, players = build_room(rounds=1)
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    share = wire(ctx, room, players)
    game = await to_results(ctx, room)
    turn_id = game.current_turn_id
    drawer = room.players[game.current_drawer]
    other = guesser(room, players)

    await share(other.sid, {"turnId": turn_id, "shared": True})
    taken = await share(drawer.sid, {"turnId": turn_id, "shared": False})
    assert taken["shares"] == [] and taken["shareWithdrawn"] is True
    assert (await share(other.sid, {"turnId": turn_id, "shared": True}))["error"] == WITHDRAWN

    again = await share(drawer.sid, {"turnId": turn_id, "shared": True})
    assert again["shares"] == [drawer.id] and again["shareWithdrawn"] is False
    assert (await share(other.sid, {"turnId": turn_id, "shared": True}))["shares"] == [
        drawer.id,
        other.id,
    ]
    await ctx.timers.close()


async def test_live_shares_go_into_history_with_the_withdrawals():
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    share = wire(ctx, room, players)
    game = await to_results(ctx, room)
    shared_turn = game.current_turn_id
    sharer = guesser(room, players)
    await share(sharer.sid, {"turnId": shared_turn, "shared": True})
    await ctx.timers.close()

    ctx.timers.cancel_phase_timer(room.id)
    await ctx.game_flow._finish_or_next(room)
    withdrawn_turn = room.game.current_turn_id
    room.game.force_prompt_choice()
    await ctx.game_flow._end_turn(room)
    ink(room, room.game)
    second_drawer = room.players[room.game.current_drawer]
    await share(second_drawer.sid, {"turnId": withdrawn_turn, "shared": False})
    await finish(ctx, room)

    [saved] = history.saved
    seat = next(p for p in saved.participants if p.user_id == sharer.user_id)
    assert [(s.turn_id, s.seat_id, s.user_id, s.notify_drawer) for s in saved.shares] == [
        (shared_turn, seat.seat_id, sharer.user_id, False)
    ], "the drawer was still in the room to see it"
    assert saved.withdrawn_turn_ids == [withdrawn_turn]
    recap = emitted(ctx, "game_ended")[-1]["drawings"]
    assert recap[0]["shares"] == [sharer.id] and recap[1]["shareWithdrawn"] is True


async def test_a_drawer_who_left_is_told_afterwards():
    room_manager, room, players = build_room(
        rounds=1, accounts={"Ann": "user-ann", "Bob": "user-bob", "Cid": "user-cid"}
    )
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    share = wire(ctx, room, players)
    game = await to_results(ctx, room)
    turn_id = game.current_turn_id
    drawer = room.players[game.current_drawer]
    sharer = guesser(room, players)
    await share(sharer.sid, {"turnId": turn_id, "shared": True})
    # The drawer walks out; their seat stays in the game as a departed one.
    room_manager.remove_player(room, drawer.id)
    await finish(ctx, room)
    [saved] = history.saved
    assert [share.notify_drawer for share in saved.shares] == [True]


# ------------------------------------------------------------------ recap


async def finished():
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    share = wire(ctx, room, players)
    await play_to_completion(ctx, room, players)
    room.last_game_drawings = [
        replace(entry, action_count=3) for entry in room.last_game_drawings
    ]
    assert room.game is None and room.last_game_history == "recorded"
    ctx.sio.emit.reset_mock()
    return ctx, room, players, history, share


async def test_a_recap_share_is_written_first_then_shown_and_announced():
    ctx, room, players, history, share = await finished()
    entry = room.last_game_drawings[0]
    sharer = next(p for p in players.values() if p.id != entry.drawer_id)
    pushed: list[str] = []
    changed: list[bool] = []

    async def push(user_id):
        pushed.append(user_id)

    ctx.on_share_notice = push
    ctx.on_gallery_changed = lambda: changed.append(True)
    history.share_result = DrawingShareResult(
        turn_id=entry.turn_id, shares=("seat-x",), withdrawn=False, notify_user_id="user-ann"
    )

    answer = await share(sharer.sid, {"turnId": entry.turn_id, "shared": True})

    assert answer["ok"] and answer["shares"] == [sharer.id]
    [write] = history.share_writes
    assert (write.game_id, write.turn_id, write.requesting_user_id, write.shared) == (
        room.last_game_id,
        entry.turn_id,
        sharer.user_id,
        True,
    )
    assert write.notify_drawer is False, "the drawer is in the room, watching"
    assert [call.args[0] for call in ctx.sio.emit.await_args_list] == ["drawing_shared"]
    assert pushed == ["user-ann"] and changed == [True]
    assert room.last_game_payload()["drawings"][0]["shares"] == [sharer.id]


async def test_a_recap_share_the_database_refuses_leaves_no_trace():
    ctx, room, players, history, share = await finished()
    entry = room.last_game_drawings[0]
    sharer = next(p for p in players.values() if p.id != entry.drawer_id)

    answer = await share(sharer.sid, {"turnId": entry.turn_id, "shared": True})

    assert answer == {"ok": False, "errorCode": "share_not_accepted", "error": NOT_ACCEPTED}
    assert room.drawing_shares == {} and ctx.sio.emit.await_args_list == []


async def test_the_recap_waits_for_the_game_to_be_saved():
    ctx, room, players, history, share = await finished()
    entry = room.last_game_drawings[0]
    room.last_game_history = "pending"
    answer = await share(entry.drawer_id and room.players[entry.drawer_id].sid, {
        "turnId": entry.turn_id, "shared": True,
    })
    assert answer == {"ok": False, "errorCode": "game_still_saving", "error": STILL_SAVING}
    assert history.share_writes == []


async def test_the_payload_is_validated_before_anything_else():
    room_manager, room, players = build_room(rounds=1)
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    share = wire(ctx, room, players)
    assert (await share("sid-ann", {"turnId": "x"}))["ok"] is False
    assert (await share("sid-ann", {"turnId": "", "shared": True}))["ok"] is False
    assert (await share("sid-ann", {"turnId": "x", "shared": "yes"}))["ok"] is False
    assert (await share("sid-ann", {"turnId": "x", "shared": True, "extra": 1}))["ok"] is False
    assert (await share("sid-ann", "share"))["ok"] is False
