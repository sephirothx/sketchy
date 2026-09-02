"""Bytes across the socket, counted where the library hands them over."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from app.handlers.socket_wire import instrument_socket_server
from app.rooms import RoomManager
from app.services.telemetry import Telemetry


pytestmark = pytest.mark.asyncio


def fake_server():
    received = AsyncMock(return_value="received")
    sent = AsyncMock(return_value=None)
    emitted = AsyncMock(return_value="emitted")
    server = SimpleNamespace(
        _handle_eio_message=received,
        eio=SimpleNamespace(send=sent),
        manager=SimpleNamespace(emit=emitted),
    )
    return server, received, sent, emitted


async def test_packets_in_and_out_are_counted_by_their_wire_size():
    server, received, sent, emitted = fake_server()
    store = Telemetry()
    instrument_socket_server(server, store)

    assert await server._handle_eio_message("eio1", '42["guess",{"text":"cat"}]') == "received"
    await server._handle_eio_message("eio1", b"\x01" * 500)
    received.assert_awaited()
    assert store.socket_bytes_in.total() == len('42["guess",{"text":"cat"}]') + 500

    # Out is per recipient: a fan-out to three seats is three packets.
    for _ in range(3):
        await server.eio.send("eio1", '42["room_state",{"players":[]}]')
    assert store.socket_bytes_out.total() == 3 * len('42["room_state",{"players":[]}]')
    assert sent.await_count == 3


async def test_an_emit_is_sized_once_by_event_and_passed_through_intact():
    server, received, sent, emitted = fake_server()
    store = Telemetry()
    instrument_socket_server(server, store)

    result = await server.manager.emit(
        "room_state", {"players": ["a", "b"]}, "/", room="r1", skip_sid="x"
    )
    assert result == "emitted"
    emitted.assert_awaited_once_with(
        "room_state", {"players": ["a", "b"]}, "/", room="r1", skip_sid="x"
    )
    await server.manager.emit("draw", b"\x00" * 300, "/", to="s1")
    await server.manager.emit("ping", None, "/")
    rows = {row["event"]: row for row in store.snapshot()["socket"]["emitSizes"]}
    assert rows["draw"]["bytesTotal"] == 300
    assert rows["room_state"]["bytesTotal"] == len(b'{"players":["a","b"]}')
    assert rows["ping"]["bytesTotal"] == 0


def test_the_library_still_has_what_the_hooks_lean_on():
    """A rename upstream must fail here, not as a page reporting no traffic."""
    sio = socketio.AsyncServer(async_mode="asgi")
    instrument_socket_server(sio, Telemetry())
    assert sio.manager.emit.__name__ == "counted_emit"
    assert sio.eio.send.__name__ == "counted_send"

    with pytest.raises(AttributeError):
        instrument_socket_server(
            SimpleNamespace(eio=SimpleNamespace(send=None), manager=SimpleNamespace(emit=None))
        )


async def test_a_real_emit_reaches_the_manager_hook_and_a_mocked_one_stays_mocked():
    """Both paths a test or the server takes still work after wrapping."""
    sio = socketio.AsyncServer(async_mode="asgi")
    store = Telemetry()
    instrument_socket_server(sio, store)
    # Nobody is in the namespace, so the manager returns before sending.
    await sio.emit("room_state", {"players": []}, room="r1")
    assert store.socket_emit_bytes.count() == 1

    sio.emit = AsyncMock()
    await sio.emit("kicked", {})
    sio.emit.assert_awaited_once_with("kicked", {})


async def test_registration_wires_the_counters_and_commands_are_sized(monkeypatch):
    from app.handlers import context as context_module

    store = Telemetry()
    monkeypatch.setattr(context_module, "telemetry", store)
    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, RoomManager())
    assert sio.manager.emit.__name__ == "counted_emit"

    sio.emit = AsyncMock()
    sio.get_session = AsyncMock(return_value={"user_id": "u1"})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    await sio.handlers["/"]["create_room"]("host", {"nickname": "Host"})
    rows = {row["event"]: row for row in store.snapshot()["socket"]["commandSizes"]}
    assert rows["create_room"]["count"] == 1
    assert rows["create_room"]["bytesTotal"] == len(b'{"nickname":"Host"}')
