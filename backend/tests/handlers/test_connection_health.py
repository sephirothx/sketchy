"""The life of a connection, measured where it happens (#881).

Each series here is reached through the code path that increments it in
production - a real handler, a real Engine.IO socket - rather than by calling
the telemetry method directly, because a counter nobody's code reaches is the
failure this issue is about: a number that reads zero on the night it matters.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import socketio
from engineio import packet as eio_packet
from engineio.async_socket import AsyncSocket

from app.handlers import register_all_handlers as register_handlers
from app.handlers.connection import disconnect
from app.handlers.socket_wire import instrument_socket_server
from app.protocol import PROTOCOL_VERSION, stale_client_bucket
from app.rooms import RoomManager
from app.services import telemetry as telemetry_module
from app.services.telemetry import Telemetry


def observations(store: Telemetry, histogram_name: str) -> int:
    line = next(
        (line for line in store.prometheus_lines() if line.startswith(f"{histogram_name}_count")),
        None,
    )
    return 0 if line is None else int(float(line.split()[-1]))


def fresh_store(monkeypatch) -> Telemetry:
    store = Telemetry()
    for module in ("app.handlers.connection", "app.handlers.rooms", "app.handlers.context"):
        monkeypatch.setattr(f"{module}.telemetry", store)
    monkeypatch.setattr(telemetry_module, "telemetry", store)
    return store


def server(room_manager: RoomManager | None = None):
    sio = socketio.AsyncServer(async_mode="asgi")
    context = register_handlers(sio, room_manager or RoomManager())
    sio.get_session = AsyncMock(return_value={})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()
    sio.transport = lambda sid: "websocket"
    return sio, context


async def test_the_library_passes_the_reason_and_it_is_counted_with_the_session(monkeypatch):
    store = fresh_store(monkeypatch)
    sio, context = server()
    store.note_socket_opened("s1", "websocket")
    # The way python-socketio calls it: with the reason as the last argument.
    await sio._trigger_event("disconnect", "/", "s1", sio.reason.PING_TIMEOUT)
    await sio._trigger_event("disconnect", "/", "s2", "a reason from a later version")
    assert store.socket_disconnects.get(("ping_timeout",)) == 1
    assert store.socket_disconnects.get(("other",)) == 1
    # Only the socket that was seen opening has a session to size.
    assert observations(store, "sketchy_socket_session_seconds") == 1
    await context.timers.close()


async def test_a_type_error_inside_disconnect_does_not_run_it_twice(monkeypatch):
    """The library retries a disconnect handler without the reason on a
    TypeError; the registered handler must not let one escape."""
    store = fresh_store(monkeypatch)
    sio, context = server()
    calls = []

    def exploding(sid):
        calls.append(sid)
        raise TypeError("a bug in a handler")

    monkeypatch.setattr(context.room_capacity, "note_socket_closed", exploding)
    await sio._trigger_event("disconnect", "/", "s1", sio.reason.CLIENT_DISCONNECT)
    assert calls == ["s1"]
    assert store.socket_disconnects.get(("client_disconnect",)) == 1
    await context.timers.close()


async def test_a_polling_socket_that_upgrades_is_counted_once_and_the_gauge_says_where_it_is(monkeypatch):
    store = fresh_store(monkeypatch)
    store.note_socket_opened("p1", "polling")
    store.note_socket_opened("p2", "polling")
    store.note_socket_opened("w1", "websocket")
    transports = {"p1": "polling", "p2": "websocket", "w1": "websocket"}
    store.sources.socket_transports = lambda: transports

    lines = store.prometheus_lines()
    assert 'sketchy_sockets_by_transport{transport="polling"} 1' in lines
    assert 'sketchy_sockets_by_transport{transport="websocket"} 2' in lines
    assert store.socket_upgrades.total() == 1
    store.prometheus_lines()
    assert store.socket_upgrades.total() == 1

    # Upgraded between two scrapes and closed before the next: counted at close.
    transports["p1"] = "websocket"
    store.note_socket_closed("p1", "transport close", "websocket")
    store.note_socket_closed("p2", "transport close", "websocket")
    assert store.socket_upgrades.total() == 2


async def test_the_handshake_transport_is_counted_for_an_accepted_socket(monkeypatch):
    store = fresh_store(monkeypatch)
    sio, context = server()
    # Upgraded before its CONNECT was handled: still a polling handshake.
    sio.transport = lambda sid: "websocket"
    environ = {"QUERY_STRING": "EIO=4&transport=polling&t=abc"}
    await sio.handlers["/"]["connect"]("s1", environ, {"protocol": PROTOCOL_VERSION})
    assert store.socket_handshake_transports.get(("polling",)) == 1
    store.note_socket_closed("s1", "client disconnect", "websocket")
    assert store.socket_upgrades.total() == 1
    await context.timers.close()


async def test_a_seat_taken_back_inside_its_grace_records_how_long_it_stood_empty(monkeypatch):
    store = fresh_store(monkeypatch)
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    player = room_manager.add_player(room, "Returner", user_id="returning-user")
    room_manager.add_player(room, "Other", user_id="other-user")
    player.sid = "old-sid"
    sio, context = server(room_manager)
    sio.get_session = AsyncMock(return_value={"user_id": "returning-user"})

    await disconnect(context, "old-sid", sio.reason.TRANSPORT_CLOSE)
    assert player.connected is False
    player.disconnected_at -= 4.0
    response = await sio.handlers["/"]["join_room"]("new-sid", {"code": room.code, "nickname": player.nickname})
    assert response["ok"] is True
    assert observations(store, "sketchy_seat_rebind_seconds") == 1
    assert 'sketchy_seat_rebind_seconds_bucket{le="3.0"} 0' in store.prometheus_lines()
    assert 'sketchy_seat_rebind_seconds_bucket{le="5.0"} 1' in store.prometheus_lines()

    # A second tab taking over a live seat is not a rebind.
    await sio.handlers["/"]["join_room"]("third-sid", {"code": room.code, "nickname": player.nickname})
    assert observations(store, "sketchy_seat_rebind_seconds") == 1
    await context.timers.close()


async def test_a_stale_client_is_counted_by_its_version_and_how_it_went(monkeypatch):
    store = fresh_store(monkeypatch)
    sio, context = server()
    sio.disconnect = AsyncMock()

    context.quarantine("reloads", PROTOCOL_VERSION - 1, close_after=60)
    context.release_stale("reloads")
    context.quarantine("lingers", 0, close_after=0)
    await asyncio.sleep(0.01)
    # The close it forces reaches `disconnect`, which must not count it again.
    context.release_stale("lingers")

    assert store.stale_clients.get(("older", "reloaded")) == 1
    assert store.stale_clients.get(("absent", "closed")) == 1
    assert store.stale_clients.total() == 2
    assert stale_client_bucket(PROTOCOL_VERSION + 3) == "newer"
    await context.timers.close()


async def test_a_stale_socket_another_server_path_closes_did_not_reload(monkeypatch):
    """A suspension or a superseded seat closes the socket from the server;
    that is not the reload the notice asked for."""
    store = fresh_store(monkeypatch)
    sio, context = server()
    context.quarantine("suspended", PROTOCOL_VERSION - 1, close_after=60)
    await disconnect(context, "suspended", sio.reason.SERVER_DISCONNECT)
    context.quarantine("tab-reloaded", PROTOCOL_VERSION - 1, close_after=60)
    await disconnect(context, "tab-reloaded", sio.reason.TRANSPORT_CLOSE)
    assert store.stale_clients.get(("older", "closed")) == 1
    assert store.stale_clients.get(("older", "reloaded")) == 1
    await context.timers.close()


async def test_a_reconnect_refused_for_an_ending_account_is_not_a_rebind(monkeypatch):
    store = fresh_store(monkeypatch)
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    player = room_manager.add_player(room, "Ending", user_id="ending-user")
    room_manager.add_player(room, "Other", user_id="other-user")
    player.sid = "old-sid"
    sio, context = server(room_manager)
    sio.get_session = AsyncMock(return_value={"user_id": "ending-user"})
    await disconnect(context, "old-sid", sio.reason.TRANSPORT_CLOSE)
    monkeypatch.setattr(context, "is_ending", lambda sid: sid == "new-sid")

    await sio.handlers["/"]["join_room"]("new-sid", {"code": room.code, "nickname": player.nickname})
    assert player.connected is False
    assert observations(store, "sketchy_seat_rebind_seconds") == 0
    await context.timers.close()


async def test_an_engineio_pong_is_timed_against_its_ping():
    sio = socketio.AsyncServer(async_mode="asgi")
    store = Telemetry()
    instrument_socket_server(sio, store)
    engine_socket = AsyncSocket(sio.eio, "e1")
    engine_socket.closed = True  # nothing to ping afterwards
    sio.eio.sockets["e1"] = engine_socket
    await sio.eio.handlers["connect"]("e1", {})

    engine_socket.last_ping = time.time() - 0.2
    await engine_socket.receive(eio_packet.Packet(eio_packet.PONG))
    # A pong nobody pinged for (the upgrade probe, a duplicate) is not timed.
    await engine_socket.receive(eio_packet.Packet(eio_packet.PONG))
    assert observations(store, "sketchy_socket_ping_rtt_seconds") == 1
    assert 'sketchy_socket_ping_rtt_seconds_bucket{le="0.1"} 0' in store.prometheus_lines()
    assert 'sketchy_socket_ping_rtt_seconds_bucket{le="0.25"} 1' in store.prometheus_lines()
