"""A refused or stalled socket is ended, not asked to leave (#1235).

These drive the real Engine.IO stack - `BoundedSocketServer.handle_request`
with an ASGI scope - so the socket, its read loop and its writer task are the
library's own. The peer is a pair of ASGI callables; "stopped reading" is a
`websocket.send` that never returns, which is what uvicorn's `send` does while
the transport is paused on a peer that is not reading.

The property under test is the one registry removal does not prove: that the
handler and the writer *finish*, and that nothing queued for the peer is still
held once they have.
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest

from app import socket_server
from app.services.telemetry import Telemetry
from app.socket_server import MAX_REJECTIONS, BoundedSocketServer
from app.socket_transport import MAX_PAYLOAD_PACKETS, engine_packet_problem

TEARDOWN_DEADLINE = 1.0


@pytest.mark.parametrize(
    ("raw", "problem"),
    [
        ("42[\"send_chat\",{}]", None),
        ("40", None),
        ("40{\"protocol\":1}", None),
        ("451-[\"draw\",{\"_placeholder\":true,\"num\":0}]", None),
        ("2", None),
        ("3", None),
        ("2probe", None),
        ("5", None),
        ("1", None),
        ("bAQID", None),
        (b"\x00\x01", None),
        ("", "malformed"),
        ("4", "malformed"),
        ("4[1,2]", "malformed"),
        ("4" + "[" * 1000, "malformed"),
        ("0", "malformed"),
        ("9", "malformed"),
        ("x", "malformed"),
        ("3" + "[" * 100, "malformed"),
    ],
)
def test_an_engine_packet_is_judged_before_the_library_decodes_it(raw, problem):
    assert engine_packet_problem(raw) == problem


# --- a peer over ASGI -----------------------------------------------------------


class Peer:
    """The client end of one ASGI connection."""

    def __init__(self, *, reading: bool = True) -> None:
        self.inbound: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []
        self.reading = reading
        self._never = asyncio.Event()

    async def receive(self):
        return await self.inbound.get()

    async def send(self, message):
        if message["type"] == "websocket.send" and not self.reading:
            await self._never.wait()  # a peer that stopped reading
        self.sent.append(message)

    def say(self, text: str) -> None:
        self.inbound.put_nowait({"type": "websocket.receive", "text": text})


def websocket_scope() -> dict:
    return {
        "type": "websocket",
        "path": "/socket.io/",
        "query_string": b"EIO=4&transport=websocket",
        "headers": [(b"host", b"test"), (b"upgrade", b"websocket"), (b"connection", b"upgrade")],
        "client": ("203.0.113.5", 5000),
    }


async def open_websocket(sio, peer: Peer) -> asyncio.Task:
    peer.inbound.put_nowait({"type": "websocket.connect"})
    task = asyncio.create_task(sio.handle_request(websocket_scope(), peer.receive, peer.send))
    for _ in range(100):
        if sio.eio.sockets:
            return task
        await asyncio.sleep(0.01)
    raise AssertionError("the handshake never registered a socket")


def build_server(monkeypatch) -> tuple[BoundedSocketServer, Telemetry]:
    store = Telemetry()
    monkeypatch.setattr(socket_server, "telemetry", store)
    # A short ping, so the ping task a socket starts is not what is left
    # running when the test counts tasks.
    return BoundedSocketServer(async_mode="asgi", ping_interval=0.05, ping_timeout=5), store


async def finished(task: asyncio.Task) -> None:
    """Within the teardown deadline. Watched, not awaited: a handler that
    swallows its cancellation and waits on a blocked writer - the bug - must
    fail the test, not hang it (`asyncio.wait_for` would wait for the cancel)."""
    await asyncio.wait({task}, timeout=TEARDOWN_DEADLINE)
    assert task.done(), "the handler is still running past the teardown deadline"


def rejected(store) -> dict[str, int]:
    return {labels[0]: count for labels, count in store.socket_packets_rejected.items()}


def retained_packets(engine_socket) -> list:
    """What the socket's queue still holds, the wake-up sentinel aside."""
    return [item for item in list(engine_socket.queue._queue) if item is not None]


async def settled(sio, before: set[asyncio.Task]) -> set[asyncio.Task]:
    """Tasks started since `before` that are still running, less the two
    server-wide loops - Engine.IO's client monitor and the backlog sweeper -
    which outlive any one socket by design."""
    await asyncio.sleep(0.2)
    server_wide = {getattr(sio.eio, "service_task_handle", None), sio._sweep_task}
    return {
        task for task in asyncio.all_tasks() - before
        if not task.done() and task not in server_wide and task is not asyncio.current_task()
    }


async def test_a_peer_sending_garbage_is_ended_while_its_writer_is_blocked(monkeypatch, caplog):
    sio, store = build_server(monkeypatch)
    before = asyncio.all_tasks()
    peer = Peer(reading=False)
    handler = await open_websocket(sio, peer)
    (engine_socket,) = sio.eio.sockets.values()

    for _ in range(MAX_REJECTIONS + 1):
        peer.say("x")  # not an Engine.IO packet at all
    # And more behind it that must never be read.
    for _ in range(50):
        peer.say('42["send_chat",{"text":"after"}]')

    await finished(handler)
    assert engine_socket.terminated
    assert sio.eio.sockets == {}
    assert retained_packets(engine_socket) == []
    assert rejected(store) == {"malformed": MAX_REJECTIONS + 1}
    assert await settled(sio, before) == set(), "the writer and the handler both finished"
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


async def test_a_socket_io_packet_that_does_not_decode_is_counted_not_a_traceback(monkeypatch, caplog):
    """Bad JSON, a nameless command, JSON nested past the decoder, an unknown
    type: each used to raise inside python-socketio and log ~3 KB."""
    sio, store = build_server(monkeypatch)
    peer = Peer()
    handler = await open_websocket(sio, peer)
    peer.say("40")
    garbage = ["42[bad", "42[]", "42[1]", "42" + "[" * 400_000, "49", "44{}", "42{\"a\":1}"]
    for raw in garbage:
        peer.say(raw)
    await asyncio.sleep(0.2)

    assert rejected(store) == {"malformed": len(garbage)}
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert sio.eio.sockets, "under the limit the socket stays"
    peer.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
    await finished(handler)


async def test_a_stalled_socket_evicted_for_its_backlog_releases_writer_and_queue(monkeypatch):
    """#602's eviction used the same close as everything else: the socket left
    the registry while the writer stayed blocked in `send` with the queue
    behind it. It now ends the same way a refused socket does."""
    sio, store = build_server(monkeypatch)
    before = asyncio.all_tasks()
    peer = Peer(reading=False)
    handler = await open_websocket(sio, peer)
    (engine_socket,) = sio.eio.sockets.values()
    peer.say("40")
    for _ in range(100):
        sid = sio.manager.sid_from_eio_sid(engine_socket.sid, "/")
        if sid is not None:
            break
        await asyncio.sleep(0.01)
    blob = "x" * (512 * 1024)
    for _ in range(socket_server.BACKLOG_MAX_BYTES // len(blob) + 2):
        await sio.emit("sync_strokes", blob, to=sid)
        await asyncio.sleep(0)

    await finished(handler)
    assert engine_socket.terminated
    assert sio.eio.sockets == {}
    assert retained_packets(engine_socket) == []
    assert await settled(sio, before) == set()


async def test_repeated_stalled_connections_leave_nothing_behind(monkeypatch):
    sio, store = build_server(monkeypatch)
    before = asyncio.all_tasks()
    for _ in range(5):
        peer = Peer(reading=False)
        handler = await open_websocket(sio, peer)
        for _ in range(MAX_REJECTIONS + 1):
            peer.say("x")
        await finished(handler)
    assert sio.eio.sockets == {}
    assert await settled(sio, before) == set()


# --- the polling transport ------------------------------------------------------


def http_scope(method: str, query: str) -> dict:
    return {
        "type": "http",
        "method": method,
        "path": "/socket.io/",
        "query_string": query.encode(),
        "headers": [(b"host", b"test"), (b"content-type", b"text/plain")],
        "client": ("203.0.113.6", 5000),
    }


async def http_request(sio, method: str, query: str, body: bytes = b"") -> tuple[int, bytes]:
    sent: list[dict] = []
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    scope = http_scope(method, query)
    if body:
        scope["headers"].append((b"content-length", str(len(body)).encode()))
    await sio.handle_request(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status, b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")


async def test_a_polling_peer_sending_garbage_is_ended_and_its_poll_released(monkeypatch, caplog):
    sio, store = build_server(monkeypatch)
    status, body = await http_request(sio, "GET", "EIO=4&transport=polling")
    assert status == 200
    sid = json.loads(body.decode()[1:])["sid"]
    engine_socket = sio.eio.sockets[sid]
    waiting = asyncio.create_task(http_request(sio, "GET", f"EIO=4&transport=polling&sid={sid}"))
    await asyncio.sleep(0.05)

    # A full payload of packets the library could not decode, twice over.
    for _ in range(2):
        payload = "\x1e".join(["x"] * MAX_PAYLOAD_PACKETS).encode()
        status, _ = await http_request(sio, "POST", f"EIO=4&transport=polling&sid={sid}", payload)
    assert engine_socket.terminated
    assert rejected(store) == {"malformed": MAX_REJECTIONS + 1}, "nothing after the cut-off is read"
    status, _ = await asyncio.wait_for(waiting, TEARDOWN_DEADLINE)
    assert status == 200, "the long-poll was answered, not left hanging"
    assert sid not in sio.eio.sockets
    assert retained_packets(engine_socket) == []
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


async def test_a_polling_payload_that_is_not_text_is_refused_quietly(monkeypatch, caplog):
    sio, store = build_server(monkeypatch)
    status, body = await http_request(sio, "GET", "EIO=4&transport=polling")
    sid = json.loads(body.decode()[1:])["sid"]
    await http_request(sio, "POST", f"EIO=4&transport=polling&sid={sid}", b"\xff\xfe")
    too_many = "\x1e".join(["2"] * (MAX_PAYLOAD_PACKETS + 1)).encode()
    await http_request(sio, "POST", f"EIO=4&transport=polling&sid={sid}", too_many)
    assert rejected(store) == {"malformed": 2}
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


# --- uvicorn's half ---------------------------------------------------------------


def test_a_send_waiting_on_a_peer_that_is_gone_is_woken():
    """Stock uvicorn leaves `send` blocked on `writable` once the connection
    is lost mid-pause; with it, Engine.IO's writer and everything queued."""
    from uvicorn.config import Config
    from uvicorn.server import ServerState

    from app.ws_transport import SketchyWebSocketProtocol

    class Transport:
        def __init__(self):
            self.aborted = False

        def get_extra_info(self, name, default=None):
            return ("127.0.0.1", 1) if name in ("peername", "sockname") else default

        def is_closing(self):
            return self.aborted

        def write(self, data):
            pass

        def abort(self):
            self.aborted = True

        def close(self):
            self.aborted = True

    async def app(scope, receive, send):  # pragma: no cover - never called
        pass

    async def scenario():
        protocol = SketchyWebSocketProtocol(Config(app=app), ServerState(), {})
        transport = Transport()
        protocol.connection_made(transport)
        protocol.pause_writing()
        waiting = asyncio.create_task(protocol.writable.wait())
        await asyncio.sleep(0)
        protocol.abort_connection()
        await asyncio.wait_for(waiting, 0.5)
        assert transport.aborted and protocol.close_sent

        # And a connection that simply drops wakes it the same way.
        protocol = SketchyWebSocketProtocol(Config(app=app), ServerState(), {})
        protocol.connection_made(Transport())
        protocol.pause_writing()
        waiting = asyncio.create_task(protocol.writable.wait())
        await asyncio.sleep(0)
        protocol.connection_lost(None)
        await asyncio.wait_for(waiting, 0.5)

    asyncio.run(scenario())
