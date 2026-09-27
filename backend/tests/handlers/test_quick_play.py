"""Quick play, decided by the server (#931, R-UX-14).

One command: the fullest public room that is waiting in the caller's language
with a seat free, or a new public room on the payload's own defaults. It used
to be a walk the client ran over the lobby's room list, one `join_room` per
candidate - a round trip each, a dependency on a list that had to have
arrived, and a room per presser when several pressed at the same moment.
"""

import asyncio
from unittest.mock import AsyncMock

import socketio

from app.handlers import register_all_handlers as register_handlers
from app.handlers import rooms as room_handlers
from app.rooms import RoomManager
from tests.handlers.helpers import SessionStore


def server(room_manager):
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    sessions = SessionStore()
    sio.get_session = AsyncMock(side_effect=sessions.get)
    sio.save_session = AsyncMock(side_effect=sessions.save)
    sio.enter_room = AsyncMock()
    sio.leave_room = AsyncMock()
    sio.disconnect = AsyncMock()
    sio.emit = AsyncMock()
    return sio, ctx


def waiting_room(room_manager, *, is_public=True, language="en", seats=1, max_players=8):
    room = room_manager.create_room(
        name="Room", is_public=is_public, max_players=max_players, prompt_language=language
    )
    for index in range(seats):
        player = room_manager.add_player(room, f"Host{index}")
        player.sid = f"host-sid-{room.id}-{index}"
    return room


def press(sio, sid="guest-sid", **extra):
    return sio.handlers["/"]["quick_play"](sid, {"nickname": "Marta", **extra})


def players(room) -> int:
    return len([p for p in room.players.values() if not p.is_spectator])


async def test_one_press_takes_a_seat_in_the_fullest_waiting_room():
    room_manager = RoomManager()
    emptier = waiting_room(room_manager, seats=1)
    fuller = waiting_room(room_manager, seats=3)
    sio, _ = server(room_manager)

    answer = await press(sio)

    assert answer["ok"] is True and answer["created"] is False
    assert answer["roomId"] == fuller.id and answer["code"] == fuller.code
    assert players(fuller) == 4 and players(emptier) == 1


async def test_a_game_under_way_a_private_room_and_another_language_are_all_passed_over():
    room_manager = RoomManager()
    playing = waiting_room(room_manager, seats=4)
    playing.state = "playing"
    private = waiting_room(room_manager, is_public=False, seats=3)
    italian = waiting_room(room_manager, language="it", seats=2)
    sio, _ = server(room_manager)

    answer = await press(sio)

    assert answer["ok"] is True and answer["created"] is True, "none of them would do"
    opened = room_manager.get_room(answer["roomId"])
    assert opened.is_public and opened.prompt_language == "en"
    assert players(playing) == 4 and players(private) == 3 and players(italian) == 2
    # The room it opens is the one the next press finds.
    again = await press(sio, sid="second-sid")
    assert again["roomId"] == opened.id and again["created"] is False


async def test_a_full_room_is_never_offered_and_never_overfilled():
    room_manager = RoomManager()
    room = waiting_room(room_manager, seats=2, max_players=2)
    sio, _ = server(room_manager)

    answer = await press(sio)

    assert answer["ok"] is True and answer["created"] is True
    assert players(room) == 2


async def test_a_room_that_starts_between_being_picked_and_sat_in_is_skipped(monkeypatch):
    """The host can start the game while the entry is being made. That is the
    next room's turn, not the caller's refusal - and no extra round trip."""
    room_manager = RoomManager()
    starting = waiting_room(room_manager, seats=4)
    spare = waiting_room(room_manager, seats=2)
    sio, ctx = server(room_manager)
    real_release = ctx.game_flow.release_other_seats

    async def host_starts_meanwhile(sid, **kwargs):
        starting.state = "playing"
        return await real_release(sid, **kwargs)

    monkeypatch.setattr(ctx.game_flow, "release_other_seats", host_starts_meanwhile)

    answer = await press(sio)

    assert answer["ok"] is True and answer["roomId"] == spare.id
    assert players(starting) == 4, "the room that started was left alone"


async def test_presses_at_the_same_moment_fill_rooms_rather_than_opening_one_each():
    """The shape a shared link produces: many first visitors, one button. Each
    press used to read the same empty list and open its own room."""
    room_manager = RoomManager()
    sio, _ = server(room_manager)
    pressers = 20

    answers = await asyncio.gather(
        *(press(sio, sid=f"sid-{index}") for index in range(pressers))
    )

    assert all(answer["ok"] for answer in answers)
    rooms = list(room_manager.rooms.values())
    assert len(rooms) == 3, "twenty seats at eight a room"
    assert sorted(players(room) for room in rooms) == [4, 8, 8]
    assert sum(answer["created"] for answer in answers) == len(rooms)


async def test_a_press_in_another_language_opens_its_own_room_beside_one_being_opened():
    room_manager = RoomManager()
    sio, _ = server(room_manager)

    english, italian = await asyncio.gather(
        press(sio, sid="en-sid"), press(sio, sid="it-sid", promptLanguage="it")
    )

    assert english["roomId"] != italian["roomId"]
    assert room_manager.get_room(english["roomId"]).prompt_language == "en"
    assert room_manager.get_room(italian["roomId"]).prompt_language == "it"


async def test_the_room_it_opens_is_the_servers_own_standard_room():
    room_manager = RoomManager()
    sio, _ = server(room_manager)

    answer = await press(sio, colorblindSafeColors=True, promptLanguage="fr")

    room = room_manager.get_room(answer["roomId"])
    assert room.is_public and room.max_players == 8 and room.rounds == 3
    assert room.prompt_language == "fr" and room.color_mode == "colorblind_safe"
    assert room.name, "the server names it"


async def test_a_press_that_cannot_be_named_is_refused_rather_than_seated(monkeypatch):
    room_manager = RoomManager()
    waiting_room(room_manager)
    sio, _ = server(room_manager)

    async def refuse(*_args, **_kwargs):
        raise room_handlers.IdentityError(
            "Somebody is using that name", room_handlers.ErrorCode.NAME_IN_USE
        )

    monkeypatch.setattr(room_handlers, "resolve_identity", refuse)

    answer = await press(sio)

    assert answer["ok"] is False and answer["errorCode"] == "name_in_use"
    assert sum(players(room) for room in room_manager.rooms.values()) == 1


async def test_a_visitor_with_no_session_is_refused_rather_than_opening_a_room():
    """Joining is open to a socket with no account; opening a room is not -
    the ceilings are keyed on one - and it must say so rather than raise."""
    room_manager = RoomManager()
    sio, _ = server(room_manager)
    sio.get_session = AsyncMock(return_value={})

    answer = await press(sio)

    assert answer["ok"] is False and answer["errorCode"] == "account_required"
    assert "cookies" in answer["error"]
    assert room_manager.rooms == {}


async def test_a_language_or_a_name_the_room_could_not_be_opened_under_is_refused_at_the_door():
    room_manager = RoomManager()
    sio, _ = server(room_manager)

    unknown = await press(sio, promptLanguage="klingon")
    illegal = await press(sio, nickname="no spaces allowed!")
    blank = await press(sio, nickname="  ")

    assert unknown["ok"] is False and unknown["errorCode"] == "invalid_payload"
    assert illegal["ok"] is False and illegal["errorCode"] == "invalid_payload"
    # A blank one is refused where every entry refuses it, by name.
    assert blank["ok"] is False and blank["errorCode"] == "invalid_nickname"
    assert room_manager.rooms == {}


async def test_a_language_tag_in_another_case_still_finds_its_rooms():
    room_manager = RoomManager()
    waiting = waiting_room(room_manager, language="it", seats=2)
    sio, _ = server(room_manager)

    answer = await press(sio, promptLanguage="IT")

    assert answer["roomId"] == waiting.id, "the tag is canonical before it is matched"


async def test_a_room_whose_seats_are_all_taken_is_not_offered_even_if_somebody_is_away():
    """`add_player` counts seats, not the players the game is waiting on: a
    seat held through a disconnect grace or an AFK mark is still taken."""
    room_manager = RoomManager()
    room = waiting_room(room_manager, seats=2, max_players=2)
    list(room.players.values())[0].connected = False
    list(room.players.values())[1].is_afk = True
    sio, ctx = server(room_manager)

    # Never offered, so no seat is asked for and refused on the way past.
    assert room_handlers._quick_play_candidates(ctx, "en") == []

    answer = await press(sio)
    assert answer["created"] is True and answer["roomId"] != room.id
    assert players(room) == 2


async def test_a_mixed_language_room_is_the_fallback_before_opening_one():
    """A mixed room (#1182) plays everyone in their own language, so it is
    worth a seat - after every room in the player's own, however full."""
    room_manager = RoomManager()
    mixed = waiting_room(room_manager, language="mul", seats=5)
    german = waiting_room(room_manager, language="de", seats=1)
    sio, _ = server(room_manager)

    first = await press(sio, promptLanguage="de")
    assert first["roomId"] == german.id

    german.state = "playing"
    second = await press(sio, sid="other-sid", nickname="Jonas", promptLanguage="de")
    assert second["ok"] is True and second["created"] is False
    assert second["roomId"] == mixed.id
    seat = next(p for p in mixed.players.values() if p.nickname == "Jonas")
    assert mixed.seat_language(seat) == "de"
