"""The WebSocket transport is the one server.py names, negotiating the window it says.

Two layers. The in-memory tests drive wsproto's own client against the server
connection this module substitutes, so they prove the negotiation without a
socket. The live test boots uvicorn on a free port with the same import path
server.py uses, because "auto" picking a different library was the bug: the
protocol class has to survive uvicorn's own loading, not just ours.
"""
from __future__ import annotations

import asyncio
import re
import socket
from pathlib import Path

import uvicorn
import wsproto
from wsproto.connection import ConnectionType
from wsproto.events import (
    AcceptConnection,
    CloseConnection,
    RejectConnection,
    RejectData,
    Request,
    TextMessage,
)
from wsproto.extensions import PerMessageDeflate

from app import ws_transport
from app.services.telemetry import Telemetry
from app.ws_transport import (
    CLIENT_MAX_WINDOW_BITS,
    SERVER_MAX_WINDOW_BITS,
    WS_PROTOCOL,
    NegotiatingConnection,
    SketchyWebSocketProtocol,
    compression_label,
)


class BrowserOffer(PerMessageDeflate):
    """What Chrome, Firefox and Safari send: the client parameter alone, valueless."""

    def offer(self) -> str:
        return "client_max_window_bits"


def negotiate(client_offer: list, monkeypatch, store: Telemetry) -> tuple[list, str]:
    """Run one handshake in memory; return the client's view and the response header."""
    monkeypatch.setattr(ws_transport, "telemetry", store)
    client = wsproto.WSConnection(ConnectionType.CLIENT)
    server = NegotiatingConnection(connection_type=ConnectionType.SERVER)
    server.receive_data(client.send(Request(host="h", target="/socket.io/", extensions=client_offer)))
    request = next(e for e in server.events() if isinstance(e, Request))
    assert request
    # What uvicorn builds at accept time, verbatim.
    response = server.send(AcceptConnection(extensions=[PerMessageDeflate()]))
    client.receive_data(response)
    accepted = next(e for e in client.events() if isinstance(e, AcceptConnection))
    header = re.search(rb"(?i)sec-websocket-extensions: ([^\r\n]*)", response)
    return accepted.extensions, header.group(1).decode() if header else ""


def test_a_browser_offer_gets_the_configured_server_window(monkeypatch):
    """Browsers offer client_max_window_bits alone; the server window is added."""
    store = Telemetry()
    extensions, header = negotiate([BrowserOffer()], monkeypatch, store)
    deflate = extensions[0]
    assert deflate.enabled()
    assert deflate.server_max_window_bits == SERVER_MAX_WINDOW_BITS
    assert deflate.client_max_window_bits == CLIENT_MAX_WINDOW_BITS
    assert f"server_max_window_bits={SERVER_MAX_WINDOW_BITS}" in header
    assert store.socket_transports.get((f"deflate-{SERVER_MAX_WINDOW_BITS}",)) == 1


def test_the_window_is_the_smaller_of_the_client_cap_and_the_configured_one(monkeypatch):
    """RFC 7692: a client may cap our window; the configured value caps it too."""
    store = Telemetry()
    extensions, header = negotiate([PerMessageDeflate(server_max_window_bits=12)], monkeypatch, store)
    assert extensions[0].server_max_window_bits == 12
    assert "server_max_window_bits=12" in header
    assert store.socket_transports.get(("deflate-12",)) == 1

    monkeypatch.setattr(ws_transport, "SERVER_MAX_WINDOW_BITS", 13)
    extensions, header = negotiate([PerMessageDeflate(server_max_window_bits=15)], monkeypatch, store)
    assert extensions[0].server_max_window_bits == 13
    assert "server_max_window_bits=13" in header


def test_no_offer_means_no_compression_and_is_counted_as_such(monkeypatch):
    store = Telemetry()
    extensions, header = negotiate([], monkeypatch, store)
    assert extensions == []
    assert "permessage-deflate" not in header
    assert store.socket_transports.get(("none",)) == 1
    assert compression_label([]) == "none"


def test_the_compressor_really_uses_the_stated_window(monkeypatch):
    """A back-reference past the window is impossible: two identical 20 KB
    messages compress to almost nothing at 15 bits and not at 12."""
    store = Telemetry()
    monkeypatch.setattr(ws_transport, "telemetry", store)
    import random

    payload = random.Random(561).randbytes(20_480)  # incompressible on its own

    def repeat_cost(bits: int) -> int:
        monkeypatch.setattr(ws_transport, "SERVER_MAX_WINDOW_BITS", bits)
        server = NegotiatingConnection(connection_type=ConnectionType.SERVER)
        client = wsproto.WSConnection(ConnectionType.CLIENT)
        server.receive_data(client.send(Request(host="h", target="/", extensions=[BrowserOffer()])))
        list(server.events())
        client.receive_data(server.send(AcceptConnection(extensions=[PerMessageDeflate()])))
        list(client.events())
        server.send(wsproto.events.BytesMessage(data=payload))
        return len(server.send(wsproto.events.BytesMessage(data=payload)))

    # 15 bits = 32 KB of history holds the whole first copy; 12 bits = 4 KB
    # holds a fifth of it, so the repeat is mostly literal bytes again.
    assert repeat_cost(15) < 200
    assert repeat_cost(12) > 10_000


def test_wire_bytes_are_the_frames_after_compression_and_not_the_handshake(monkeypatch):
    """The one counter that says what deflate produced (#875): exactly the bytes
    each side hands the transport once open, and a repeated payload costing a
    fraction of its size the second time, which the packet counters cannot show."""
    store = Telemetry()
    monkeypatch.setattr(ws_transport, "telemetry", store)
    client = wsproto.WSConnection(ConnectionType.CLIENT)
    server = NegotiatingConnection(connection_type=ConnectionType.SERVER)
    server.receive_data(client.send(Request(host="h", target="/socket.io/", extensions=[BrowserOffer()])))
    list(server.events())
    client.receive_data(server.send(AcceptConnection(extensions=[PerMessageDeflate()])))
    list(client.events())
    assert store.ws_wire_bytes_out.total() == 0 and store.ws_wire_bytes_in.total() == 0

    state = '42["room_state",' + '{"nickname":"Player","score":120,"connected":true},' * 16 + "{}]"
    first = server.send(TextMessage(data=state))
    second = server.send(TextMessage(data=state))
    assert store.ws_wire_bytes_out.total() == len(first) + len(second)
    assert len(first) < len(state) and len(second) < len(first) // 4

    guess = client.send(TextMessage(data='42["guess",{"text":"cat"}]'))
    server.receive_data(guess)
    assert store.ws_wire_bytes_in.total() == len(guess)
    lines = store.prometheus_lines()
    assert f"sketchy_ws_wire_bytes_out_total {len(first) + len(second)}" in lines
    assert f"sketchy_ws_wire_bytes_in_total {len(guess)}" in lines


def open_pair(monkeypatch, store: Telemetry):
    monkeypatch.setattr(ws_transport, "telemetry", store)
    client = wsproto.WSConnection(ConnectionType.CLIENT)
    server = NegotiatingConnection(connection_type=ConnectionType.SERVER)
    server.receive_data(client.send(Request(host="h", target="/socket.io/", extensions=[BrowserOffer()])))
    list(server.events())
    client.receive_data(server.send(AcceptConnection(extensions=[PerMessageDeflate()])))
    list(client.events())
    return client, server


def test_a_rejected_handshake_is_http_and_not_counted_as_wire(monkeypatch):
    """A plain-ws or cross-origin handshake is refused with an HTTP response,
    which has no packet bytes behind it; counting it would skew the ratio."""
    store = Telemetry()
    monkeypatch.setattr(ws_transport, "telemetry", store)
    client = wsproto.WSConnection(ConnectionType.CLIENT)
    server = NegotiatingConnection(connection_type=ConnectionType.SERVER)
    server.receive_data(client.send(Request(host="h", target="/socket.io/")))
    list(server.events())
    rejected = server.send(RejectConnection(status_code=403, has_body=True))
    rejected += server.send(RejectData(data=b"Forbidden"))
    assert rejected
    assert store.ws_wire_bytes_out.total() == 0 and store.ws_wire_bytes_in.total() == 0


def test_both_halves_of_a_closing_handshake_are_counted(monkeypatch):
    """wsproto still takes frames while the side that closed first waits for
    the reply, and still sends the reply to a close it received."""
    store = Telemetry()
    client, server = open_pair(monkeypatch, store)
    closing = server.send(CloseConnection(code=1000))
    client.receive_data(closing)
    reply = client.send(next(e for e in client.events() if isinstance(e, CloseConnection)).response())
    server.receive_data(reply)
    assert store.ws_wire_bytes_out.total() == len(closing)
    assert store.ws_wire_bytes_in.total() == len(reply)

    store = Telemetry()
    client, server = open_pair(monkeypatch, store)
    closing = client.send(CloseConnection(code=1001))
    server.receive_data(closing)
    reply = server.send(next(e for e in server.events() if isinstance(e, CloseConnection)).response())
    assert store.ws_wire_bytes_in.total() == len(closing)
    assert store.ws_wire_bytes_out.total() == len(reply)


def test_server_names_the_protocol_and_requirements_pin_the_library():
    assert WS_PROTOCOL == "app.ws_transport:SketchyWebSocketProtocol"
    from app import server as server_module

    assert server_module.WS_PROTOCOL == WS_PROTOCOL
    requirements = (Path(__file__).parents[1] / "requirements.txt").read_text()
    assert re.search(r"^wsproto==\d", requirements, re.M), "wsproto must be a declared runtime dependency"


async def _accepting_app(scope, receive, send):
    """The smallest ASGI app that upgrades: the negotiation is uvicorn's and ours."""
    assert scope["type"] == "websocket"
    await receive()
    await send({"type": "websocket.accept"})
    while (await receive())["type"] != "websocket.disconnect":
        pass


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _handshake(port: int, offer: list) -> tuple[list, str]:
    client = wsproto.WSConnection(ConnectionType.CLIENT)
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(client.send(Request(host=f"127.0.0.1:{port}", target="/ws", extensions=offer)))
        raw = sock.recv(65536)
    client.receive_data(raw)
    accepted = next(e for e in client.events() if isinstance(e, AcceptConnection))
    header = re.search(rb"(?i)sec-websocket-extensions: ([^\r\n]*)", raw)
    return accepted.extensions, header.group(1).decode() if header else ""


async def test_uvicorn_loads_the_named_protocol_and_negotiates_it_live(monkeypatch):
    store = Telemetry()
    monkeypatch.setattr(ws_transport, "telemetry", store)
    port = _free_port()
    config = uvicorn.Config(_accepting_app, host="127.0.0.1", port=port, ws=WS_PROTOCOL, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started
        assert config.ws_protocol_class is SketchyWebSocketProtocol
        loop = asyncio.get_running_loop()
        extensions, header = await loop.run_in_executor(None, _handshake, port, [PerMessageDeflate()])
        assert extensions[0].server_max_window_bits == SERVER_MAX_WINDOW_BITS
        assert f"server_max_window_bits={SERVER_MAX_WINDOW_BITS}" in header
        plain, header = await loop.run_in_executor(None, _handshake, port, [])
        assert plain == [] and "permessage" not in header
        await asyncio.sleep(0.05)
        assert store.socket_transports.get((f"deflate-{SERVER_MAX_WINDOW_BITS}",)) == 1
        assert store.socket_transports.get(("none",)) == 1
    finally:
        server.should_exit = True
        await task


def test_the_operations_snapshot_and_metrics_carry_the_transport_rows():
    store = Telemetry()
    store.note_socket_transport("deflate-15")
    store.note_socket_transport("deflate-15")
    store.note_socket_transport("none")
    assert store.snapshot()["socket"]["transports"] == {"deflate-15": 2, "none": 1}
    text = "\n".join(store.prometheus_lines()) if hasattr(store, "prometheus_lines") else "\n".join(store.lines())
    assert 'sketchy_socket_transport_total{compression="deflate-15"} 2' in text


# --- the inflate budget (#1234) ---------------------------------------------------


def _open_pair(monkeypatch):
    """A negotiated client/server pair in memory, deflate on both sides."""
    monkeypatch.setattr(ws_transport, "telemetry", Telemetry())
    server = NegotiatingConnection(connection_type=ConnectionType.SERVER)
    client = wsproto.WSConnection(ConnectionType.CLIENT)
    server.receive_data(client.send(Request(host="h", target="/", extensions=[BrowserOffer()])))
    list(server.events())
    client.receive_data(server.send(AcceptConnection(extensions=[PerMessageDeflate()])))
    list(client.events())
    return client, server


def _feed(server, wire: bytes) -> tuple[list, int]:
    """Hand `wire` to the server in one read; return its events and the peak
    Python allocation it took to produce them."""
    import tracemalloc

    tracemalloc.start()
    try:
        server.receive_data(wire)
        events = list(server.events())
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return events, peak


def _text(events) -> str:
    return "".join(e.data for e in events if isinstance(e, TextMessage))


def test_a_compressed_bomb_closes_with_1009_before_it_is_inflated(monkeypatch):
    """32 KB of wire used to become 32 MiB in memory before anything counted
    it. Now the most one message inflates to is the ceiling plus one byte."""
    from app.socket_server import MAX_PACKET_BYTES

    client, server = _open_pair(monkeypatch)
    wire = bytes(client.send(wsproto.events.TextMessage(data="x" * (32 * 1024 * 1024))))
    assert len(wire) < 64 * 1024, "a thousandfold bomb"

    events, peak = _feed(server, wire)

    closes = [e for e in events if isinstance(e, CloseConnection)]
    assert closes and closes[0].code == 1009
    assert peak < 3 * MAX_PACKET_BYTES, f"inflated {peak} bytes on the way to refusing it"


def test_a_binary_bomb_is_bounded_the_same_way(monkeypatch):
    client, server = _open_pair(monkeypatch)
    wire = bytes(client.send(wsproto.events.BytesMessage(data=b"\0" * (8 * 1024 * 1024))))
    events, peak = _feed(server, wire)
    assert [e.code for e in events if isinstance(e, CloseConnection)] == [1009]
    assert peak < 3 * ws_transport.INBOUND_MESSAGE_LIMIT


def test_the_budget_spans_every_frame_of_a_fragmented_message(monkeypatch):
    """Each fragment under the ceiling, the message over it: the count must
    not reset at a frame boundary."""
    client, server = _open_pair(monkeypatch)
    quarter = "y" * (ws_transport.INBOUND_MESSAGE_LIMIT // 4 + 1)
    wire = b"".join(
        bytes(client.send(wsproto.events.TextMessage(data=quarter, message_finished=index == 3)))
        for index in range(4)
    )
    events, _ = _feed(server, wire)
    assert [e.code for e in events if isinstance(e, CloseConnection)] == [1009]


def test_a_message_at_the_ceiling_passes_and_one_byte_more_does_not(monkeypatch):
    limit = ws_transport.INBOUND_MESSAGE_LIMIT
    client, server = _open_pair(monkeypatch)
    events, _ = _feed(server, bytes(client.send(wsproto.events.TextMessage(data="z" * limit))))
    assert len(_text(events)) == limit
    assert not [e for e in events if isinstance(e, CloseConnection)]

    client, server = _open_pair(monkeypatch)
    events, _ = _feed(server, bytes(client.send(wsproto.events.TextMessage(data="z" * (limit + 1)))))
    assert [e.code for e in events if isinstance(e, CloseConnection)] == [1009]


def test_messages_under_the_ceiling_keep_passing_with_context_takeover(monkeypatch):
    """The count is per message, and the shared compression context keeps
    working across them - the second copy is a back-reference to the first."""
    client, server = _open_pair(monkeypatch)
    big = "w" * (ws_transport.INBOUND_MESSAGE_LIMIT - 10)
    for _ in range(3):
        events, _ = _feed(server, bytes(client.send(wsproto.events.TextMessage(data=big))))
        assert _text(events) == big
    fragments = [
        bytes(client.send(wsproto.events.TextMessage(data="ab" * 1000, message_finished=last)))
        for last in (False, True)
    ]
    events, _ = _feed(server, b"".join(fragments))
    assert _text(events) == "ab" * 2000


def test_the_largest_create_room_still_passes_the_inflate_budget(monkeypatch):
    """Both serialisations of the 80,000-character custom-prompts blob."""
    import json

    from app.prompts import MAX_RAW_INPUT_LENGTH

    blob = "\U0001F600" * MAX_RAW_INPUT_LENGTH
    for packet in (
        "42" + json.dumps(["create_room", {"customPrompts": blob}], ensure_ascii=False),
        "42" + json.dumps(["create_room", {"customPrompts": blob}]),
    ):
        client, server = _open_pair(monkeypatch)
        events, _ = _feed(server, bytes(client.send(wsproto.events.TextMessage(data=packet))))
        assert _text(events) == packet
        assert not [e for e in events if isinstance(e, CloseConnection)]


def _bomb_client(port: int) -> int | None:
    """Send one compressed 15 MiB message over a real socket; return the close
    code the server answered with, or None if it only dropped the line."""
    client = wsproto.WSConnection(ConnectionType.CLIENT)
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(client.send(Request(host=f"127.0.0.1:{port}", target="/ws", extensions=[PerMessageDeflate()])))
        client.receive_data(sock.recv(65536))
        list(client.events())
        sock.sendall(client.send(wsproto.events.TextMessage(data="x" * (15 * 1024 * 1024))))
        while True:
            data = sock.recv(65536)
            if not data:
                return None
            client.receive_data(data)
            for event in client.events():
                if isinstance(event, CloseConnection):
                    return event.code


async def test_uvicorn_closes_a_bomb_with_1009_on_the_wire(monkeypatch):
    monkeypatch.setattr(ws_transport, "telemetry", Telemetry())
    port = _free_port()
    config = uvicorn.Config(_accepting_app, host="127.0.0.1", port=port, ws=WS_PROTOCOL, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        code = await asyncio.get_running_loop().run_in_executor(None, _bomb_client, port)
        assert code == 1009
    finally:
        server.should_exit = True
        await task


def _raw_frame(payload: bytes, *, opcode: int, fin: bool, rsv1: bool) -> bytes:
    """One masked client frame, built by hand: wsproto's own client never
    sends a final deflate block, which is the point of these tests."""
    import os
    import struct

    head = (0x80 if fin else 0) | (0x40 if rsv1 else 0) | opcode
    length = len(payload)
    if length < 126:
        header = bytes([head, 0x80 | length])
    elif length < 65536:
        header = bytes([head, 0x80 | 126]) + struct.pack("!H", length)
    else:
        header = bytes([head, 0x80 | 127]) + struct.pack("!Q", length)
    mask = os.urandom(4)
    return header + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))


def _final_block(text: bytes) -> bytes:
    import zlib

    compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
    return compressor.compress(text) + compressor.flush(zlib.Z_FINISH)


def test_input_after_a_final_deflate_block_is_refused_not_kept(monkeypatch):
    """#1234 review: after BFINAL, zlib keeps every further byte as unused
    data and inflates none of it, so a budget that counts output never saw
    fifty 1 MiB continuations pile up."""
    client, server = _open_pair(monkeypatch)
    first = _raw_frame(_final_block(b"42[\"x\"]"), opcode=1, fin=False, rsv1=True)
    junk = _raw_frame(b"\x00" * (256 * 1024), opcode=0, fin=False, rsv1=False)
    events, peak = _feed(server, first + junk)
    assert [event.code for event in events if isinstance(event, CloseConnection)] == [1007]
    assert peak < 2 * 1024 * 1024


def test_a_message_that_ends_its_stream_is_read_and_the_next_one_too(monkeypatch):
    """A final block is allowed at the end of a message (RFC 7692 §7.2.3.4);
    the next message then starts a stream of its own."""
    client, server = _open_pair(monkeypatch)
    first = _raw_frame(_final_block(b"hello"), opcode=1, fin=True, rsv1=True)
    events, _ = _feed(server, first)
    assert _text(events) == "hello"
    second = _raw_frame(_final_block(b"again"), opcode=1, fin=True, rsv1=True)
    events, _ = _feed(server, second)
    assert _text(events) == "again"
    assert not [event for event in events if isinstance(event, CloseConnection)]
