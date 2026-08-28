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

    notice = (
        ("account_suspended", {"reason": "suspended"})
        if ending == "suspension"
        else ("session_superseded", {"reason": "Your account was deleted."})
    )
    await main._close_every_socket_of("doomed", notice)

    assert server.emitted == [(event, notice[1], "user:doomed")]
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
async def test_a_socket_is_marked_as_ending_while_it_is_being_closed():
    """The mark is what a mid-entry socket sees. Closing one waits at its
    seating gate, so an entry already holding that gate runs to completion
    first - and without the mark it completes by seating an account this
    sweep has already walked past."""
    from app import main

    seen: dict[str, bool] = {}

    class MarkWatchingServer(FakeServer):
        async def disconnect(self, sid):
            seen[sid] = main.handler_context.is_ending(sid)
            await super().disconnect(sid)

    server = MarkWatchingServer({"user:doomed": ["first-sid", "second-sid"]})
    original = main.sio
    main.sio = server
    try:
        await main._close_every_socket_of(
            "doomed", ("session_superseded", {"reason": "gone"})
        )
    finally:
        main.sio = original

    # Marked before the first disconnect rather than one at a time: the sweep
    # blocks on each, and the socket it has not reached yet is exactly the one
    # that could be seating itself meanwhile.
    assert seen == {"first-sid": True, "second-sid": True}
    assert not main.handler_context.is_ending("first-sid")
    assert not main.handler_context.is_ending("second-sid")
