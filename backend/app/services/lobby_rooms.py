"""The public room list, as something the lobby is told rather than asks for.

Every visible lobby used to re-fetch the whole list every four seconds whether
or not anything had moved, which is what #462 was filed about: a hundred
lobbies is twenty-five requests a second before anybody plays, and each one
crosses the session middleware and a database read to resolve a cookie. A 304
makes the *body* free; it does not make the request free.

So the list rides the channel the lobby already opens for presence, in the same
shape: a snapshot when you join, a delta when something moves, and a monotonic
revision so a client that missed one can tell and ask again. The two feeds are
separate events with separate revisions on purpose - a room filling up should
not re-send who is online, and somebody signing in should not re-send the
rooms.

Diffed rather than marked dirty, for the reason the presence feed gives at
length: a room summary changes from a dozen places (a join, a leave, a game
starting, a settings edit, a code retiring), and a `mark_dirty` at each is one
more thing every future writer has to know about. Rebuilding and comparing
cannot be forgotten.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.rooms import RoomManager


@dataclass(frozen=True, slots=True)
class RoomsSnapshot:
    """The public rooms at one revision, keyed by id for diffing."""

    revision: int
    rooms: tuple[dict, ...]

    def payload(self) -> dict:
        return {"revision": self.revision, "rooms": [dict(r) for r in self.rooms]}


@dataclass(frozen=True, slots=True)
class RoomsDelta:
    """What changed between two snapshots of the list."""

    revision: int
    opened: tuple[dict, ...]
    closed: tuple[str, ...]
    changed: tuple[dict, ...]

    @property
    def is_empty(self) -> bool:
        return not (self.opened or self.closed or self.changed)

    def payload(self) -> dict:
        return {
            "revision": self.revision,
            "opened": [dict(r) for r in self.opened],
            "closed": list(self.closed),
            "changed": [dict(r) for r in self.changed],
        }


def build_rooms_snapshot(room_manager: RoomManager, *, revision: int) -> RoomsSnapshot:
    """The list exactly as `GET /api/rooms` would answer it.

    The same `to_public_summary` the endpoint uses, so the two cannot describe
    different rooms - the endpoint stays for operators and for tests, and a
    second serializer would be a second thing to keep true.
    """
    return RoomsSnapshot(
        revision=revision, rooms=tuple(room_manager.list_public_rooms())
    )


def diff_rooms(before: RoomsSnapshot, after: RoomsSnapshot) -> RoomsDelta:
    """What a client holding `before` must apply to arrive at `after`."""
    previous = {room["id"]: room for room in before.rooms}
    current = {room["id"]: room for room in after.rooms}
    opened = tuple(room for room_id, room in current.items() if room_id not in previous)
    closed = tuple(room_id for room_id in previous if room_id not in current)
    changed = tuple(
        room
        for room_id, room in current.items()
        if room_id in previous and previous[room_id] != room
    )
    return RoomsDelta(
        revision=after.revision, opened=opened, closed=closed, changed=changed
    )


EMPTY_ROOMS = RoomsSnapshot(revision=0, rooms=())
