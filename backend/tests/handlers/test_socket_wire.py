"""Bytes across the socket, counted where the library hands them over.

The outbound tests run a real `AsyncServer` and manager with seated
recipients and mock only the Engine.IO socket writer, because #563 found the
previous hook (`eio.send`) sat on a path ordinary broadcasts never take: two
recipients, two packets written, zero bytes counted. The invariant under test
is that the counter equals the bytes the sockets were handed - every path,
once each.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import socketio
from engineio import packet as eio_packet

from app.handlers import register_all_handlers as register_handlers
from app.handlers.socket_wire import engineio_packet_size, instrument_socket_server
from app.rooms import RoomManager
from app.services.telemetry import Telemetry


pytestmark = pytest.mark.asyncio


class FakeEngineSocket:
    """The writer end of one Engine.IO connection: keeps what it was handed."""

    closed = False

    def __init__(self) -> None:
        self.packets: list = []

    async def send(self, pkt) -> None:
        self.packets.append(pkt.encode())


def written_bytes(*sockets: FakeEngineSocket) -> int:
    return sum(
        len(p) if isinstance(p, bytes) else len(p.encode("utf-8"))
        for s in sockets
        for p in s.packets
    )


async def seated_server(seats: int):
    """A real server with `seats` connections in room `r1`; sockets mocked."""
    sio = socketio.AsyncServer(async_mode="asgi")
    store = Telemetry()
    instrument_socket_server(sio, store)
    sockets: dict[str, FakeEngineSocket] = {}
    sids: list[str] = []
    for index in range(seats):
        eio_sid = f"eio{index}"
        sockets[eio_sid] = sio.eio.sockets[eio_sid] = FakeEngineSocket()
        sid = await sio.manager.connect(eio_sid, "/")
        await sio.enter_room(sid, "r1")
        sids.append(sid)
    return sio, store, sockets, sids


async def drain() -> None:
    """Let the manager's per-recipient send tasks run."""
    import asyncio

    for _ in range(3):
        await asyncio.sleep(0)


def fake_server():
    received = AsyncMock(return_value="received")
    sent = AsyncMock(return_value=None)
    emitted = AsyncMock(return_value="emitted")
    server = SimpleNamespace(
        _handle_eio_message=received,
        eio=SimpleNamespace(send_packet=sent),
        manager=SimpleNamespace(emit=emitted),
    )
    return server, received, sent, emitted


async def test_packets_in_are_counted_by_their_wire_size():
    server, received, sent, emitted = fake_server()
    store = Telemetry()
    instrument_socket_server(server, store)

    assert await server._handle_eio_message("eio1", '42["guess",{"text":"cat"}]') == "received"
    await server._handle_eio_message("eio1", b"\x01" * 500)
    received.assert_awaited()
    assert store.socket_bytes_in.total() == len('42["guess",{"text":"cat"}]') + 500


async def test_a_room_broadcast_is_counted_once_per_recipient():
    sio, store, sockets, sids = await seated_server(3)
    await sio.emit("room_state", {"players": []}, room="r1")
    await drain()
    assert sum(len(s.packets) for s in sockets.values()) == 3
    assert store.socket_bytes_out.total() == written_bytes(*sockets.values())
    assert store.socket_bytes_out.total() == 3 * len('42["room_state",{"players":[]}]')


async def test_skip_sid_and_a_direct_send_count_only_who_was_written_to():
    sio, store, sockets, sids = await seated_server(3)
    await sio.emit("draw", "AQID", room="r1", skip_sid=sids[0])
    await drain()
    assert len(sockets["eio0"].packets) == 0
    assert store.socket_bytes_out.total() == written_bytes(*sockets.values())
    before = store.socket_bytes_out.total()

    await sio.emit("kicked", {"reason": "afk"}, to=sids[1])
    await drain()
    assert len(sockets["eio1"].packets) == 2
    assert store.socket_bytes_out.total() - before == len('42["kicked",{"reason":"afk"}]')
    assert store.socket_bytes_out.total() == written_bytes(*sockets.values())


async def test_a_binary_attachment_counts_the_envelope_and_the_blob_per_recipient():
    sio, store, sockets, sids = await seated_server(2)
    blob = b"\x11" * 300
    await sio.emit("draw", (blob, [1, 2, 3, "h"]), room="r1")
    await drain()
    # Placeholder envelope, then the attachment: two packets per seat.
    assert [len(s.packets) for s in sockets.values()] == [2, 2]
    assert store.socket_bytes_out.total() == written_bytes(*sockets.values())
    envelope = '451-["draw",{"_placeholder":true,"num":0},[1,2,3,"h"]]'
    assert store.socket_bytes_out.total() == 2 * (len(envelope) + len(blob))


async def test_an_emit_with_a_callback_and_an_ack_reply_are_counted_once_each():
    sio, store, sockets, sids = await seated_server(2)
    await sio.emit("client_config", {"flushIntervalMs": 40}, to=sids[0], callback=lambda: None)
    await drain()
    assert len(sockets["eio0"].packets) == 1
    assert store.socket_bytes_out.total() == written_bytes(*sockets.values())

    before = store.socket_bytes_out.total()
    await sio._send_packet(
        "eio1", sio.packet_class(socketio.packet.ACK, namespace="/", data=[{"ok": True}], id=7)
    )
    assert store.socket_bytes_out.total() - before == len(sockets["eio1"].packets[-1])
    assert store.socket_bytes_out.total() == written_bytes(*sockets.values())


async def test_a_send_to_an_unknown_socket_is_written_nowhere_and_still_counted_as_offered():
    """The library drops the packet with a warning after the hook; what the
    counter records is what the server offered the transport, which is the
    bound an operator sizes for. Kept explicit so a change is deliberate."""
    sio, store, sockets, sids = await seated_server(1)
    await sio.eio.send("nobody", "hello")
    assert store.socket_bytes_out.total() == len("4hello")


async def test_engineio_packet_size_matches_the_encoding_without_caching_it():
    text = eio_packet.Packet(eio_packet.MESSAGE, data='42["draw","AQID"]')
    binary = eio_packet.Packet(eio_packet.MESSAGE, data=b"\x00" * 90)
    unicode = eio_packet.Packet(eio_packet.MESSAGE, data='42["chat","héllo"]')
    for pkt in (text, binary, unicode):
        encoded = eio_packet.Packet(pkt.packet_type, data=pkt.data).encode()
        assert engineio_packet_size(pkt) == (
            len(encoded) if isinstance(encoded, bytes) else len(encoded.encode("utf-8"))
        )
        assert pkt.encode_cache is None
    assert engineio_packet_size(eio_packet.Packet(eio_packet.PING)) == 1
    # A polling writer asks for base64 afterwards and must still get it.
    assert binary.encode(b64=True).startswith("b")


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


async def test_the_library_still_has_what_the_hooks_lean_on():
    """A rename upstream must fail here, not as a page reporting no traffic."""
    sio = socketio.AsyncServer(async_mode="asgi")
    instrument_socket_server(sio, Telemetry())
    assert sio.manager.emit.__name__ == "counted_emit"
    assert sio.eio.send_packet.__name__ == "counted_send_packet"

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


async def test_packets_arriving_through_engineio_are_counted_not_only_direct_calls():
    """#461: the load gate reported zero bytes in under 400 seats. socketio
    hands engineio its *bound* receive method at construction, so wrapping
    the instance attribute counted only callers that went through the
    attribute - every test - and none of the packets a socket actually sent.
    The registered handler is the one real traffic reaches."""
    import socketio as socketio_module

    from app.handlers.socket_wire import instrument_socket_server

    store = Telemetry()
    sio = socketio_module.AsyncServer(async_mode="asgi")
    seen = []

    async def received(eio_sid, data):
        seen.append((eio_sid, data))

    sio._handle_eio_message = received
    sio.eio.on("message", received)  # what the constructor did with the original
    instrument_socket_server(sio, store)

    await sio.eio._trigger_event("message", "eio1", '42["guess",{"text":"cat"}]')
    assert seen == [("eio1", '42["guess",{"text":"cat"}]')]
    assert store.socket_bytes_in.total() == len('42["guess",{"text":"cat"}]')
