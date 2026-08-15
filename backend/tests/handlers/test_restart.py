import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import socketio

from app.canvas_history import encode_canvas_history
from app.game import Game, Phase
from app.handlers import register_all_handlers as register_handlers
from app.live_drawing import encode_live_drawing
from app.rooms import DrawingRecapEntry, RestartVote, RoomManager, STARTING_SCORE


def active_room(player_count: int = 3):
    room_manager = RoomManager()
    room = room_manager.create_room(name="Restart room", rounds=2)
    players = [
        room_manager.add_player(room, f"Player {index + 1}")
        for index in range(player_count)
    ]
    for index, player in enumerate(players):
        player.sid = f"p{index + 1}-sid"
    room.state = "playing"
    room.game = Game(turn_order=[player.id for player in players], rounds_total=2)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()
    return room_manager, room, players


def registered_server(room_manager, room, players):
    sio = socketio.AsyncServer(async_mode="asgi")
    context = register_handlers(sio, room_manager)
    sessions = {
        player.sid: {"room_id": room.id, "player_id": player.id}
        for player in players
        if player.sid
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()
    return sio, context, sessions


@pytest.mark.parametrize(
    ("eligible_count", "required_votes"),
    ((2, 2), (3, 2), (4, 3)),
)
def test_restart_vote_requires_a_strict_majority(
    eligible_count: int,
    required_votes: int,
):
    vote = RestartVote(
        proposer_id="player-1",
        proposer_nickname="Player 1",
        eligible_voter_ids=tuple(
            f"player-{index}" for index in range(1, eligible_count + 1)
        ),
        votes={"player-1": True},
        expires_at=0,
    )

    assert vote.required_votes == required_votes


@pytest.mark.asyncio
async def test_restart_vote_cannot_start_before_the_first_turn_is_initialized():
    room_manager, room, players = active_room(2)
    room.game = Game(turn_order=[player.id for player in players], rounds_total=2)
    sio, context, _ = registered_server(room_manager, room, players)

    response = await sio.handlers["/"]["propose_restart_vote"](
        players[0].sid, {}
    )

    assert response == {"ok": False, "error": "The game is still starting"}
    assert room.restart_vote is None
    assert context.timers.restart_timers == {}

    await context.timers.close()


@pytest.mark.asyncio
async def test_restart_vote_snapshots_eligible_players_and_requires_strict_majority():
    room_manager, room, players = active_room(4)
    proposer, voter, third_voter, afk_player = players
    afk_player.is_afk = True
    spectator = room_manager.add_player(room, "Spectator", is_spectator=True)
    spectator.sid = "spectator-sid"

    sio, context, sessions = registered_server(
        room_manager, room, [*players, spectator]
    )
    propose = sio.handlers["/"]["propose_restart_vote"]
    cast = sio.handlers["/"]["cast_restart_vote"]

    assert await propose("spectator-sid", {}) == {
        "ok": False,
        "error": "Only active, non-AFK players can propose a restart",
    }
    assert await propose(afk_player.sid, {}) == {
        "ok": False,
        "error": "Only active, non-AFK players can propose a restart",
    }

    response = await propose(proposer.sid, {})
    assert response["ok"] is True
    vote = room.restart_vote
    assert vote is not None
    assert vote.eligible_voter_ids == (proposer.id, voter.id, third_voter.id)
    assert vote.votes == {proposer.id: True}
    assert vote.required_votes == 2

    late_player = room_manager.add_player(room, "Late player")
    late_player.sid = "late-sid"
    room.game.add_player_to_rotation(late_player.id)
    sessions[late_player.sid] = {
        "room_id": room.id,
        "player_id": late_player.id,
    }
    assert await cast(late_player.sid, {"vote": True}) == {
        "ok": False,
        "error": "You are not eligible to vote",
    }

    first = await cast(voter.sid, {"vote": False})
    assert first["ok"] is True
    assert first["approved"] is False
    assert first["rejected"] is False
    assert vote.votes[voter.id] is False

    duplicate = await cast(voter.sid, {"vote": False})
    assert duplicate["ok"] is True
    assert duplicate["approved"] is False
    assert duplicate["rejected"] is False
    assert vote.votes[voter.id] is False

    with patch("app.handlers.restart.RESTART_DELAY_SECONDS", 60):
        changed = await cast(voter.sid, {"vote": True})
    assert changed["ok"] is True
    assert changed["approved"] is True
    assert vote.status == "approved"
    assert vote.payload()["castVotes"] == [
        {"playerId": proposer.id, "vote": True},
        {"playerId": voter.id, "vote": True},
    ]
    assert room.game.phase == Phase.GAME_END

    await context.timers.close()


@pytest.mark.asyncio
async def test_restart_vote_expiry_enforces_cooldown():
    room_manager, room, players = active_room(2)
    sio, context, _ = registered_server(room_manager, room, players)
    propose = sio.handlers["/"]["propose_restart_vote"]

    with patch("app.handlers.restart.RESTART_VOTE_SECONDS", 0.01):
        response = await propose(players[0].sid, {})
        assert response["ok"] is True
        await asyncio.sleep(0.03)

    assert room.restart_vote is None
    assert room.restart_vote_cooldown_until > 0
    retry = await propose(players[0].sid, {})
    assert retry["ok"] is False
    assert "Another restart vote can be proposed" in retry["error"]
    assert any(
        call.args[0] == "chat_message"
        and call.args[1]["text"] == "The restart vote expired without passing."
        for call in sio.emit.await_args_list
    )

    await context.timers.close()


@pytest.mark.asyncio
async def test_restart_vote_rejection_closes_immediately_and_enforces_cooldown():
    room_manager, room, players = active_room(2)
    sio, context, _ = registered_server(room_manager, room, players)
    propose = sio.handlers["/"]["propose_restart_vote"]
    cast = sio.handlers["/"]["cast_restart_vote"]

    assert (await propose(players[0].sid, {}))["ok"] is True
    rejected = await cast(players[1].sid, {"vote": False})

    assert rejected == {"ok": True, "approved": False, "rejected": True}
    assert room.restart_vote is None
    assert room.restart_vote_cooldown_until > 0
    retry = await propose(players[0].sid, {})
    assert retry["ok"] is False
    assert "Another restart vote can be proposed" in retry["error"]
    assert any(
        call.args[0] == "chat_message"
        and call.args[1]["text"] == "The restart vote was rejected."
        for call in sio.emit.await_args_list
    )

    await context.timers.close()


@pytest.mark.asyncio
async def test_approved_restart_atomically_replaces_game_and_rejects_stale_canvas():
    room_manager, room, players = active_room(2)
    proposer, voter = players
    room.rounds = 4
    room.drawing_seconds = 30
    room.custom_words = ["reviewword", "secondword", "thirdword"]
    room.custom_words_only = True
    room.hint_mode = "wheel"
    room.hide_masked_prompt = True
    room.spectators_see_solution = True
    old_game = room.game
    assert old_game is not None
    old_generation = old_game.canvas.generation
    old_game.canvas.history.append_path(
        [(0.1, 0.1), (0.2, 0.2)], color=0, width=4
    )
    proposer.score = 999
    voter.score = 1
    room.last_game_drawings.append(
        DrawingRecapEntry(
            round_number=1,
            turn_number=1,
            drawer_id=proposer.id,
            drawer_nickname=proposer.nickname,
            drawer_name_color=proposer.name_color,
            word="old",
            action_count=0,
            canvas_history=encode_canvas_history([]),
        )
    )

    sio, context, _ = registered_server(room_manager, room, players)
    old_phase_timer = asyncio.create_task(asyncio.sleep(60))
    old_hint_timer = asyncio.create_task(asyncio.sleep(60))
    context.timers.replace_phase_timer(room.id, old_phase_timer)
    context.timers.add_hint_timer(room.id, old_hint_timer)

    await sio.handlers["/"]["propose_restart_vote"](proposer.sid, {})
    with patch("app.handlers.restart.RESTART_DELAY_SECONDS", 0.01):
        approved = await sio.handlers["/"]["cast_restart_vote"](
            voter.sid, {"vote": True}
        )
        assert approved["approved"] is True
        await asyncio.sleep(0.03)

    assert old_phase_timer.cancelled()
    assert old_hint_timer.cancelled()
    assert room.game is not None and room.game is not old_game
    assert room.game.phase == Phase.CHOOSING_WORD
    assert room.game.round_number == 1
    assert room.game.rounds_total == 4
    assert room.game.drawing_seconds == 30
    assert room.game.word_pool == ["reviewword", "secondword", "thirdword"]
    assert room.game.hint_mode == "wheel"
    assert room.game.hide_masked_prompt is True
    assert room.spectators_see_solution is True
    assert room.game.canvas.generation > old_generation
    assert room.last_game_drawings == []
    assert room.last_game_scores == []
    assert proposer.score == STARTING_SCORE
    assert voter.score == STARTING_SCORE
    assert room.restart_vote is None
    assert room.restart_vote_cooldown_until == 0

    word = room.game.word_choices[0]
    selected = await sio.handlers["/"]["select_word"](
        proposer.sid, {"word": word}
    )
    assert selected == {"ok": True}
    stale_frame = encode_live_drawing(
        "draw_start",
        {"x": 0.2, "y": 0.3, "color": "#000000", "width": 4},
    )
    await sio.handlers["/"]["draw"](
        proposer.sid,
        stale_frame,
        [old_generation, 1],
    )
    assert len(room.game.canvas.history) == 0
    assert any(
        call.args[0] == "sync_strokes"
        and call.kwargs.get("to") == proposer.sid
        for call in sio.emit.await_args_list
    )
    assert any(
        call.args[0] == "game_started"
        and call.args[1] == {"restarted": True}
        for call in sio.emit.await_args_list
    )

    await context.timers.close()


@pytest.mark.asyncio
async def test_disconnected_snapshot_voter_can_vote_after_reconnect_only():
    room_manager, room, players = active_room(3)
    proposer, reconnecting, third = players
    sio, context, sessions = registered_server(room_manager, room, players)
    propose = sio.handlers["/"]["propose_restart_vote"]
    cast = sio.handlers["/"]["cast_restart_vote"]

    await propose(proposer.sid, {})
    old_sid = reconnecting.sid
    reconnecting.connected = False
    reconnecting.sid = None
    assert await cast(old_sid, {"vote": True}) == {
        "ok": False,
        "error": "Not in this room",
    }

    reconnecting.sid = "reconnected-sid"
    reconnecting.connected = True
    sessions[reconnecting.sid] = {
        "room_id": room.id,
        "player_id": reconnecting.id,
    }
    with patch("app.handlers.restart.RESTART_DELAY_SECONDS", 60):
        response = await cast(reconnecting.sid, {"vote": True})
    assert response["ok"] is True
    assert response["approved"] is True
    assert third.id in room.restart_vote.eligible_voter_ids

    await context.timers.close()


@pytest.mark.asyncio
async def test_approved_restart_is_cancelled_if_too_few_players_remain():
    room_manager, room, players = active_room(2)
    proposer, voter = players
    sio, context, _ = registered_server(room_manager, room, players)

    await sio.handlers["/"]["propose_restart_vote"](proposer.sid, {})
    with patch("app.handlers.restart.RESTART_DELAY_SECONDS", 0.01):
        approved = await sio.handlers["/"]["cast_restart_vote"](
            voter.sid, {"vote": True}
        )
        assert approved["approved"] is True
        voter.connected = False
        voter.sid = None
        await asyncio.sleep(0.03)

    assert room.state == "waiting"
    assert room.game is None
    assert room.restart_vote is None
    assert room.restart_vote_cooldown_until > 0
    assert any(
        call.args[0] == "chat_message"
        and "fewer than two active players remain" in call.args[1]["text"]
        for call in sio.emit.await_args_list
    )
    restarted_events = [
        call
        for call in sio.emit.await_args_list
        if call.args[0] == "game_started"
        and call.args[1] == {"restarted": True}
    ]
    assert restarted_events == []

    await context.timers.close()
