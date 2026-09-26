"""A mixed-language room through its commands (#1182)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import socketio

from app.handlers import register_all_handlers as register_handlers
from app.rooms import RoomManager
from tests.handlers.helpers import SessionStore, StubPromptListRepo


def _server(room_manager, repo):
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, prompt_list_repo=repo)
    sessions = SessionStore()
    sio.get_session = AsyncMock(side_effect=sessions.get)
    sio.save_session = AsyncMock(side_effect=sessions.save)
    sio.enter_room = AsyncMock()
    sio.leave_room = AsyncMock()
    sio.emit = AsyncMock()
    return sio, sessions


def _standard_stub():
    """Two prompts spelled in every room language, as Standard is."""
    return StubPromptListRepo(
        ["dog", "cat"],
        concept_ids={"dog": "c-dog", "cat": "c-cat"},
        translations={
            "dog": {"en": "dog", "de": "Hund", "fr": "chien", "es": "perro", "it": "cane", "nl": "hond", "pt": "cão"},
            "cat": {"en": "cat", "de": "Katze", "fr": "chat", "es": "gato", "it": "gatto", "nl": "kat", "pt": "gato"},
        },
        revision_ids=("revision-standard",),
    )


async def _create(sio, sessions, *, seat="de", **extra):
    await sessions.save("host-sid", {"user_id": "user-host"})
    return await sio.handlers["/"]["create_room"](
        "host-sid",
        {"nickname": "Greta", "promptLanguage": "mul", "seatLanguage": seat, **extra},
    )


async def test_a_mixed_room_refuses_quick_prompts_against_their_field():
    room_manager = RoomManager()
    sio, sessions = _server(room_manager, _standard_stub())

    answer = await _create(sio, sessions, customPrompts="Pikachu")

    assert answer["ok"] is False
    assert answer["errorCode"] == "mixed_room_custom_prompts"
    assert answer["field"] == "customPrompts"
    assert room_manager.rooms == {}


async def test_a_mixed_room_refuses_a_list_in_one_language_by_name():
    room_manager = RoomManager()
    sio, sessions = _server(room_manager, StubPromptListRepo(["Hund"], language="de"))

    answer = await _create(sio, sessions)

    assert answer["ok"] is False
    assert answer["errorCode"] == "mixed_room_list_unsupported"
    assert answer["field"] == "promptListSlugs"


async def test_each_seat_plays_the_drawing_in_the_language_it_joined_with():
    room_manager = RoomManager()
    sio, sessions = _server(room_manager, _standard_stub())
    created = await _create(sio, sessions, seat="de")
    assert created["ok"] is True, created
    room = room_manager.get_room(created["roomId"])
    assert room.prompt_language == "mul"
    await sessions.save("guest-sid", {"user_id": "user-guest"})
    joined = await sio.handlers["/"]["join_room"](
        "guest-sid", {"code": room.code, "nickname": "Jean", "seatLanguage": "fr"}
    )
    assert joined["ok"] is True, joined
    host = next(p for p in room.players.values() if p.nickname == "Greta")
    guest = next(p for p in room.players.values() if p.nickname == "Jean")
    assert (room.seat_language(host), room.seat_language(guest)) == ("de", "fr")

    assert (await sio.handlers["/"]["start_game"]("host-sid", None))["ok"] is True
    game = room.game
    assert game.seat_languages[host.id] == "de"
    assert game.seat_languages[guest.id] == "fr"
    drawer = room.players[game.current_drawer]
    guesser = guest if drawer is host else host
    drawer_language = room.seat_language(drawer)
    [offer] = [
        call.args[1]
        for call in sio.emit.await_args_list
        if call.args[0] == "your_prompt_choices"
    ]
    spelled = {"de": {"Hund", "Katze"}, "fr": {"chien", "chat"}}[drawer_language]
    assert set(offer["choices"]) == spelled

    chosen = await sio.handlers["/"]["select_prompt"](
        drawer.sid, {"index": 0, "turnId": offer["turnId"]}
    )
    assert chosen["ok"] is True
    concept = game.prompt_key
    english = {"c-dog": "dog", "c-cat": "cat"}[concept]
    # The guesser plays the drawing in their own language, and English -
    # nobody's language here - names it too.
    assert game.prompt_for(guesser.id) != game.prompt
    started = {
        call.kwargs.get("to"): call.args[1]
        for call in sio.emit.await_args_list
        if call.args[0] == "turn_started"
    }
    guesser_word = game.prompt_for(guesser.id)
    # Tiles for the guesser's own spelling, not the drawer's.
    assert started[guesser.sid]["maskedPrompt"].split("  ")[-1] == str(len(guesser_word))
    answer = await sio.handlers["/"]["guess"](guesser.sid, {"text": english})
    assert answer.get("ok", True) is True, answer
    assert guesser.id in game.correct_guessers
    # What they are told they guessed is their own language's word.
    assert game.prompt_for(guesser.id) == guesser_word
    from app.presenters import guessed_receipt

    assert guessed_receipt(game, guesser.id)["prompt"] == guesser_word
