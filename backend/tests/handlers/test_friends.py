"""Friends from inside the game: who may let whom into a room.

The two commands that seat somebody are the point of this file. An invitation
is no weaker than pasting the room code, which any seated player can already
do - so anyone may send one. Pulling yourself into a room nobody invited you to
is new, so it is held to the host.

And on every path: no room code reaches a caller who has not been seated.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from app.rooms import RoomManager
from app.services.friends import FriendshipRefused
from tests.handlers.helpers import SessionStore

pytestmark = pytest.mark.asyncio


class StubFriendService:
    """Answers the two questions the handlers ask, without a database."""

    def __init__(self, friends=(), blocked=(), refuse=None):
        self._friends = {frozenset(pair) for pair in friends}
        self._blocked = {frozenset(pair) for pair in blocked}
        self._refuse = refuse
        self.requested: list[tuple[str, str]] = []

    async def are_friends(self, a, b):
        return frozenset({str(a), str(b)}) in self._friends

    async def is_blocked_pair(self, a, b):
        return frozenset({str(a), str(b)}) in self._blocked

    async def request(self, a, b):
        if self._refuse:
            raise FriendshipRefused(self._refuse)
        self.requested.append((str(a), str(b)))


def build_stack(room_manager, **kwargs):
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager, **kwargs)
    sessions = SessionStore()
    sio.get_session = AsyncMock(side_effect=sessions.get)
    sio.save_session = AsyncMock(side_effect=sessions.save)
    sio.enter_room = AsyncMock()
    sio.leave_room = AsyncMock()
    sio.disconnect = AsyncMock()
    sio.emit = AsyncMock()
    return ctx, sio, sessions


ADA = "0199a000-0000-7000-8000-00000000000a"
BOB = "0199a000-0000-7000-8000-00000000000b"
CAT = "0199a000-0000-7000-8000-00000000000c"


async def seat_host(room_manager, room, user_id, nickname="Host"):
    player = room_manager.add_player(
        room, nickname, user_id=user_id, is_anonymous=False
    )
    player.is_host = True
    return player


def emitted(sio, event):
    return [
        call for call in sio.emit.await_args_list
        if call.args and call.args[0] == event
    ]


def timeline(sio, answer=None):
    entries = [
        [call.args[0], call.args[1] if len(call.args) > 1 else None]
        for call in sio.emit.await_args_list
    ]
    return json.dumps([answer] + entries, default=str)


# --- add_friend -----------------------------------------------------------


async def test_adding_a_friend_names_a_seat_rather_than_an_account():
    """R-ROOM-07 stays put: the client says who it can see, not who they are."""
    room_manager = RoomManager()
    friends = StubFriendService()
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Studio", is_public=True)
    me = await seat_host(room_manager, room, ADA, "Ada")
    me.sid = "sid-ada"
    them = room_manager.add_player(room, "Bob", user_id=BOB, is_anonymous=False)
    await sessions.save("sid-ada", {"room_id": room.id, "player_id": me.id})

    answer = await sio.handlers["/"]["add_friend"](
        "sid-ada", {"playerId": them.id}
    )

    assert answer["ok"] is True
    assert friends.requested == [(ADA, BOB)]


async def test_adding_a_seat_that_is_not_there_answers_like_one_that_is():
    """The same answer for 'no such seat' and 'that is you', as reports do."""
    room_manager = RoomManager()
    friends = StubFriendService()
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Studio", is_public=True)
    me = await seat_host(room_manager, room, ADA, "Ada")
    me.sid = "sid-ada"
    await sessions.save("sid-ada", {"room_id": room.id, "player_id": me.id})

    for player_id in ("no-such-seat", me.id):
        answer = await sio.handlers["/"]["add_friend"](
            "sid-ada", {"playerId": player_id}
        )
        assert answer == {"ok": True}
    assert friends.requested == []


async def test_a_guest_is_told_to_register_rather_than_silently_ignored():
    room_manager = RoomManager()
    friends = StubFriendService()
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Studio", is_public=True)
    me = room_manager.add_player(room, "Guesty", user_id=ADA, is_anonymous=True)
    me.sid = "sid-guest"
    them = room_manager.add_player(room, "Bob", user_id=BOB, is_anonymous=False)
    await sessions.save("sid-guest", {"room_id": room.id, "player_id": me.id})

    answer = await sio.handlers["/"]["add_friend"](
        "sid-guest", {"playerId": them.id}
    )

    assert answer["ok"] is False
    assert "Create an account" in answer["error"]
    assert friends.requested == []


# --- invite_friend --------------------------------------------------------


async def test_an_invitation_carries_no_way_to_name_the_room():
    room_manager = RoomManager()
    friends = StubFriendService(friends=[(ADA, BOB)])
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Secret Studio", is_public=False)
    me = await seat_host(room_manager, room, ADA, "Ada")
    me.sid = "sid-ada"
    await sessions.save("sid-ada", {"room_id": room.id, "player_id": me.id})

    answer = await sio.handlers["/"]["invite_friend"](
        "sid-ada", {"friendUserId": BOB}
    )

    assert answer["ok"] is True
    sent = emitted(sio, "friend_invite_received")
    assert len(sent) == 1
    assert sent[0].kwargs["room"] == f"user:{BOB}"
    body = sent[0].args[1]
    assert set(body) == {"fromUserId", "displayName", "inviteToken", "expiresIn"}
    # The whole point: an invitation is a capability to *ask*, not to enter.
    flat = timeline(sio, answer)
    assert room.code not in flat
    assert room.id not in flat
    assert room.name not in flat


async def test_only_a_friend_can_be_invited():
    room_manager = RoomManager()
    friends = StubFriendService()
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Studio", is_public=True)
    me = await seat_host(room_manager, room, ADA, "Ada")
    me.sid = "sid-ada"
    await sessions.save("sid-ada", {"room_id": room.id, "player_id": me.id})

    answer = await sio.handlers["/"]["invite_friend"](
        "sid-ada", {"friendUserId": BOB}
    )

    assert answer["ok"] is False
    assert emitted(sio, "friend_invite_received") == []


async def test_a_block_stops_an_invitation_even_if_a_friendship_survived():
    room_manager = RoomManager()
    friends = StubFriendService(friends=[(ADA, BOB)], blocked=[(ADA, BOB)])
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Studio", is_public=True)
    me = await seat_host(room_manager, room, ADA, "Ada")
    me.sid = "sid-ada"
    await sessions.save("sid-ada", {"room_id": room.id, "player_id": me.id})

    answer = await sio.handlers["/"]["invite_friend"](
        "sid-ada", {"friendUserId": BOB}
    )

    assert answer["ok"] is False
    assert emitted(sio, "friend_invite_received") == []


# --- join_friend_room -----------------------------------------------------


async def test_a_friend_of_the_host_may_join_a_private_room_uninvited():
    room_manager = RoomManager()
    friends = StubFriendService(friends=[(ADA, BOB)])
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Secret Studio", is_public=False)
    host = await seat_host(room_manager, room, ADA, "Ada")
    host.sid = "sid-ada"
    await sessions.save("sid-bob", {"user_id": BOB})

    answer = await sio.handlers["/"]["join_friend_room"](
        "sid-bob", {"friendUserId": ADA, "nickname": "Bob"}
    )

    assert answer["ok"] is True
    assert answer["roomId"] == room.id
    # Seated, and only now told the code - which every seated player knows.
    assert answer["code"] == room.code
    assert any(player.user_id == BOB for player in room.players.values())


async def test_a_friend_of_an_occupant_may_not_walk_into_the_hosts_room():
    """The consent that is missing: the host never met this person."""
    room_manager = RoomManager()
    friends = StubFriendService(friends=[(BOB, CAT)])
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Secret Studio", is_public=False)
    host = await seat_host(room_manager, room, ADA, "Ada")
    host.sid = "sid-ada"
    occupant = room_manager.add_player(room, "Bob", user_id=BOB, is_anonymous=False)
    occupant.sid = "sid-bob"
    await sessions.save("sid-cat", {"user_id": CAT})

    answer = await sio.handlers["/"]["join_friend_room"](
        "sid-cat", {"friendUserId": BOB, "nickname": "Cat"}
    )

    assert answer["ok"] is False
    assert "invite" in answer["error"]
    assert not any(player.user_id == CAT for player in room.players.values())
    assert room.code not in timeline(sio, answer)


async def test_an_invitation_from_an_occupant_is_enough():
    """Because they could have pasted the code instead, and this is tighter."""
    room_manager = RoomManager()
    friends = StubFriendService(friends=[(BOB, CAT)])
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Secret Studio", is_public=False)
    host = await seat_host(room_manager, room, ADA, "Ada")
    host.sid = "sid-ada"
    occupant = room_manager.add_player(room, "Bob", user_id=BOB, is_anonymous=False)
    occupant.sid = "sid-bob"
    await sessions.save("sid-bob", {"room_id": room.id, "player_id": occupant.id})
    await sessions.save("sid-cat", {"user_id": CAT})

    invited = await sio.handlers["/"]["invite_friend"](
        "sid-bob", {"friendUserId": CAT}
    )
    token = emitted(sio, "friend_invite_received")[0].args[1]["inviteToken"]

    answer = await sio.handlers["/"]["join_friend_room"](
        "sid-cat", {"friendUserId": BOB, "inviteToken": token, "nickname": "Cat"}
    )

    assert invited["ok"] is True
    assert answer["ok"] is True
    assert any(player.user_id == CAT for player in room.players.values())


async def test_an_invitation_cannot_be_spent_twice():
    room_manager = RoomManager()
    friends = StubFriendService(friends=[(ADA, BOB)])
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Studio", is_public=True)
    host = await seat_host(room_manager, room, ADA, "Ada")
    host.sid = "sid-ada"
    await sessions.save("sid-ada", {"room_id": room.id, "player_id": host.id})
    await sessions.save("sid-bob", {"user_id": BOB})

    await sio.handlers["/"]["invite_friend"]("sid-ada", {"friendUserId": BOB})
    token = emitted(sio, "friend_invite_received")[0].args[1]["inviteToken"]
    first = await sio.handlers["/"]["join_friend_room"](
        "sid-bob", {"friendUserId": ADA, "inviteToken": token, "nickname": "Bob"}
    )
    second = await sio.handlers["/"]["join_friend_room"](
        "sid-bob", {"friendUserId": ADA, "inviteToken": token, "nickname": "Bob"}
    )

    assert first["ok"] is True
    assert second["ok"] is False
    assert "expired" in second["error"]


async def test_an_invitation_addressed_to_somebody_else_is_not_a_way_in():
    room_manager = RoomManager()
    friends = StubFriendService(friends=[(ADA, BOB), (ADA, CAT)])
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Secret Studio", is_public=False)
    host = await seat_host(room_manager, room, ADA, "Ada")
    host.sid = "sid-ada"
    await sessions.save("sid-ada", {"room_id": room.id, "player_id": host.id})
    await sessions.save("sid-cat", {"user_id": CAT})

    await sio.handlers["/"]["invite_friend"]("sid-ada", {"friendUserId": BOB})
    token = emitted(sio, "friend_invite_received")[0].args[1]["inviteToken"]

    # Cat is a friend of the host, so she could join anyway - but not by
    # presenting a token that was addressed to Bob.
    answer = await sio.handlers["/"]["join_friend_room"](
        "sid-cat", {"friendUserId": ADA, "inviteToken": token, "nickname": "Cat"}
    )
    assert answer["ok"] is False
    assert "expired" in answer["error"]


async def test_joining_a_friend_who_is_not_in_a_game_says_so():
    room_manager = RoomManager()
    friends = StubFriendService(friends=[(ADA, BOB)])
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    await sessions.save("sid-bob", {"user_id": BOB})

    answer = await sio.handlers["/"]["join_friend_room"](
        "sid-bob", {"friendUserId": ADA, "nickname": "Bob"}
    )

    assert answer["ok"] is False
    assert "not in a game" in answer["error"]


async def test_a_stranger_is_refused_the_same_way_a_non_friend_is():
    """So the command cannot be used to test whether somebody unfriended you."""
    room_manager = RoomManager()
    friends = StubFriendService()
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Studio", is_public=True)
    host = await seat_host(room_manager, room, ADA, "Ada")
    host.sid = "sid-ada"
    await sessions.save("sid-bob", {"user_id": BOB})

    not_a_friend = await sio.handlers["/"]["join_friend_room"](
        "sid-bob", {"friendUserId": ADA, "nickname": "Bob"}
    )
    stranger = await sio.handlers["/"]["join_friend_room"](
        "sid-bob", {"friendUserId": CAT, "nickname": "Bob"}
    )

    assert not_a_friend == stranger
    assert not_a_friend["ok"] is False


async def test_a_signed_out_socket_cannot_join_a_friend():
    room_manager = RoomManager()
    friends = StubFriendService(friends=[(ADA, BOB)])
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    await sessions.save("sid-nobody", {"user_id": None})

    answer = await sio.handlers["/"]["join_friend_room"](
        "sid-nobody", {"friendUserId": ADA, "nickname": "Nobody"}
    )

    assert answer["ok"] is False
    assert "Sign in" in answer["error"]


async def test_joining_a_friend_releases_the_seat_this_socket_already_held():
    """R-ROOM-08 comes from _seat_in_room, which is why it is shared."""
    room_manager = RoomManager()
    friends = StubFriendService(friends=[(ADA, BOB)])
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    first = room_manager.create_room(name="First", is_public=True)
    elsewhere = room_manager.add_player(
        first, "Bob", user_id=BOB, is_anonymous=False
    )
    elsewhere.sid = "sid-bob"
    second = room_manager.create_room(name="Second", is_public=False)
    host = await seat_host(room_manager, second, ADA, "Ada")
    host.sid = "sid-ada"
    await sessions.save("sid-bob", {"user_id": BOB})

    answer = await sio.handlers["/"]["join_friend_room"](
        "sid-bob", {"friendUserId": ADA, "nickname": "Bob"}
    )

    assert answer["ok"] is True
    assert answer["roomId"] == second.id
    assert room_manager.get_room(first.id) is None, "the first room leaked"
    await ctx.timers.close()


async def test_add_friend_names_only_the_outcomes_that_changed_something():
    """Three answers, and a fourth that covers everything else on purpose.

    Already friends, already asked, and a block all read as "nothing to do",
    so the command cannot be used to tell those apart from inside a room.
    """
    from app.services.friends import FriendshipOutcome

    class Outcomes(StubFriendService):
        def __init__(self, outcome):
            super().__init__()
            self._outcome = outcome

        async def request(self, a, b):
            return self._outcome

    for outcome, expected in (
        (FriendshipOutcome.CREATED, "created"),
        (FriendshipOutcome.ACCEPTED, "accepted"),
        (FriendshipOutcome.UNCHANGED, "unchanged"),
        (FriendshipOutcome.IGNORED, "unchanged"),
    ):
        room_manager = RoomManager()
        ctx, sio, sessions = build_stack(
            room_manager, friend_service=Outcomes(outcome)
        )
        room = room_manager.create_room(name="Studio", is_public=True)
        me = await seat_host(room_manager, room, ADA, "Ada")
        me.sid = "sid-ada"
        them = room_manager.add_player(room, "Bob", user_id=BOB, is_anonymous=False)
        await sessions.save("sid-ada", {"room_id": room.id, "player_id": me.id})

        answer = await sio.handlers["/"]["add_friend"](
            "sid-ada", {"playerId": them.id}
        )

        assert answer == {"ok": True, "status": expected}
        # Told only where something moved. A notice on a request that was
        # quietly dropped would be the tell that silence exists to avoid.
        notices = emitted(sio, "friends_changed")
        assert bool(notices) is (
            outcome in (FriendshipOutcome.CREATED, FriendshipOutcome.ACCEPTED)
        )


# --- the paths that refuse -------------------------------------------------


async def test_every_friend_command_needs_the_service_behind_it():
    """Built without a database in most of the suite, and it must say so."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    assert ctx.friend_service is None
    room = room_manager.create_room(name="Studio", is_public=True)
    me = await seat_host(room_manager, room, ADA, "Ada")
    me.sid = "sid-ada"
    them = room_manager.add_player(room, "Bob", user_id=BOB, is_anonymous=False)
    await sessions.save("sid-ada", {"room_id": room.id, "player_id": me.id})
    await sessions.save("sid-bob", {"user_id": BOB})

    for command, payload, sid in (
        ("add_friend", {"playerId": them.id}, "sid-ada"),
        ("invite_friend", {"friendUserId": BOB}, "sid-ada"),
        ("join_friend_room", {"friendUserId": ADA}, "sid-bob"),
    ):
        answer = await sio.handlers["/"][command](sid, payload)
        assert answer["ok"] is False
        assert "unavailable" in answer["error"]


async def test_a_friend_command_from_outside_a_room_is_refused():
    room_manager = RoomManager()
    friends = StubFriendService(friends=[(ADA, BOB)])
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    await sessions.save("sid-ada", {"user_id": ADA})

    for command, payload in (
        ("add_friend", {"playerId": "whoever"}),
        ("invite_friend", {"friendUserId": BOB}),
    ):
        answer = await sio.handlers["/"][command]("sid-ada", payload)
        assert answer == {"ok": False, "error": "Not in this room"}


async def test_a_guest_cannot_invite_even_a_friend():
    room_manager = RoomManager()
    friends = StubFriendService(friends=[(ADA, BOB)])
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Studio", is_public=True)
    me = room_manager.add_player(room, "Guesty", user_id=ADA, is_anonymous=True)
    me.sid = "sid-guest"
    await sessions.save("sid-guest", {"room_id": room.id, "player_id": me.id})

    answer = await sio.handlers["/"]["invite_friend"](
        "sid-guest", {"friendUserId": BOB}
    )

    assert answer["ok"] is False
    assert "Create an account" in answer["error"]
    assert emitted(sio, "friend_invite_received") == []


async def test_a_seat_with_no_account_cannot_be_friended():
    """R-HIST-10 keeps its cookieless seat; there is simply nobody to ask."""
    room_manager = RoomManager()
    friends = StubFriendService()
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Studio", is_public=True)
    me = await seat_host(room_manager, room, ADA, "Ada")
    me.sid = "sid-ada"
    nobody = room_manager.add_player(room, "Nobody", user_id=None)
    await sessions.save("sid-ada", {"room_id": room.id, "player_id": me.id})

    answer = await sio.handlers["/"]["add_friend"](
        "sid-ada", {"playerId": nobody.id}
    )

    assert answer == {"ok": True}
    assert friends.requested == []


async def test_a_full_friends_list_is_reported_from_inside_a_room():
    room_manager = RoomManager()
    friends = StubFriendService(refuse="Your friends list is full (200).")
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)
    room = room_manager.create_room(name="Studio", is_public=True)
    me = await seat_host(room_manager, room, ADA, "Ada")
    me.sid = "sid-ada"
    them = room_manager.add_player(room, "Bob", user_id=BOB, is_anonymous=False)
    await sessions.save("sid-ada", {"room_id": room.id, "player_id": me.id})

    answer = await sio.handlers["/"]["add_friend"](
        "sid-ada", {"playerId": them.id}
    )

    assert answer["ok"] is False
    assert "full" in answer["error"]


async def test_a_malformed_friend_payload_is_refused_before_anything_else():
    room_manager = RoomManager()
    friends = StubFriendService()
    ctx, sio, sessions = build_stack(room_manager, friend_service=friends)

    for command, payload in (
        ("add_friend", {"playerId": "seat", "extra": 1}),
        ("invite_friend", {}),
        ("join_friend_room", {"friendUserId": "u", "code": "ABC123"}),
    ):
        answer = await sio.handlers["/"][command]("sid-any", payload)
        assert answer["ok"] is False
