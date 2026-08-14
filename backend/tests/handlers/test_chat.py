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
from app.rooms import DrawingRecapEntry, STARTING_SCORE, RoomManager
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
async def test_host_can_update_waiting_room_settings_and_chat():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Before", is_public=True, max_players=4)
    host = room_manager.add_player(room, "Host")
    host.sid = "host-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": host.id})
    sio.emit = AsyncMock()

    settings = await sio.handlers["/"]["get_room_settings"]("host-sid", {})
    assert settings["ok"] is True
    assert settings["settings"]["name"] == "Before"

    response = await sio.handlers["/"]["update_room_settings"](
        "host-sid",
        {"name": "After", "rounds": 5, "customWords": "apple\npear", "customWordsOnly": True},
    )
    assert response["ok"] is True
    assert room.name == "After"
    assert room.rounds == 5
    assert room.custom_words == ["apple", "pear"]
    assert room.custom_words_only is True

    response = await sio.handlers["/"]["update_room_settings"](
        "host-sid", {"drawingSeconds": 300, "maxPlayers": 16},
    )
    assert response["ok"] is True
    assert room.drawing_seconds == 300
    assert room.max_players == 16

    chat = await sio.handlers["/"]["send_chat"]("host-sid", {"text": "Ready?"})
    assert chat["ok"] is True
    assert any(call.args[0] == "chat_message" and call.args[1]["text"] == "Ready?" for call in sio.emit.await_args_list)

@pytest.mark.asyncio
async def test_waiting_chat_rejects_oversized_message_without_broadcast():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room")
    host = room_manager.add_player(room, "Host")
    host.sid = "host-sid"
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": host.id}
    )
    sio.emit = AsyncMock()

    send_chat = sio.handlers["/"]["send_chat"]
    accepted = await send_chat("host-sid", {"text": "x" * MAX_CHAT_MESSAGE_LENGTH})
    rejected = await send_chat(
        "host-sid",
        {"text": "x" * (MAX_CHAT_MESSAGE_LENGTH + 1)},
    )

    assert accepted == {"ok": True}
    assert rejected["ok"] is False
    chat_messages = [
        call for call in sio.emit.await_args_list if call.args[0] == "chat_message"
    ]
    assert len(chat_messages) == 1
    assert len(chat_messages[0].args[1]["text"]) == MAX_CHAT_MESSAGE_LENGTH

@pytest.mark.asyncio
async def test_active_message_limit_rejects_before_processing_or_broadcast():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room")
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"
    guesser.is_afk = True
    room.state = "playing"
    room.game = Game(turn_order=[drawer.id, guesser.id], word_pool=["panda"])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_word(drawer.id, "panda")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": guesser.id}
    )
    sio.emit = AsyncMock()
    guess = sio.handlers["/"]["guess"]

    with (
        patch.object(Game, "submit_guess") as submit_guess,
        patch.object(Game, "guess_hint") as guess_hint,
    ):
        rejected = await guess(
            "guesser-sid",
            {"text": "x" * (MAX_CHAT_MESSAGE_LENGTH + 1)},
        )

    assert rejected["ok"] is False
    submit_guess.assert_not_called()
    guess_hint.assert_not_called()
    sio.emit.assert_not_awaited()
    assert guesser.is_afk is True

    sio.emit.reset_mock()
    with (
        patch.object(Game, "submit_guess") as submit_guess,
        patch.object(Game, "guess_hint") as guess_hint,
    ):
        accepted = await guess(
            "guesser-sid",
            {"text": "x" * MAX_CHAT_MESSAGE_LENGTH},
        )

    assert accepted is None
    submit_guess.assert_not_called()
    guess_hint.assert_not_called()
    assert any(
        call.args[0] == "chat_message"
        and call.args[1]["text"] == "x" * MAX_CHAT_MESSAGE_LENGTH
        and call.kwargs.get("room") == room.id
        for call in sio.emit.await_args_list
    )

@pytest.mark.asyncio
async def test_only_messages_within_word_limit_are_processed_as_guesses():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room")
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"
    room.state = "playing"
    room.game = Game(turn_order=[drawer.id, guesser.id], word_pool=["panda"])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_word(drawer.id, "panda")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": guesser.id}
    )
    sio.emit = AsyncMock()
    guess = sio.handlers["/"]["guess"]

    with (
        patch.object(Game, "submit_guess", return_value=(False, 0)) as submit_guess,
        patch.object(Game, "guess_hint", return_value=None) as guess_hint,
    ):
        await guess("guesser-sid", {"text": "x" * MAX_WORD_LENGTH})
        await guess("guesser-sid", {"text": "x" * (MAX_WORD_LENGTH + 1)})

    submit_guess.assert_called_once_with(guesser.id, "x" * MAX_WORD_LENGTH)
    guess_hint.assert_called_once_with(guesser.id, "x" * MAX_WORD_LENGTH)
    assert any(
        call.args[0] == "chat_message"
        and call.args[1]["text"] == "x" * (MAX_WORD_LENGTH + 1)
        and call.kwargs.get("room") == room.id
        for call in sio.emit.await_args_list
    )

@pytest.mark.asyncio
async def test_simultaneous_final_guesses_end_round_once():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    players = [room_manager.add_player(room, name) for name in ("Drawer", "One", "Two")]
    for index, player in enumerate(players):
        player.sid = f"sid-{index}"
    room.game = Game(turn_order=[player.id for player in players], rounds_total=2)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_word_choice()
    room.game.set_phase_deadline(DRAWING_SECONDS)
    answer = room.game.word

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sessions = {
        player.sid: {"room_id": room.id, "player_id": player.id}
        for player in players
    }

    async def get_session(sid):
        return sessions[sid]

    async def yielding_emit(*args, **kwargs):
        await asyncio.sleep(0)

    sio.get_session = AsyncMock(side_effect=get_session)
    sio.emit = AsyncMock(side_effect=yielding_emit)
    guess = sio.handlers["/"]["guess"]

    await asyncio.gather(
        guess(players[1].sid, {"text": answer}),
        guess(players[2].sid, {"text": answer}),
    )

    drawer_bonus = sum(room.game.guess_points.values())
    assert players[0].score == STARTING_SCORE + drawer_bonus
    assert [call.args[0] for call in sio.emit.await_args_list].count("round_ended") == 1
    round_ended_payload = next(
        call.args[1] for call in sio.emit.await_args_list if call.args[0] == "round_ended"
    )
    assert {guess["nickname"] for guess in round_ended_payload["guesses"]} == {"One", "Two"}
    assert all(0 <= guess["seconds"] <= DRAWING_SECONDS for guess in round_ended_payload["guesses"])

    timer = timers.phase_timers.pop(room.id)
    timer.cancel()
    with suppress(asyncio.CancelledError):
        await timer

@pytest.mark.asyncio
async def test_buy_hint_purchase_mode():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, hint_mode="purchase")
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"

    room.game = Game(
        turn_order=[drawer.id, guesser.id],
        hint_mode="purchase",
        word_pool=["apple"],
    )
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_word(drawer.id, "apple")

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sessions = {
        "drawer-sid": {"room_id": room.id, "player_id": drawer.id},
        "guesser-sid": {"room_id": room.id, "player_id": guesser.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()
    buy_hint = sio.handlers["/"]["buy_hint"]

    # Drawer attempting to buy a hint should fail
    drawer_res = await buy_hint("drawer-sid", {"slot": 0})
    assert drawer_res == {"ok": False, "error": "Hint unavailable"}

    # Guesser buying a valid hint slot
    initial_score = guesser.score
    res = await buy_hint("guesser-sid", {"slot": 0})
    assert res["ok"] is True
    assert res["cost"] == 12
    assert guesser.score == initial_score - 12
    assert 0 in room.game.purchased_hints[guesser.id]

    # Check hint_revealed event emission
    emitted_events = [call.args[0] for call in sio.emit.await_args_list]
    assert "hint_revealed" in emitted_events

    # Guesser with insufficient points
    guesser.score = 5
    res_broke = await buy_hint("guesser-sid", {"slot": 1})
    assert res_broke == {"ok": False, "error": "Not enough points"}

    timer = timers.phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer

@pytest.mark.asyncio
async def test_buy_wheel_letter():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, hint_mode="wheel")
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    guesser.sid = "guesser-sid"
    drawer.sid = "drawer-sid"

    room.game = Game(
        turn_order=[drawer.id, guesser.id],
        hint_mode="wheel",
        word_pool=["banana"],
    )
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_word(drawer.id, "banana")

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": guesser.id})
    sio.emit = AsyncMock()
    buy_wheel_letter = sio.handlers["/"]["buy_wheel_letter"]

    # Invalid letter format
    inv_res = await buy_wheel_letter("guesser-sid", {"letter": "123"})
    assert inv_res == {"ok": False, "error": "Invalid letter"}

    # Buy letter 'a' (present 3 times in 'banana')
    guesser.score = 500
    initial_score = guesser.score
    res = await buy_wheel_letter("guesser-sid", {"letter": "a"})
    assert res["ok"] is True
    assert res["found"] == 3
    assert guesser.score < initial_score
    assert "a" in room.game.purchased_letters[guesser.id]

    # Attempting to buy the same letter again should fail
    dup_res = await buy_wheel_letter("guesser-sid", {"letter": "a"})
    assert dup_res == {"ok": False, "error": "Letter unavailable"}

    # Verify system message emission
    emitted = [call.args for call in sio.emit.await_args_list]
    chat_emits = [args for args in emitted if args[0] == "chat_message"]
    assert any("You bought 'A'" in args[1]["text"] for args in chat_emits)

    timer = timers.phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer

@pytest.mark.asyncio
async def test_near_miss_guess_privacy_and_restricted_chat():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    guesser1 = room_manager.add_player(room, "Guesser1")
    guesser2 = room_manager.add_player(room, "Guesser2")
    drawer.sid = "drawer-sid"
    guesser1.sid = "guesser1-sid"
    guesser2.sid = "guesser2-sid"

    room.game = Game(
        turn_order=[drawer.id, guesser1.id, guesser2.id],
        word_pool=["panda"],
    )
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_word(drawer.id, "panda")
    room.game.set_phase_deadline(DRAWING_SECONDS)

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sessions = {
        "drawer-sid": {"room_id": room.id, "player_id": drawer.id},
        "guesser1-sid": {"room_id": room.id, "player_id": guesser1.id},
        "guesser2-sid": {"room_id": room.id, "player_id": guesser2.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()
    guess = sio.handlers["/"]["guess"]

    # Guesser1 makes a near-miss guess "pandas" (distance 1 from "panda")
    await guess("guesser1-sid", {"text": "pandas"})

    # Check emits for near-miss
    emitted_calls = sio.emit.await_args_list
    # Guesser1 should receive a close hint message to their specific sid
    close_hints = [
        call for call in emitted_calls
        if call.args[0] == "chat_message" and call.kwargs.get("to") == "guesser1-sid" and call.args[1].get("close")
    ]
    assert len(close_hints) == 1
    assert "very close" in close_hints[0].args[1]["text"]

    # Guesser1's guess text should NOT be broadcast to room.id or guesser2-sid
    room_broadcasts = [call for call in emitted_calls if call.kwargs.get("room") == room.id]
    assert not any(call.args[1].get("text") == "pandas" for call in room_broadcasts)

    sio.emit.reset_mock()

    # Guesser1 guesses correctly ("panda")
    await guess("guesser1-sid", {"text": "panda"})
    assert guesser1.id in room.game.correct_guessers

    sio.emit.reset_mock()

    # Guesser1 sends follow-up chat after guessing correctly
    await guess("guesser1-sid", {"text": "I got it!"})

    # The chat message should be restricted: True and sent only to in_the_know sids (drawer-sid and guesser1-sid)
    restricted_emits = [
        call for call in sio.emit.await_args_list
        if call.args[0] == "chat_message" and call.args[1].get("restricted") is True
    ]
    assert len(restricted_emits) == 2
    target_sids = {call.kwargs.get("to") for call in restricted_emits}
    assert target_sids == {"drawer-sid", "guesser1-sid"}
    assert "guesser2-sid" not in target_sids

    timer = timers.phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer

@pytest.mark.asyncio
async def test_spectator_chat_is_restricted_and_solution_visible_when_enabled():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, spectators_see_solution=True)
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    spectator = room_manager.add_player(room, "Spectator", is_spectator=True)
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"
    spectator.sid = "spec-sid"

    room.game = Game(turn_order=[drawer.id, guesser.id], rounds_total=1)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game._set_word("apple")

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sessions = {
        "drawer-sid": {"room_id": room.id, "player_id": drawer.id},
        "guesser-sid": {"room_id": room.id, "player_id": guesser.id},
        "spec-sid": {"room_id": room.id, "player_id": spectator.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    # Spectator masked word is unmasked because spectators_see_solution=True
    spec_masked = room.game.masked_word(spectator.id, is_spectator=spectator.is_spectator, spectators_see_solution=room.spectators_see_solution)
    assert spec_masked == "apple"

    # Active guesser masked word is masked
    guesser_masked = room.game.masked_word(guesser.id, is_spectator=guesser.is_spectator, spectators_see_solution=room.spectators_see_solution)
    assert guesser_masked != "apple"

    # Spectator sends chat message
    guess = sio.handlers["/"]["guess"]
    await guess("spec-sid", {"text": "hello spectators!"})

    # Message is restricted and sent to drawer and spectator, NOT active guesser
    emitted = [call for call in sio.emit.await_args_list if call.args[0] == "chat_message"]
    target_sids = {call.kwargs.get("to") for call in emitted}
    assert target_sids == {"drawer-sid", "spec-sid"}
    assert "guesser-sid" not in target_sids

    timer = timers.phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer

@pytest.mark.asyncio
async def test_chatting_removes_afk_status():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    p1 = room_manager.add_player(room, "P1")
    p2 = room_manager.add_player(room, "P2")
    p1.sid, p2.sid = "p1-sid", "p2-sid"
    p1.is_afk = True

    room.state = "playing"
    room.game = Game(turn_order=[p1.id, p2.id], rounds_total=1)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "p1-sid": {"room_id": room.id, "player_id": p1.id},
        "p2-sid": {"room_id": room.id, "player_id": p2.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    guess = sio.handlers["/"]["guess"]
    await guess("p1-sid", {"text": "hello chat"})
    assert p1.is_afk is False
