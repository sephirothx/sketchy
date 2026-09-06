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

import pytest
import uvicorn
import wsproto
from wsproto.connection import ConnectionType
from wsproto.events import AcceptConnection, Request
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


@pytest.mark.asyncio
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
