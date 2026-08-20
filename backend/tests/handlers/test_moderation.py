import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, patch

import pytest
import socketio

from app.canvas_history import (
    ClearAction,
    FillAction,
    PathAction,
    ShapeAction,
    decode_binary_canvas_history,
    encode_canvas_history,
)
from app.handlers import register_all_handlers as register_handlers
from app.game import DRAWING_SECONDS, Game, Phase
from app.live_drawing import encode_live_drawing
from app.message_limits import MAX_CHAT_MESSAGE_LENGTH
from app.rooms import DrawingRecapEntry, RoomManager
from app.words import MAX_WORD_LENGTH


def canvas_action(game: Game, sequence: int) -> list[int]:
    return [game.canvas.generation, sequence]


def contains_secret(value, secret: str) -> bool:
    if value == secret:
        return True
    if isinstance(value, dict):
        return any(
            key in {"reconnectSecret", "reconnect_secret"}
            or contains_secret(item, secret)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return any(contains_secret(item, secret) for item in value)
    return False

@pytest.mark.asyncio
async def test_toggle_afk_socket_handler_and_not_waited_for():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    p1 = room_manager.add_player(room, "P1")
    p2 = room_manager.add_player(room, "P2")
    p3 = room_manager.add_player(room, "P3")
    p1.sid, p2.sid, p3.sid = "p1-sid", "p2-sid", "p3-sid"

    room.state = "playing"
    room.game = Game(turn_order=[p1.id, p2.id, p3.id], rounds_total=1)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game._set_word("banana")

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sessions = {
        "p1-sid": {"room_id": room.id, "player_id": p1.id},
        "p2-sid": {"room_id": room.id, "player_id": p2.id},
        "p3-sid": {"room_id": room.id, "player_id": p3.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    toggle_afk = sio.handlers["/"]["toggle_afk"]
    guess = sio.handlers["/"]["guess"]

    # P2 guesses correctly
    await guess("p2-sid", {"text": "banana"})
    # Round is not ended yet because P3 hasn't guessed
    assert room.game.phase == Phase.DRAWING

    # P3 goes AFK -> P3 is no longer waited for -> round ends immediately!
    await toggle_afk("p3-sid", {"afk": True})
    assert p3.is_afk is True
    assert room.game.phase == Phase.ROUND_END

    timer = timers.phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer

@pytest.mark.asyncio
async def test_vote_kick_and_vote_afk_socket_handlers():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    p1 = room_manager.add_player(room, "P1")
    p2 = room_manager.add_player(room, "P2")
    p3 = room_manager.add_player(room, "P3")
    p1.sid, p2.sid, p3.sid = "p1-sid", "p2-sid", "p3-sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "p1-sid": {"room_id": room.id, "player_id": p1.id},
        "p2-sid": {"room_id": room.id, "player_id": p2.id},
        "p3-sid": {"room_id": room.id, "player_id": p3.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    vote_player = sio.handlers["/"]["vote_player"]

    # P1 votes to AFK P2 (required = 2 votes because 2 other connected players)
    res1 = await vote_player("p1-sid", {"targetPlayerId": p2.id, "action": "afk"})
    assert res1["ok"] is True
    assert res1["executed"] is False
    assert p1.id in p2.afk_votes
    assert p2.is_afk is False

    # P3 votes to AFK P2 -> threshold reached -> P2 is marked AFK
    res2 = await vote_player("p3-sid", {"targetPlayerId": p2.id, "action": "afk"})
    assert res2["ok"] is True
    assert res2["executed"] is True
    assert p2.is_afk is True

    # P1 votes to Kick P2
    res3 = await vote_player("p1-sid", {"targetPlayerId": p2.id, "action": "kick"})
    assert res3["ok"] is True
    assert res3["executed"] is False

    # P3 votes to Kick P2 -> threshold reached -> P2 is kicked
    res4 = await vote_player("p3-sid", {"targetPlayerId": p2.id, "action": "kick"})
    assert res4["ok"] is True
    assert res4["executed"] is True
    assert p2.id not in room.players

    # Emitted kicked event to P2
    kicked_calls = [call for call in sio.emit.await_args_list if call.args[0] == "kicked" and call.kwargs.get("to") == "p2-sid"]
    assert len(kicked_calls) == 1

@pytest.mark.asyncio
async def test_direct_socket_moderation_rejects_spectator_voters_and_targets():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    voter = room_manager.add_player(room, "Voter")
    target = room_manager.add_player(room, "Target")
    afk_voter = room_manager.add_player(room, "AFK voter")
    spectator = room_manager.add_player(room, "Spectator", is_spectator=True)
    voter.sid = "voter-sid"
    target.sid = "target-sid"
    afk_voter.sid = "afk-sid"
    spectator.sid = "spectator-sid"
    afk_voter.is_afk = True

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "voter-sid": {"room_id": room.id, "player_id": voter.id},
        "target-sid": {"room_id": room.id, "player_id": target.id},
        "afk-sid": {"room_id": room.id, "player_id": afk_voter.id},
        "spectator-sid": {"room_id": room.id, "player_id": spectator.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()
    vote_player = sio.handlers["/"]["vote_player"]

    spectator_vote = await vote_player(
        "spectator-sid", {"targetPlayerId": target.id, "action": "kick"}
    )
    assert spectator_vote == {"ok": False, "error": "Spectators cannot vote"}
    assert target.kick_votes == set()

    spectator_target = await vote_player(
        "voter-sid", {"targetPlayerId": spectator.id, "action": "kick"}
    )
    assert spectator_target == {
        "ok": False,
        "error": "Spectators cannot be moderation targets",
    }
    assert spectator.kick_votes == set()

    first_vote = await vote_player(
        "voter-sid", {"targetPlayerId": target.id, "action": "afk"}
    )
    assert first_vote == {"ok": True, "action": "afk", "executed": False}

    # AFK players remain eligible. The spectator does not raise the threshold
    # beyond two votes from the three connected non-spectator players.
    second_vote = await vote_player(
        "afk-sid", {"targetPlayerId": target.id, "action": "afk"}
    )
    assert second_vote == {"ok": True, "action": "afk", "executed": True}
    assert target.is_afk is True

@pytest.mark.asyncio
async def test_votes_removed_when_player_leaves_or_disconnects():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    p1 = room_manager.add_player(room, "P1")
    p2 = room_manager.add_player(room, "P2")
    p3 = room_manager.add_player(room, "P3")
    p1.sid, p2.sid, p3.sid = "p1-sid", "p2-sid", "p3-sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "p1-sid": {"room_id": room.id, "player_id": p1.id},
        "p2-sid": {"room_id": room.id, "player_id": p2.id},
        "p3-sid": {"room_id": room.id, "player_id": p3.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    vote_player = sio.handlers["/"]["vote_player"]
    disconnect = sio.handlers["/"]["disconnect"]

    # P1 votes to AFK P2
    await vote_player("p1-sid", {"targetPlayerId": p2.id, "action": "afk"})
    assert p1.id in p2.afk_votes

    # P1 disconnects -> P1's votes are removed from P2
    await disconnect("p1-sid")
    assert p1.id not in p2.afk_votes
