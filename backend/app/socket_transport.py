"""The Engine.IO layer under Socket.IO: what a transport may hand up, and how one is ended.

`socket_server.py` judges Socket.IO packets. Underneath it, python-engineio
decodes each transport message into an Engine.IO packet first, and two things
there were out of reach of that door (#1235):

* **Decoding.** Engine.IO hands every text packet whose second character is not
  a digit to ``json.loads``, and raises on an empty one or an unknown type. A
  WebSocket's read loop does that decode outside any ``try``, so one such
  message ended the handler with the writer task still running and the socket
  still registered; a polling POST logged a traceback for it. Neither was
  counted. :func:`engine_packet_problem` answers first, on the raw message, and
  a message it refuses is counted and dropped without being decoded.
* **Ending a transport.** ``eio.disconnect`` queues a CLOSE packet and waits for
  the peer to read it, which a hostile peer never does, and a writer blocked in
  ``ws.send`` on a peer that stopped reading was never woken at all - the
  socket left the registry while its handler, its writer and every queued
  packet stayed in memory behind it. :meth:`BoundedEngineServer.terminate_socket`
  is the one teardown: it aborts the connection, interrupts a send or receive
  that is blocked, fires the disconnect handlers once, and drops what was
  queued, so nothing the peer sends afterwards is read and nothing queued for
  it is kept.

The WebSocket driver is replaced (:class:`GuardedWebSocket`) because it is the
one object that holds both the ASGI transport and the handler's blocked calls;
the socket class is replaced (:class:`GuardedEngineSocket`) for the polling
transport's POST, which decodes a whole payload of packets at a time.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import engineio
from engineio import exceptions
from engineio import packet as eio_packet
from engineio.async_socket import AsyncSocket

logger = logging.getLogger("sketchy.socket_transport")

#: The ASGI scope extension a server's WebSocket protocol offers to abort its
#: connection (`ws_transport.SketchyWebSocketProtocol`). Absent elsewhere, in
#: which case a teardown still interrupts the blocked calls, just without
#: dropping the TCP connection first.
ABORT_EXTENSION = "sketchy.transport.abort"

#: Engine.IO control packets a client sends: CLOSE, PING (`2probe` while
#: upgrading), PONG, UPGRADE and NOOP. OPEN is the server's.
CONTROL_TYPES = frozenset("12356")
#: Longest control packet a client sends (`2probe`, `3probe`). Past this a
#: control packet is data Engine.IO would hand to `json.loads`.
MAX_CONTROL_PACKET = 8
#: A polling POST carries this many packets at most; Engine.IO refuses more.
MAX_PAYLOAD_PACKETS = 16
#: The separator between packets in a polling payload.
RECORD_SEPARATOR = "\x1e"

Refusal = Callable[[str, str], Awaitable[None]]


def engine_packet_problem(data: Any) -> str | None:
    """Why a raw inbound Engine.IO packet must not be decoded, or None.

    A binary message is a binary MESSAGE and always decodes. A text one must be
    a MESSAGE whose payload starts with a Socket.IO packet type (a digit), a
    base64 binary MESSAGE (``b…``), or a short control packet - anything else
    is either refused by the library with a traceback or handed to
    ``json.loads``, and none of it is something a client of this protocol
    sends.
    """
    if isinstance(data, (bytes, bytearray, memoryview)):
        return None
    if not isinstance(data, str) or not data:
        return "malformed"
    kind = data[0]
    if kind == "4":
        return None if len(data) > 1 and data[1] in "0123456" else "malformed"
    if kind == "b":
        return None
    if kind in CONTROL_TYPES:
        return None if len(data) <= MAX_CONTROL_PACKET else "malformed"
    return "malformed"


class GuardedWebSocket:
    """Engine.IO's ASGI WebSocket driver, screened and able to be ended.

    A drop-in for ``engineio.async_drivers.asgi.WebSocket``: Engine.IO calls
    ``wait`` for each inbound message and ``send`` from its writer task. This
    one screens each message before Engine.IO decodes it, and remembers which
    task is inside ``wait`` or ``send`` so a teardown can interrupt it - the
    one thing nothing else can do for a writer blocked on a peer that stopped
    reading.
    """

    def __init__(self, handler, server: "BoundedEngineServer") -> None:
        self.handler = handler
        self.server = server
        # `handler` is the socket's bound `_websocket_handler`.
        self.socket: GuardedEngineSocket = handler.__self__
        self.terminated = False
        self.asgi_receive = None
        self.asgi_send = None
        self._abort: Callable[[], None] | None = None
        self._receiver: asyncio.Task | None = None
        self._sender: asyncio.Task | None = None
        self._interrupted: set[asyncio.Task] = set()

    async def __call__(self, environ):
        self.asgi_receive = environ["asgi.receive"]
        self.asgi_send = environ["asgi.send"]
        extensions = environ.get("asgi.scope", {}).get("extensions") or {}
        self._abort = extensions.get(ABORT_EXTENSION)
        self.socket.websocket = self
        await self.asgi_send({"type": "websocket.accept"})
        await self.handler(self)
        return ""  # the response went out as the WebSocket itself

    async def wait(self):
        if self.terminated:
            raise OSError("transport terminated")
        task = asyncio.current_task()
        self._receiver = task
        try:
            while True:
                try:
                    event = await self.asgi_receive()
                except asyncio.CancelledError:
                    self._interruption(task)
                    raise
                if event["type"] != "websocket.receive":
                    raise OSError("transport closed")
                data = event.get("bytes")
                if data is None:
                    data = event.get("text")
                if data is None:
                    raise OSError("empty message")
                problem = self.server.inbound_problem(self.socket.sid, data)
                if problem is None:
                    return data
                await self.server.refuse(self.socket.sid, problem)
                if self.terminated:
                    raise OSError("transport terminated")
        finally:
            self._receiver = None

    async def send(self, message) -> None:
        if self.terminated:
            raise OSError("transport terminated")
        task = asyncio.current_task()
        self._sender = task
        try:
            if isinstance(message, bytes):
                await self.asgi_send({"type": "websocket.send", "bytes": message, "text": None})
            else:
                await self.asgi_send({"type": "websocket.send", "bytes": None, "text": message})
        except asyncio.CancelledError:
            self._interruption(task)
            raise
        finally:
            self._sender = None

    async def close(self) -> None:
        if self.terminated:
            return  # the connection is already gone; there is nobody to tell
        try:
            await self.asgi_send({"type": "websocket.close"})
        except Exception:
            pass  # already closed

    def terminate(self) -> None:
        """End this transport now, from any task.

        Aborts the connection when the server offers a way to, then cancels
        whichever task is blocked in ``send`` or ``wait`` - each sees an
        ``OSError``, which is how Engine.IO's read and write loops already
        expect a dead transport to look, and both unwind.
        """
        if self.terminated:
            return
        self.terminated = True
        if self._abort is not None:
            try:
                self._abort()
            except Exception:  # pragma: no cover - the connection may already be gone
                logger.debug("could not abort %s", self.socket.sid, exc_info=True)
        current = asyncio.current_task()
        for task in (self._sender, self._receiver):
            if task is not None and task is not current and not task.done():
                self._interrupted.add(task)
                task.cancel()

    def _interruption(self, task: asyncio.Task | None) -> None:
        """Turn this transport's own cancellation into the ``OSError`` Engine.IO
        handles; anybody else's cancellation is left to propagate."""
        if task is not None and task in self._interrupted:
            self._interrupted.discard(task)
            if task.uncancel() == 0:
                raise OSError("transport terminated")


class GuardedEngineSocket(AsyncSocket):
    """An Engine.IO socket that can be ended, and whose POSTs are screened."""

    terminated = False
    websocket: GuardedWebSocket | None = None

    async def handle_post_request(self, environ):
        """The library's POST, packet by packet, screened and stoppable.

        The library decodes a whole payload before handling any of it, so one
        bad packet was a traceback and none of the rest; and it went on
        handling the rest after the socket had been ended.
        """
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
        except ValueError:
            await self.server.refuse(self.sid, "malformed")
            return
        if length > self.server.max_http_buffer_size:
            raise exceptions.ContentTooLongError()
        raw = await environ["wsgi.input"].read(length)
        try:
            body = raw.decode("utf-8")
        except UnicodeDecodeError:
            await self.server.refuse(self.sid, "malformed")
            return
        if not body:
            return
        encoded = body.split(RECORD_SEPARATOR)
        if len(encoded) > MAX_PAYLOAD_PACKETS:
            await self.server.refuse(self.sid, "malformed")
            return
        for item in encoded:
            if self.terminated or self.closed:
                return
            problem = self.server.inbound_problem(self.sid, item)
            if problem is not None:
                await self.server.refuse(self.sid, problem)
                continue
            await self.receive(eio_packet.Packet(encoded_packet=item))


class BoundedEngineServer(engineio.AsyncServer):
    """Engine.IO with screened inbound packets and a teardown that ends things."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # A copy: the driver table is the library module's own dict, shared by
        # every server in the process.
        self._async = {**self._async, "websocket": GuardedWebSocket}
        self._refusal: Refusal | None = None

    def on_refusal(self, refusal: Refusal) -> None:
        """Where a refused packet is counted: the Socket.IO door's ledger, so a
        transport-level refusal and a Socket.IO one add up to one limit."""
        self._refusal = refusal

    async def refuse(self, sid: str, reason: str) -> None:
        if self._refusal is not None:
            await self._refusal(sid, reason)

    def inbound_problem(self, sid: str, data: Any) -> str | None:
        """Why this raw message must not reach Engine.IO's decoder, or None."""
        return engine_packet_problem(data)

    async def terminate(self, sid: str, *, reason: str | None = None) -> bool:
        """End the socket named `sid`, if it is still here."""
        socket = self.sockets.get(sid)
        if socket is None:
            return False
        await self.terminate_socket(socket, reason=reason)
        return True

    async def terminate_socket(self, socket: Any, *, reason: str | None = None) -> None:
        """End one socket, completely, whatever state its transport is in.

        In order: stop the transport (a WebSocket is aborted and its blocked
        ``send``/``wait`` interrupted; a poll is woken below), fire the
        disconnect handlers once without sending a CLOSE nobody will read,
        then drop every queued packet and wake whatever waits on the queue, and
        forget the socket. Idempotent: a second call finds it terminated.
        """
        if getattr(socket, "terminated", False):
            return
        socket.terminated = True
        websocket = getattr(socket, "websocket", None)
        if websocket is not None:
            websocket.terminate()
        try:
            await socket.close(
                wait=False, abort=True, reason=reason or self.reason.SERVER_DISCONNECT
            )
        except Exception:  # pragma: no cover - the socket may already be gone
            logger.debug("could not close %s", getattr(socket, "sid", "?"), exc_info=True)
        finally:
            self._release(socket)

    def _release(self, socket: Any) -> None:
        queue = getattr(socket, "queue", None)
        if queue is not None:
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                queue.task_done()
            # Wakes a writer waiting for work, and a long-poll waiting to answer.
            queue.put_nowait(None)
        sid = getattr(socket, "sid", None)
        if sid is not None and self.sockets.get(sid) is socket:
            del self.sockets[sid]

    async def _trigger_event(self, event, *args, **kwargs):
        if event == "connect":
            # The first moment the library hands over a socket it has just
            # built (`_handle_connect`), before it has served a request of its
            # own: promote it to the guarded class. The subclass adds methods
            # only, so the object is the same socket with a screened POST and
            # a way to be ended - and the library's handshake is used as it
            # is, rather than copied here to change one constructor call.
            engine_socket = self.sockets.get(args[0]) if args else None
            if type(engine_socket) is AsyncSocket:
                engine_socket.__class__ = GuardedEngineSocket
        return await super()._trigger_event(event, *args, **kwargs)
