"""The public room list, as a feed rather than an answer to a question.

Every case here is one the four-second poll never had to think about, because
a poll re-sends the whole truth every time and cannot be wrong for longer than
one interval. A feed can: a delta that never went out, a revision that moved
without a broadcast, a diff that calls a room unchanged when a field moved.
Those are the ones worth pinning.
"""
from __future__ import annotations

import pytest

from app.rooms import RoomManager
from app.services.lobby_rooms import (
    EMPTY_ROOMS,
    RoomsSnapshot,
    build_rooms_snapshot,
    diff_rooms,
)
from app.services.presence import (
    LobbyBroadcaster,
    PresenceIdentityCache,
    PresenceRegistry,
)


def snapshot(rooms, revision=1) -> RoomsSnapshot:
    return RoomsSnapshot(revision=revision, rooms=tuple(rooms))


def a_room(room_id: str, **fields) -> dict:
    return {"id": room_id, "name": f"Room {room_id}", "playerCount": 1, **fields}


# --- building -------------------------------------------------------------


def test_the_snapshot_is_what_the_endpoint_would_answer():
    manager = RoomManager()
    public = manager.create_room(name="Open", is_public=True)
    manager.create_room(name="Hidden", is_public=False)

    built = build_rooms_snapshot(manager, revision=4)
    assert built.revision == 4
    assert [room["id"] for room in built.rooms] == [public.id]
    # Not merely the same ids: the same serializer, so the two surfaces cannot
    # start describing rooms differently.
    assert list(built.rooms) == manager.list_public_rooms()


def test_a_private_room_never_enters_the_feed():
    manager = RoomManager()
    manager.create_room(name="Hidden", is_public=False)
    assert build_rooms_snapshot(manager, revision=1).rooms == ()


def test_the_payload_copies_rather_than_sharing_the_room_dicts():
    manager = RoomManager()
    manager.create_room(name="Open", is_public=True)
    built = build_rooms_snapshot(manager, revision=1)
    payload = built.payload()
    payload["rooms"][0]["name"] = "mutated"
    assert built.rooms[0]["name"] == "Open"


# --- diffing --------------------------------------------------------------


def test_a_diff_against_itself_is_empty():
    built = snapshot([a_room("a"), a_room("b")])
    assert diff_rooms(built, built).is_empty


def test_opened_closed_and_changed_are_told_apart():
    before = snapshot([a_room("a"), a_room("b")], revision=1)
    after = snapshot([a_room("a", playerCount=5), a_room("c")], revision=2)

    delta = diff_rooms(before, after)
    assert [room["id"] for room in delta.opened] == ["c"]
    assert delta.closed == ("b",)
    assert [room["id"] for room in delta.changed] == ["a"]
    assert delta.revision == 2
    assert not delta.is_empty


def test_any_field_moving_makes_a_room_changed():
    """Diffed on the whole summary, not a chosen few fields.

    `to_public_summary` carries twenty-two of them and grows; a diff that
    listed the ones worth watching would silently stop reporting the next one
    somebody adds.
    """
    before = snapshot([a_room("a")])
    for field, value in (
        ("playerCount", 7),
        ("name", "Renamed"),
        ("newFieldNobodyHasAddedYet", True),
    ):
        after = snapshot([a_room("a", **{field: value})], revision=2)
        assert [room["id"] for room in diff_rooms(before, after).changed] == ["a"], field


def test_the_first_delta_off_an_empty_feed_opens_everything():
    after = snapshot([a_room("a"), a_room("b")], revision=1)
    delta = diff_rooms(EMPTY_ROOMS, after)
    assert {room["id"] for room in delta.opened} == {"a", "b"}
    assert delta.closed == () and delta.changed == ()


def test_applying_a_delta_agrees_with_the_snapshot_it_should_equal():
    """The #493 contract, in Python: patching must not drift from replacing."""
    before = snapshot([a_room("a"), a_room("b")], revision=1)
    after = snapshot([a_room("b", playerCount=9), a_room("c")], revision=2)
    delta = diff_rooms(before, after)

    patched = {room["id"]: room for room in before.rooms}
    for room in (*delta.opened, *delta.changed):
        patched[room["id"]] = room
    for room_id in delta.closed:
        del patched[room_id]

    assert patched == {room["id"]: room for room in after.rooms}


# --- the feed on the channel ----------------------------------------------


def broadcaster_for(manager: RoomManager) -> LobbyBroadcaster:
    class RecordingSio:
        def __init__(self):
            self.emitted = []

        async def emit(self, event, payload=None, room=None, **_):
            self.emitted.append((event, payload, room))

    return LobbyBroadcaster(
        RecordingSio(),
        PresenceRegistry(),
        PresenceIdentityCache(None),
        manager,
        environ={},
    )


def rooms_frames(caster) -> list:
    return [frame for frame in caster._sio.emitted if frame[0] == "lobby_rooms_changed"]


@pytest.mark.asyncio
async def test_a_tick_with_no_room_news_says_nothing():
    caster = broadcaster_for(RoomManager())
    await caster.flush()
    assert rooms_frames(caster) == []
    assert caster.rooms_revision == 0


@pytest.mark.asyncio
async def test_a_new_room_is_broadcast_once():
    manager = RoomManager()
    caster = broadcaster_for(manager)
    room = manager.create_room(name="Open", is_public=True)

    await caster.flush()
    frames = rooms_frames(caster)
    assert len(frames) == 1
    event, payload, channel = frames[0]
    assert channel == "lobby"
    assert [entry["id"] for entry in payload["opened"]] == [room.id]
    assert payload["revision"] == 1 == caster.rooms_revision

    # Nothing moved since, so the next tick is silent and the revision holds.
    await caster.flush()
    assert len(rooms_frames(caster)) == 1
    assert caster.rooms_revision == 1


@pytest.mark.asyncio
async def test_the_two_feeds_do_not_move_each_other():
    """Separate revisions on purpose: a room filling up must not re-send who is
    online, and somebody signing in must not re-send the rooms."""
    manager = RoomManager()
    caster = broadcaster_for(manager)
    manager.create_room(name="Open", is_public=True)
    await caster.flush()
    assert caster.rooms_revision == 1 and caster.revision == 0

    caster._registry.note_socket_opened("sid-a", "user-1")
    await caster.flush()
    assert caster.rooms_revision == 1
    assert len(rooms_frames(caster)) == 1


@pytest.mark.asyncio
async def test_a_watcher_is_handed_the_revision_already_broadcast():
    """The acknowledgement is fresh, but stamped with what the channel is at.

    A snapshot stamped one ahead would make the *next* delta look like a gap
    to this client and to nobody else; stamped behind, an upsert it already
    holds arrives again, which changes nothing.
    """
    manager = RoomManager()
    caster = broadcaster_for(manager)
    manager.create_room(name="Open", is_public=True)
    await caster.flush()

    later = manager.create_room(name="Second", is_public=True)
    handed = caster.rooms_for_watcher()
    assert handed.revision == caster.rooms_revision == 1
    # Fresh: the room created after the last tick is already in it.
    assert later.id in {room["id"] for room in handed.rooms}


@pytest.mark.asyncio
async def test_a_room_going_private_leaves_the_feed_as_a_close():
    manager = RoomManager()
    caster = broadcaster_for(manager)
    room = manager.create_room(name="Open", is_public=True)
    await caster.flush()

    room.is_public = False
    await caster.flush()
    _, payload, _ = rooms_frames(caster)[-1]
    assert payload["closed"] == [room.id]
    assert payload["revision"] == 2
