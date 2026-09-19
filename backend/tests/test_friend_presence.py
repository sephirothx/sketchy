"""Friends told apart from the public presence list (#873, #878)."""
from __future__ import annotations

from uuid import UUID

import pytest

from app.rooms import RoomManager
from app.services.friend_presence import FriendPresence, FriendsUnavailable
from app.services.presence import (
    PresenceIdentity,
    PresenceIdentityCache,
    PresenceRegistry,
    build_snapshot,
)
from tests.test_presence import RecordingSio

ADA = "0199a000-0000-7000-8000-00000000000a"
BOB = "0199a000-0000-7000-8000-00000000000b"
CAT = "0199a000-0000-7000-8000-00000000000c"


class Friendships:
    def __init__(self, *pairs):
        self.pairs = {frozenset(pair) for pair in pairs}
        self.reads: list[str] = []
        self.fail = False

    async def __call__(self, user_id: UUID) -> set[UUID]:
        me = str(user_id)
        self.reads.append(me)
        if self.fail:
            raise RuntimeError("database down")
        return {UUID(o) for pair in self.pairs if me in pair for o in pair if o != me}


def stack(*pairs):
    registry = PresenceRegistry()
    room_manager = RoomManager()
    friendships = Friendships(*pairs)
    sio = RecordingSio()
    service = FriendPresence(
        sio, registry, PresenceIdentityCache(None), room_manager, friendships
    )
    return service, registry, room_manager, friendships, sio


def pushes(sio):
    return [(payload, room) for event, payload, room in sio.emitted if event == "friend_presence"]


async def test_a_friend_past_the_public_cap_is_still_online_and_invitable():
    """#878: 150 accounts online, the friend's name sorting last, so the
    public list's hundred leave them out; the friend answer does not."""
    service, registry, room_manager, _, _ = stack((ADA, BOB))
    names = {}
    for i in range(150):
        user_id = f"user-{i:03}"
        registry.note_socket_opened(f"sid-{i}", user_id)
        names[user_id] = PresenceIdentity(user_id, f"a{i:03}", "#4f9", False)
    registry.note_socket_opened("sid-ada", ADA)
    registry.note_socket_opened("sid-bob", BOB)
    names[ADA] = PresenceIdentity(ADA, "Ada", "#4f9", False)
    names[BOB] = PresenceIdentity(BOB, "zzz", "#4f9", False)
    # 152 arrivals at 25 reads a tick.
    for _ in range(7):
        await service.flush()

    public = build_snapshot(registry, room_manager, names, revision=1)
    assert BOB not in {entry.user_id for entry in public.entries}

    assert await service.online_friends(ADA) == [[BOB, "lobby"]]


async def test_coming_online_playing_and_leaving_are_each_told_once():
    service, registry, room_manager, _, sio = stack((ADA, BOB))
    registry.note_socket_opened("sid-ada", ADA)
    await service.flush()
    assert pushes(sio) == []  # Bob is not online to be told.

    registry.note_socket_opened("sid-bob", BOB)
    await service.flush()
    # Bob moved, so Ada hears; Ada did not, so Bob asks rather than hears.
    assert pushes(sio) == [([BOB, "lobby"], f"user:{ADA}")]
    sio.emitted.clear()

    await service.flush()
    assert pushes(sio) == []

    room = room_manager.create_room(name="Room", is_public=True)
    room_manager.add_player(room, "Bob", user_id=BOB, is_anonymous=False)
    await service.flush()
    assert pushes(sio) == [([BOB, "playing"], f"user:{ADA}")]
    sio.emitted.clear()

    registry.note_socket_closed("sid-bob")
    room.players.clear()
    await service.flush()
    assert pushes(sio) == [([BOB, None], f"user:{ADA}")]


async def test_a_stranger_is_never_told():
    service, registry, _, _, sio = stack((ADA, BOB))
    registry.note_socket_opened("sid-ada", ADA)
    registry.note_socket_opened("sid-cat", CAT)
    await service.flush()
    assert all(room != f"user:{CAT}" for _, room in pushes(sio))
    assert await service.online_friends(CAT) == []


async def test_friends_are_read_once_while_online_and_again_after_a_change():
    service, registry, _, friendships, _ = stack((ADA, BOB))
    registry.note_socket_opened("sid-ada", ADA)
    await service.flush()
    await service.online_friends(ADA)
    await service.online_friends(ADA)
    assert friendships.reads == [ADA]

    friendships.pairs.add(frozenset((ADA, CAT)))
    service.forget(ADA)
    registry.note_socket_opened("sid-cat", CAT)
    await service.flush()
    assert await service.online_friends(ADA) == [[CAT, "lobby"]]

    registry.note_socket_closed("sid-ada")
    await service.flush()
    assert ADA not in service._friends


async def test_an_unreadable_friend_list_is_retried_rather_than_told_as_empty():
    """A failed read is neither an empty answer nor a change marked told."""
    service, registry, _, friendships, sio = stack((ADA, BOB))
    registry.note_socket_opened("sid-ada", ADA)
    await service.flush()
    friendships.fail = True
    registry.note_socket_opened("sid-bob", BOB)
    await service.flush()
    assert pushes(sio) == []
    with pytest.raises(FriendsUnavailable):
        await service.online_friends(BOB)

    friendships.fail = False
    await service.flush()
    assert pushes(sio) == [([BOB, "lobby"], f"user:{ADA}")]
    assert await service.online_friends(ADA) == [[BOB, "lobby"]]


async def test_the_answer_is_what_was_told_so_later_pushes_apply_on_top():
    """A client replaces its map with the answer and applies pushes after it.
    That is only sound if the answer is never newer than a push still to
    come: Bob leaving after the last tick is told by the next one, not by the
    answer, and Cat arriving is told by push rather than lost."""
    service, registry, _, friendships, sio = stack((ADA, BOB), (ADA, CAT))
    registry.note_socket_opened("sid-ada", ADA)
    registry.note_socket_opened("sid-bob", BOB)
    await service.flush()
    sio.emitted.clear()

    registry.note_socket_closed("sid-bob")
    registry.note_socket_opened("sid-cat", CAT)
    online = {friend: status for friend, status in await service.online_friends(ADA)}
    assert online == {BOB: "lobby"}

    await service.flush()
    for (friend, status), room in pushes(sio):
        assert room == f"user:{ADA}"
        if status is None:
            online.pop(friend, None)
        else:
            online[friend] = status
    assert online == {CAT: "lobby"}


async def test_a_push_names_a_status_and_never_a_room():
    service, registry, room_manager, _, sio = stack((ADA, BOB))
    registry.note_socket_opened("sid-ada", ADA)
    registry.note_socket_opened("sid-bob", BOB)
    room = room_manager.create_room(name="Room", is_public=True)
    room_manager.add_player(room, "Bob", user_id=BOB, is_anonymous=False)
    await service.flush()
    for payload, _ in pushes(sio):
        assert room.id not in repr(payload) and room.code not in repr(payload)
    assert room.id not in repr(await service.online_friends(ADA))


async def test_a_burst_of_arrivals_is_read_a_bounded_number_per_tick(monkeypatch):
    """A restart brings everybody back at once; their lists are spread over
    ticks rather than read in one, and nobody is skipped."""
    monkeypatch.setattr("app.services.friend_presence.READS_PER_TICK", 2)
    service, registry, _, friendships, sio = stack((ADA, BOB))
    extra = [f"0199a000-0000-7000-8000-0000000001{i:02}" for i in range(4)]
    for i, user_id in enumerate([ADA, BOB, *extra]):
        registry.note_socket_opened(f"sid-{i}", user_id)

    await service.flush()
    assert len(friendships.reads) == 2
    for _ in range(3):
        await service.flush()
    assert sorted(friendships.reads) == sorted([ADA, BOB, *extra])
    # Whichever of the pair was read second, the other was online to hear.
    assert pushes(sio)
