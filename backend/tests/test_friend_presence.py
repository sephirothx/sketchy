"""Friends answered apart from the public presence list (#873, #878)."""
from __future__ import annotations

from uuid import UUID

import pytest

from app.rooms import RoomManager
from app.services.friend_presence import FriendPresence
from app.services.presence import PresenceIdentity, PresenceRegistry, build_snapshot

ADA = "0199a000-0000-7000-8000-00000000000a"
BOB = "0199a000-0000-7000-8000-00000000000b"
CAT = "0199a000-0000-7000-8000-00000000000c"


class Friendships:
    def __init__(self, *pairs):
        self.pairs = {frozenset(pair) for pair in pairs}
        self.reads: list[str] = []
        self.fail = False
        self.during_read = None

    async def __call__(self, user_id: UUID) -> set[UUID]:
        me = str(user_id)
        self.reads.append(me)
        if self.during_read:
            self.during_read()
        if self.fail:
            raise RuntimeError("database down")
        return {UUID(o) for pair in self.pairs if me in pair for o in pair if o != me}


def stack(*pairs):
    registry = PresenceRegistry()
    room_manager = RoomManager()
    friendships = Friendships(*pairs)
    return FriendPresence(registry, room_manager, friendships), registry, room_manager, friendships


async def test_a_friend_past_the_public_cap_is_still_online_and_invitable():
    """#878: 150 accounts online, the friend's name sorting last, so the
    public list's hundred leave them out; the friend answer does not."""
    service, registry, room_manager, _ = stack((ADA, BOB))
    names = {}
    for i in range(150):
        user_id = f"user-{i:03}"
        registry.note_socket_opened(f"sid-{i}", user_id)
        names[user_id] = PresenceIdentity(user_id, f"a{i:03}", "#4f9", False)
    registry.note_socket_opened("sid-ada", ADA)
    registry.note_socket_opened("sid-bob", BOB)
    names[ADA] = PresenceIdentity(ADA, "Ada", "#4f9", False)
    names[BOB] = PresenceIdentity(BOB, "zzz", "#4f9", False)

    public = build_snapshot(registry, room_manager, names, revision=1)
    assert BOB not in {entry.user_id for entry in public.entries}

    assert await service.online_friends(ADA) == [[BOB, "lobby"]]


async def test_the_answer_is_live_every_time_it_is_asked():
    service, registry, room_manager, _ = stack((ADA, BOB), (ADA, CAT))
    registry.note_socket_opened("sid-ada", ADA)
    assert await service.online_friends(ADA) == []

    registry.note_socket_opened("sid-bob", BOB)
    registry.note_socket_opened("sid-cat", CAT)
    room = room_manager.create_room(name="Room", is_public=True)
    room_manager.add_player(room, "Cat", user_id=CAT, is_anonymous=False)
    assert await service.online_friends(ADA) == [[BOB, "lobby"], [CAT, "playing"]]

    registry.note_socket_closed("sid-bob")
    assert await service.online_friends(ADA) == [[CAT, "playing"]]


async def test_a_stranger_is_never_named():
    service, registry, _, _ = stack((ADA, BOB))
    registry.note_socket_opened("sid-ada", ADA)
    registry.note_socket_opened("sid-cat", CAT)
    assert await service.online_friends(CAT) == []
    assert await service.online_friends(ADA) == []


async def test_polling_reads_the_database_once_per_connection():
    service, registry, _, friendships = stack((ADA, BOB))
    registry.note_socket_opened("sid-ada", ADA)
    for _ in range(5):
        await service.online_friends(ADA)
    assert friendships.reads == [ADA]

    friendships.pairs.add(frozenset((ADA, CAT)))
    registry.note_socket_opened("sid-cat", CAT)
    service.forget(ADA)  # friends_changed
    assert await service.online_friends(ADA) == [[CAT, "lobby"]]
    assert friendships.reads == [ADA, ADA]


async def test_an_account_that_goes_offline_during_the_read_is_not_cached():
    """`forget` runs on the last socket closing; a read that finishes after
    it must not leave an entry nothing will drop."""
    service, registry, _, friendships = stack((ADA, BOB))
    registry.note_socket_opened("sid-ada", ADA)

    def ada_leaves():
        registry.note_socket_closed("sid-ada")
        service.forget(ADA)

    friendships.during_read = ada_leaves
    await service.online_friends(ADA)
    assert ADA not in service._friends


async def test_an_unreadable_friend_list_raises_and_is_not_remembered():
    service, registry, _, friendships = stack((ADA, BOB))
    registry.note_socket_opened("sid-ada", ADA)
    registry.note_socket_opened("sid-bob", BOB)
    friendships.fail = True
    with pytest.raises(RuntimeError):
        await service.online_friends(ADA)
    friendships.fail = False
    assert await service.online_friends(ADA) == [[BOB, "lobby"]]


async def test_the_answer_names_a_status_and_never_a_room():
    service, registry, room_manager, _ = stack((ADA, BOB))
    registry.note_socket_opened("sid-ada", ADA)
    registry.note_socket_opened("sid-bob", BOB)
    room = room_manager.create_room(name="Room", is_public=True)
    room_manager.add_player(room, "Bob", user_id=BOB, is_anonymous=False)
    answer = repr(await service.online_friends(ADA))
    assert room.id not in answer and room.code not in answer
