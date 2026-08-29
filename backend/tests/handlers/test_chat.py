import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, patch

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from tests.handlers.helpers import build_context
from app.game import DRAWING_SECONDS, MAX_GUESS_POINTS, MAX_HINT_SPEND, Game
from app.message_limits import MAX_CHAT_MESSAGE_LENGTH
from app.rooms import RoomManager
from app.prompts import MAX_PROMPT_LENGTH


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
        {"name": "After", "rounds": 5, "customPrompts": "apple\npear", "customPromptsOnly": True},
    )
    assert response["ok"] is True
    assert room.name == "After"
    assert room.rounds == 5
    assert room.custom_prompts == ["apple", "pear"]
    assert room.custom_prompts_only is True

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
    room.game = Game(turn_order=[drawer.id, guesser.id], prompt_pool=["panda"])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_prompt(drawer.id, "panda")

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
    room.game = Game(turn_order=[drawer.id, guesser.id], prompt_pool=["panda"])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_prompt(drawer.id, "panda")

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
        await guess("guesser-sid", {"text": "x" * MAX_PROMPT_LENGTH})
        await guess("guesser-sid", {"text": "x" * (MAX_PROMPT_LENGTH + 1)})

    submit_guess.assert_called_once_with(guesser.id, "x" * MAX_PROMPT_LENGTH)
    guess_hint.assert_called_once_with(guesser.id, "x" * MAX_PROMPT_LENGTH)
    assert any(
        call.args[0] == "chat_message"
        and call.args[1]["text"] == "x" * (MAX_PROMPT_LENGTH + 1)
        and call.kwargs.get("room") == room.id
        for call in sio.emit.await_args_list
    )

@pytest.mark.asyncio
async def test_simultaneous_final_guesses_end_turn_once():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    players = [room_manager.add_player(room, name) for name in ("Drawer", "One", "Two")]
    for index, player in enumerate(players):
        player.sid = f"sid-{index}"
    room.game = Game(turn_order=[player.id for player in players], rounds_total=2)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()
    room.game.set_phase_deadline(DRAWING_SECONDS)
    answer = room.game.prompt

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
    assert players[0].score == drawer_bonus
    assert [call.args[0] for call in sio.emit.await_args_list].count("turn_ended") == 1
    turn_ended_payload = next(
        call.args[1] for call in sio.emit.await_args_list if call.args[0] == "turn_ended"
    )
    assert {guess["nickname"] for guess in turn_ended_payload["guesses"]} == {"One", "Two"}
    assert all(0 <= guess["seconds"] <= DRAWING_SECONDS for guess in turn_ended_payload["guesses"])

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
        prompt_pool=["apple"],
    )
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_prompt(drawer.id, "apple")

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

    # Guesser buying a valid hint slot. Hints are bought on credit, so the
    # score does not move and the debt shows up in hint_spend instead.
    initial_score = guesser.score
    res = await buy_hint("guesser-sid", {"slot": 0})
    assert res["ok"] is True
    assert res["cost"] == 12
    assert res["hintSpend"] == 12
    assert guesser.score == initial_score
    assert room.game.hint_spend[guesser.id] == 12
    assert 0 in room.game.purchased_hints[guesser.id]

    # Buying does not touch any public state, so nothing is broadcast.
    emitted_events = [call.args[0] for call in sio.emit.await_args_list]
    assert "hint_revealed" in emitted_events
    assert "room_state" not in emitted_events

    # Guesser who has already committed the whole turn budget
    room.game.hint_spend[guesser.id] = MAX_HINT_SPEND
    res_broke = await buy_hint("guesser-sid", {"slot": 1})
    assert res_broke == {"ok": False, "error": "You've reached this turn's hint spend limit"}
    assert 1 not in room.game.purchased_hints[guesser.id]

    timer = timers.phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer

@pytest.mark.asyncio
async def test_a_correct_guess_is_credited_net_of_hints():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, hint_mode="purchase")
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"

    room.game = Game(
        turn_order=[drawer.id, guesser.id],
        hint_mode="purchase",
        prompt_pool=["apple"],
    )
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_prompt(drawer.id, "apple")
    room.game.set_phase_deadline(room.game.drawing_seconds)

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sessions = {
        "drawer-sid": {"room_id": room.id, "player_id": drawer.id},
        "guesser-sid": {"room_id": room.id, "player_id": guesser.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    buy_hint = sio.handlers["/"]["buy_hint"]
    assert (await buy_hint("guesser-sid", {"slot": 0}))["ok"] is True
    assert (await buy_hint("guesser-sid", {"slot": 1}))["ok"] is True
    spend = room.game.hint_spend[guesser.id]

    # The running total is reported on every purchase, privately.
    hint_revealed = [
        call.args[1] for call in sio.emit.await_args_list if call.args[0] == "hint_revealed"
    ]
    assert [payload["hintSpend"] for payload in hint_revealed] == [12, 12 + 24]
    assert guesser.score == 0

    await sio.handlers["/"]["guess"]("guesser-sid", {"text": "apple"})

    net = room.game.guess_points[guesser.id]
    assert net == MAX_GUESS_POINTS - spend
    assert guesser.score == net

    broadcast = next(
        call.args[1] for call in sio.emit.await_args_list if call.args[0] == "correct_guess"
    )
    assert broadcast["points"] == net

    private = next(
        call.args[1]
        for call in sio.emit.await_args_list
        if call.args[0] == "you_guessed_correctly"
    )
    assert private == {
        "prompt": "apple",
        "points": net,
        "basePoints": MAX_GUESS_POINTS,
        "hintSpend": spend,
    }

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
        prompt_pool=["banana"],
    )
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_prompt(drawer.id, "banana")

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sio.get_session = AsyncMock(return_value={"room_id": room.id, "player_id": guesser.id})
    sio.emit = AsyncMock()
    buy_wheel_letter = sio.handlers["/"]["buy_wheel_letter"]

    # Invalid letter format
    inv_res = await buy_wheel_letter("guesser-sid", {"letter": "123"})
    assert inv_res == {"ok": False, "error": "Invalid letter"}

    # Buy letter 'a' (present 3 times in 'banana')
    initial_score = guesser.score
    res = await buy_wheel_letter("guesser-sid", {"letter": "a"})
    assert res["ok"] is True
    assert res["found"] == 3
    assert guesser.score == initial_score
    assert res["hintSpend"] == room.game.hint_spend[guesser.id] > 0
    assert "a" in room.game.purchased_letters[guesser.id]

    # Attempting to buy the same letter again should fail
    dup_res = await buy_wheel_letter("guesser-sid", {"letter": "a"})
    assert dup_res == {"ok": False, "error": "Letter unavailable"}

    # Verify system message emission
    emitted = [call.args for call in sio.emit.await_args_list]
    chat_emits = [args for args in emitted if args[0] == "chat_message"]
    assert any(args[1]["text"].startswith("'A' -") for args in chat_emits)
    assert "room_state" not in [args[0] for args in emitted]

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
        prompt_pool=["panda"],
    )
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_prompt(drawer.id, "panda")
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

    # Guesser1 makes a close guess "pandas" (distance 1 from "panda")
    await guess("guesser1-sid", {"text": "pandas"})

    # Check emits for the close guess
    emitted_calls = sio.emit.await_args_list
    # Guesser1 should receive a close hint message to their specific sid
    close_hints = [
        call for call in emitted_calls
        if call.args[0] == "chat_message" and call.kwargs.get("to") == "guesser1-sid" and call.args[1].get("close")
    ]
    assert len(close_hints) == 1
    assert "very close" in close_hints[0].args[1]["text"]

    forwarded_near_misses = [
        call
        for call in emitted_calls
        if call.args[0] == "chat_message"
        and call.args[1].get("text") == "pandas"
        and call.kwargs.get("to") != "guesser1-sid"
    ]
    assert len(forwarded_near_misses) == 1
    assert forwarded_near_misses[0].kwargs["to"] == ["drawer-sid"]

    # Guesser1's guess text should NOT be broadcast to room.id or guesser2-sid
    room_broadcasts = [call for call in emitted_calls if call.kwargs.get("room") == room.id]
    assert not any(call.args[1].get("text") == "pandas" for call in room_broadcasts)

    sio.emit.reset_mock()

    # Guesser1 guesses correctly ("panda")
    await guess("guesser1-sid", {"text": "panda"})
    assert guesser1.id in room.game.correct_guessers
    correct_chat_emits = [
        call
        for call in sio.emit.await_args_list
        if call.args[0] == "chat_message" and call.args[1].get("correct") is True
    ]
    assert len(correct_chat_emits) == 1
    assert correct_chat_emits[0].kwargs["to"] == ["drawer-sid", "guesser1-sid"]

    sio.emit.reset_mock()

    # Guesser1 sends follow-up chat after guessing correctly
    await guess("guesser1-sid", {"text": "I got it!"})

    # The chat message should be restricted: True and sent only to in_the_know sids (drawer-sid and guesser1-sid)
    restricted_emits = [
        call for call in sio.emit.await_args_list
        if call.args[0] == "chat_message" and call.args[1].get("restricted") is True
    ]
    assert len(restricted_emits) == 1
    assert restricted_emits[0].kwargs["to"] == ["drawer-sid", "guesser1-sid"]
    assert "guesser2-sid" not in restricted_emits[0].kwargs["to"]

    timer = timers.phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer

@pytest.mark.asyncio
async def test_spectator_chat_is_restricted_and_solution_visible_when_enabled():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, spectators_see_prompt=True)
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    spectator = room_manager.add_player(room, "Spectator", is_spectator=True)
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"
    spectator.sid = "spec-sid"

    room.game = Game(turn_order=[drawer.id, guesser.id], rounds_total=1)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game._set_prompt("apple")

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sessions = {
        "drawer-sid": {"room_id": room.id, "player_id": drawer.id},
        "guesser-sid": {"room_id": room.id, "player_id": guesser.id},
        "spec-sid": {"room_id": room.id, "player_id": spectator.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    # Spectator masked prompt is unmasked because spectators_see_prompt=True
    spec_masked = room.game.masked_prompt(spectator.id, is_spectator=spectator.is_spectator, spectators_see_prompt=room.spectators_see_prompt)
    assert spec_masked == "apple"

    # Active guesser masked prompt is masked
    guesser_masked = room.game.masked_prompt(guesser.id, is_spectator=guesser.is_spectator, spectators_see_prompt=room.spectators_see_prompt)
    assert guesser_masked != "apple"

    # Spectator sends chat message
    guess = sio.handlers["/"]["guess"]
    await guess("spec-sid", {"text": "hello spectators!"})

    # Message is restricted and sent to drawer and spectator, NOT active guesser
    emitted = [call for call in sio.emit.await_args_list if call.args[0] == "chat_message"]
    assert len(emitted) == 1
    assert emitted[0].kwargs["to"] == ["drawer-sid", "spec-sid"]
    assert "guesser-sid" not in emitted[0].kwargs["to"]

    timer = timers.phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer


@pytest.mark.asyncio
async def test_empty_privileged_recipient_list_does_not_broadcast_close_guess():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    guesser.sid = "guesser-sid"

    room.game = Game(turn_order=[drawer.id, guesser.id], prompt_pool=["panda"])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_prompt(drawer.id, "panda")
    room.game.set_phase_deadline(DRAWING_SECONDS)

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": guesser.id}
    )
    sio.emit = AsyncMock()

    guess = sio.handlers["/"]["guess"]
    await guess("guesser-sid", {"text": "pandas"})

    chat_emits = [
        call for call in sio.emit.await_args_list if call.args[0] == "chat_message"
    ]
    assert len(chat_emits) == 2
    assert all(call.kwargs.get("to") == "guesser-sid" for call in chat_emits)
    assert all(call.kwargs.get("room") is None for call in chat_emits)

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


@pytest.mark.asyncio
async def test_pressure_room_credits_the_decayed_points():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Racy", scoring_mode="pressure")
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"
    room.state = "playing"
    room.game = Game(
        turn_order=[drawer.id, guesser.id],
        scoring_mode="pressure",
        drawing_seconds=90.0,
        prompt_pool=["panda"],
    )
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_prompt(drawer.id, "panda")
    room.game.remaining_seconds = lambda: 90.0 - 12.0

    opening_balance = guesser.score
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": guesser.id}
    )
    sio.emit = AsyncMock()

    await sio.handlers["/"]["guess"]("guesser-sid", {"text": "panda"})

    correct_guess = next(
        call for call in sio.emit.await_args_list if call.args[0] == "correct_guess"
    )
    assert correct_guess.args[1]["points"] == 235
    assert guesser.score == opening_balance + 235


def _guessing_room():
    """A room mid-turn where `guesser` may guess at "panda"."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room")
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    drawer.sid = "drawer-sid"
    guesser.sid = "guesser-sid"
    room.state = "playing"
    room.game = Game(turn_order=[drawer.id, guesser.id], prompt_pool=["panda"])
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_prompt(drawer.id, "panda")

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": guesser.id}
    )
    sio.emit = AsyncMock()
    return room, guesser, sio


def _guess_lines(sio, text):
    return [
        call
        for call in sio.emit.await_args_list
        if call.args[0] == "chat_message" and call.args[1].get("text") == text
    ]


@pytest.mark.asyncio
async def test_a_retried_guess_is_acknowledged_but_not_processed_twice():
    """The client resends a guess it never saw acknowledged. If the first copy
    did arrive, replaying it would double the chat line and the turn's counts."""
    room, guesser, sio = _guessing_room()
    guess = sio.handlers["/"]["guess"]

    assert await guess("guesser-sid", {"text": "otter", "id": 0}) is None
    assert await guess("guesser-sid", {"text": "otter", "id": 0}) is None

    assert len(_guess_lines(sio, "otter")) == 1
    assert room.game.wrong_guesses[guesser.id] == 1


@pytest.mark.asyncio
async def test_the_same_word_guessed_again_under_a_new_id_is_processed():
    room, guesser, sio = _guessing_room()
    guess = sio.handlers["/"]["guess"]

    await guess("guesser-sid", {"text": "otter", "id": 0})
    await guess("guesser-sid", {"text": "otter", "id": 1})

    assert len(_guess_lines(sio, "otter")) == 2
    assert room.game.wrong_guesses[guesser.id] == 2


@pytest.mark.asyncio
async def test_a_reconnected_client_restarts_its_guess_ids_without_being_deduped():
    """Ids are per connection. A reconnect starts them over, and judging the
    new counter against the old one would swallow a genuine guess."""
    room, guesser, sio = _guessing_room()
    guess = sio.handlers["/"]["guess"]

    await guess("guesser-sid", {"text": "otter", "id": 0})
    guesser.sid = "guesser-sid-2"
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": guesser.id}
    )
    await guess("guesser-sid-2", {"text": "badger", "id": 0})

    assert len(_guess_lines(sio, "badger")) == 1
    assert room.game.wrong_guesses[guesser.id] == 2


@pytest.mark.asyncio
async def test_a_guess_without_an_id_is_never_deduped():
    """A client that sends no id forgoes deduplication rather than losing
    guesses to an id it never claimed."""
    room, guesser, sio = _guessing_room()
    guess = sio.handlers["/"]["guess"]

    await guess("guesser-sid", {"text": "otter"})
    await guess("guesser-sid", {"text": "otter"})

    assert len(_guess_lines(sio, "otter")) == 2
    assert room.game.wrong_guesses[guesser.id] == 2


@pytest.mark.asyncio
async def test_a_near_miss_retry_repeats_neither_the_echo_nor_the_hint():
    """The near-miss path answers one guess with two messages to the guesser -
    their own line and the hint. A replayed guess would duplicate both."""
    room, guesser, sio = _guessing_room()
    guess = sio.handlers["/"]["guess"]

    await guess("guesser-sid", {"text": "pandas", "id": 4})
    await guess("guesser-sid", {"text": "pandas", "id": 4})

    to_guesser = [
        call
        for call in sio.emit.await_args_list
        if call.args[0] == "chat_message" and call.kwargs.get("to") == "guesser-sid"
    ]
    assert [call.args[1]["text"] for call in to_guesser] == [
        "pandas",
        '"pandas" is very close!',
    ]
    assert room.game.near_misses[guesser.id] == 1


@pytest.mark.asyncio
async def test_a_correct_guess_retried_is_answered_with_silence():
    """Scoring twice is already impossible - the guesser is in
    `correct_guessers` by then. What the retry would otherwise produce is a
    second chat line, echoing the answer back as ordinary post-guess chatter."""
    room, guesser, sio = _guessing_room()
    guess = sio.handlers["/"]["guess"]

    await guess("guesser-sid", {"text": "panda", "id": 7})
    scored = guesser.score
    sio.emit.reset_mock()

    await guess("guesser-sid", {"text": "panda", "id": 7})

    assert guesser.score == scored
    assert sio.emit.await_args_list == []


@pytest.mark.asyncio
async def test_an_invalid_guess_payload_is_refused_in_the_acknowledgement():
    room, _guesser, sio = _guessing_room()
    guess = sio.handlers["/"]["guess"]

    response = await guess("guesser-sid", {"text": "otter", "id": -1})

    assert response["ok"] is False
    assert response["field"] == "id"
    assert not _guess_lines(sio, "otter")

# ---------------------------------------------------------------------------
# Spectators and the hint economy (#334)
# ---------------------------------------------------------------------------
#
# A spectator has no seat in the guesser population, so it can never settle a
# hint debt against points it will never earn - which would make every reveal
# free, and would hand the prompt to a watcher in a room that deliberately
# keeps it from them.
#
# The guard is `is_turn_eligible`, and it holds because `_begin_drawing`
# snapshots the turn's participants from `room.seated_players()` only. That is
# an indirect guarantee: nothing in either purchase handler names spectators,
# so these tests exist to fail if the snapshot ever widens. They go through
# `_begin_drawing` rather than `Game.choose_prompt` for exactly that reason -
# without the snapshot, eligibility falls back to "anyone who is not the
# drawer", which a spectator passes.


async def _room_at_drawing_phase(hint_mode: str, prompt: str):
    """A room mid-turn with a drawer, a guesser, and a watcher who may not see."""
    room_manager = RoomManager()
    room = room_manager.create_room(
        name="Room",
        is_public=True,
        hint_mode=hint_mode,
        custom_prompts=[prompt],
        custom_prompts_only=True,
        spectators_see_prompt=False,
    )
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    spectator = room_manager.add_player(room, "Watcher", is_spectator=True)
    for player in (drawer, guesser, spectator):
        player.sid = f"{player.nickname.lower()}-sid"

    ctx = build_context(room_manager, None)
    sessions = {
        player.sid: {"room_id": room.id, "player_id": player.id}
        for player in (drawer, guesser, spectator)
    }
    ctx.sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))

    # `room.active_players()`, which is what both production start paths pass.
    # `_start_fresh_game` puts the caller's roster straight into `turn_order`
    # and only filters spectators out of the arrivals it reconciles, so handing
    # it `player_list()` would seat the watcher in the rotation.
    await ctx.game_flow._start_fresh_game(room, room.active_players())
    room.game.hint_mode = hint_mode
    room.game.force_prompt_choice()
    await ctx.game_flow._begin_drawing(room)
    # The precondition these tests rest on, stated rather than assumed: a
    # spectator that reached the rotation could be picked as drawer, and would
    # then be refused for being the drawer even under a widened snapshot -
    # passing for the wrong reason and covering nothing.
    assert spectator.id not in room.game.turn_order
    assert spectator.id != room.game.current_drawer
    # The seat the game is drawing for, not the one this helper happened to
    # create first: the turn order decides.
    drawer, guesser = (
        room.players[room.game.current_drawer],
        next(
            p
            for p in room.seated_players()
            if p.id != room.game.current_drawer
        ),
    )
    return ctx, room, drawer, guesser, spectator


@pytest.mark.asyncio
async def test_a_spectator_cannot_buy_a_hint_letter():
    ctx, room, _drawer, guesser, spectator = await _room_at_drawing_phase(
        "purchase", "volleyball"
    )
    buy_hint = ctx.sio.handlers["/"]["buy_hint"]

    assert (await buy_hint(guesser.sid, {"slot": 0}))["ok"] is True

    result = await buy_hint(spectator.sid, {"slot": 1})
    assert result == {"ok": False, "error": "Hint unavailable"}
    # The refusal has to leave no trace: an unpaid debt would settle against
    # points a spectator never earns, and a revealed slot is the prompt.
    assert spectator.id not in room.game.purchased_hints
    assert spectator.id not in room.game.hint_spend
    # Nothing revealed: what the spectator sees is what a stranger sees, while
    # the guesser's paid-for slot does show through - so the comparison is
    # testing the reveal machinery, not an inert prompt.
    assert room.game.masked_prompt(spectator.id) == room.game.masked_prompt("nobody")
    assert room.game.masked_prompt(guesser.id) != room.game.masked_prompt("nobody")

    ctx.timers.cancel_phase_timer(room.id)
    await ctx.timers.close()


@pytest.mark.asyncio
async def test_a_spectator_cannot_buy_a_wheel_letter():
    ctx, room, _drawer, guesser, spectator = await _room_at_drawing_phase(
        "wheel", "volleyball"
    )
    buy_wheel_letter = ctx.sio.handlers["/"]["buy_wheel_letter"]

    assert (await buy_wheel_letter(guesser.sid, {"letter": "l"}))["ok"] is True

    result = await buy_wheel_letter(spectator.sid, {"letter": "v"})
    assert result == {"ok": False, "error": "Letter unavailable"}
    assert spectator.id not in room.game.purchased_letters
    assert spectator.id not in room.game.hint_spend
    assert room.game.masked_prompt(spectator.id) == room.game.masked_prompt("nobody")
    assert room.game.masked_prompt(guesser.id) != room.game.masked_prompt("nobody")

    ctx.timers.cancel_phase_timer(room.id)
    await ctx.timers.close()
