"""Ending an account ends its sockets, not only its seats.

Walking the live rooms reaches a socket that already holds a seat. One can be
in flight: `create_room` and `join_room` await the database before they seat
anybody, so a socket that was mid-entry when the sweep passed has no seat to
be found and finishes seating itself afterwards. Every socket joins its
account's broadcast room at the handshake, and that is the list with all of
them on it.
"""
from __future__ import annotations

import pytest


class FakeManager:
    """Just enough of Socket.IO's room bookkeeping to be swept."""

    def __init__(self, rooms: dict[str, list[str]]) -> None:
        self._rooms = rooms

    def get_participants(self, namespace, room):
        assert namespace == "/"
        for sid in list(self._rooms.get(room, [])):
            yield sid, f"eio-{sid}"


class FakeServer:
    def __init__(self, rooms: dict[str, list[str]]) -> None:
        self.manager = FakeManager(rooms)
        self.emitted: list[tuple] = []
        self.disconnected: list[str] = []

    async def emit(self, event, payload=None, to=None, room=None, **_kwargs):
        self.emitted.append((event, payload, to or room))

    async def disconnect(self, sid):
        self.disconnected.append(sid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ending, event",
    [
        ("suspension", "account_suspended"),
        ("deletion", "session_superseded"),
    ],
)
async def test_every_socket_of_the_account_is_told_and_then_closed(
    monkeypatch, ending, event
):
    """Including one that held no seat when the rooms were walked - which is
    what a socket still inside `create_room` looks like."""
    from app import main

    unseated = "mid-entry-sid"
    server = FakeServer({"user:doomed": ["seated-sid", unseated]})
    monkeypatch.setattr(main, "sio", server)
    monkeypatch.setattr(main.block_service, "clear", lambda: None)

    async def no_seats(user_id, *, reason, suspension=None):
        return None

    monkeypatch.setattr(main, "_remove_account_from_live_rooms", no_seats)
    if ending == "suspension":
        payload = {"reason": "suspended"}

        async def suspension_payload(*_args, **_kwargs):
            return payload

        monkeypatch.setattr(main, "suspension_payload", suspension_payload)
        await main.remove_banned_account_from_live_rooms("doomed")
    else:
        payload = {"reason": "Your account was deleted."}
        await main.remove_deleted_account_from_live_rooms("doomed")

    assert server.emitted == [(event, payload, "user:doomed")]
    assert server.disconnected == ["seated-sid", unseated]


@pytest.mark.asyncio
async def test_deleting_an_account_closes_its_sockets_too(monkeypatch):
    """This half was only ever done for suspensions."""
    from app import main

    server = FakeServer({"user:gone": ["idle-sid"]})
    monkeypatch.setattr(main, "sio", server)
    monkeypatch.setattr(main.block_service, "clear", lambda: None)

    async def no_seats(user_id, *, reason, suspension=None):
        return None

    monkeypatch.setattr(main, "_remove_account_from_live_rooms", no_seats)

    await main.remove_deleted_account_from_live_rooms("gone")

    assert server.disconnected == ["idle-sid"]
    assert server.emitted[0][0] == "session_superseded"


@pytest.mark.asyncio
async def test_the_mark_is_taken_before_the_sweep_awaits_anything(monkeypatch):
    """The mark is what a mid-entry socket sees, and every step of a sweep
    yields: reading the suspension, walking the rooms, emitting the notice,
    closing each socket. An entry that reads the mark in one of those gaps and
    finds nothing is an entry that seats an account mid-ban."""
    from app import main

    sids = ["first-sid", "second-sid"]
    marked_at: dict[str, list[bool]] = {}

    def record(step: str) -> None:
        marked_at[step] = [main.handler_context.is_ending(sid) for sid in sids]

    class MarkWatchingServer(FakeServer):
        async def emit(self, event, payload=None, to=None, room=None, **kwargs):
            record("emit")
            await super().emit(event, payload, to=to, room=room, **kwargs)

        async def disconnect(self, sid):
            record(f"disconnect {sid}")
            await super().disconnect(sid)

    server = MarkWatchingServer({"user:doomed": list(sids)})
    monkeypatch.setattr(main, "sio", server)

    async def suspension_payload(*_args, **_kwargs):
        record("reading the suspension")
        return {"reason": "suspended"}

    async def walk_the_rooms(user_id, *, reason, suspension=None):
        record("walking the rooms")

    monkeypatch.setattr(main, "suspension_payload", suspension_payload)
    monkeypatch.setattr(main, "_remove_account_from_live_rooms", walk_the_rooms)

    await main.remove_banned_account_from_live_rooms("doomed")

    assert marked_at == {
        "reading the suspension": [True, True],
        "walking the rooms": [True, True],
        "emit": [True, True],
        "disconnect first-sid": [True, True],
        "disconnect second-sid": [True, True],
    }
    assert not any(main.handler_context.is_ending(sid) for sid in sids)
