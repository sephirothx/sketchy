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
import binascii
import logging
import time
from collections import deque
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

#: The Engine.IO control packets a client sends, exactly, by transport: CLOSE
#: and PONG on either; the upgrade's probe PING and UPGRADE on a WebSocket
#: only. Anything else is refused by the library - on polling by disconnecting
#: the socket and waiting for its queue to drain, which a client that never
#: polls again never lets happen, so the POST hung for good (#1235 review).
CONTROL_PACKETS = {
    "websocket": frozenset({"1", "2probe", "3", "5"}),
    "polling": frozenset({"1", "3"}),
}
#: Packets one polling POST may carry. The library allowed 16 and dropped the
#: whole payload past it, but a client batches by bytes, not count - a polling
#: drawer's queue behind one slow POST is two packets per frame - so the bound
#: is wider here; the byte window and the packet rate bound the cost.
MAX_PAYLOAD_PACKETS = 64
#: How long a WebSocket upgrade may take to complete its probe. The client
#: sends `2probe` as soon as the socket opens and `5` as soon as the answer
#: arrives; the library waited for ever, so an unfinished upgrade held an
#: accepted WebSocket that no ledger counted (#1235 review).
UPGRADE_DEADLINE_SECONDS = 10.0
#: The separator between packets in a polling payload.
RECORD_SEPARATOR = "\x1e"
#: What one socket may send in a second, counted on the raw message (bytes, or
#: characters for text) before anything decodes it (#1234). The packet-count
#: door let a valid 1 MB command through 480 times a second - about 43% of
#: the core for one socket, which closed nothing - while the heaviest
#: legitimate second is a drawer at the drawing budget's tunable maximum
#: (400 frames of at most 1,793 B, a third more as base64 on polling: under
#: 1 MB) or one maximal `create_room` (under 1 MiB).
INBOUND_BYTES_PER_WINDOW = 2 * 1024 * 1024
INBOUND_BYTE_WINDOW_SECONDS = 1.0

Refusal = Callable[[str, str], Awaitable[None]]


def engine_packet_problem(data: Any, transport: str = "websocket") -> str | None:
    """Why a raw inbound Engine.IO packet must not be decoded, or None.

    A binary message is a binary MESSAGE and always decodes. A text one must be
    a MESSAGE whose payload starts with a Socket.IO packet type (a digit), one
    of the control packets its transport carries (`CONTROL_PACKETS`), or - on
    polling only, where binary travels as text - a base64 binary MESSAGE
    (``b…``), which the caller decodes and refuses if it does not. Anything
    else is either refused by the library with a traceback or handed to
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
        # A WebSocket carries binary as binary frames; base64 text there is
        # nothing a browser sends, and a bad one raised outside any `try`.
        return None if transport == "polling" else "malformed"
    return None if data in CONTROL_PACKETS.get(transport, ()) else "malformed"


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
        # The socket's one WebSocket: `GuardedEngineSocket._upgrade_websocket`
        # refuses a second while this one is here.
        self.socket.websocket = self
        try:
            await self.asgi_send({"type": "websocket.accept"})
            await self.handler(self)
        finally:
            if not self.socket.upgraded and self.socket.websocket is self:
                # An upgrade that never completed: the socket goes on polling,
                # and may try again. `upgrading` too: the library clears it on
                # every failed upgrade but a probe that never arrived, and
                # while it stood every poll was answered with a NOOP and every
                # retry refused (#1288 review).
                self.socket.websocket = None
                self.socket.upgrading = False
        return ""  # the response went out as the WebSocket itself

    def _ended(self) -> bool:
        """Terminated, or the socket it carries has closed: nothing more is
        read. Reading on after a close re-created per-socket state that
        nothing would forget again (#1235 review)."""
        return self.terminated or self.socket.closed

    async def wait(self):
        if self._ended():
            raise OSError("transport terminated")
        task = asyncio.current_task()
        self._receiver = task
        try:
            while True:
                try:
                    if self.socket.upgraded:
                        event = await self.asgi_receive()
                    else:
                        # The probe and the UPGRADE: bounded, where the library
                        # waited for ever on each.
                        async with asyncio.timeout(UPGRADE_DEADLINE_SECONDS):
                            event = await self.asgi_receive()
                except TimeoutError:
                    raise OSError("the upgrade was not completed in time") from None
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
                if self._ended():
                    raise OSError("transport terminated")
                problem = self.server.inbound_problem(self.socket.sid, data, "websocket")
                if problem is None:
                    return data
                await self.server.refuse(self.socket.sid, problem)
                if self._ended():
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
    """An Engine.IO socket that can be ended, whose POSTs are screened, and
    which carries at most one WebSocket."""

    terminated = False
    websocket: GuardedWebSocket | None = None

    async def _upgrade_websocket(self, environ):
        """The library's upgrade, one at a time.

        The library checked only that the socket had not already upgraded, so
        one polling session - one ticket, one socket - could open any number
        of WebSockets at once, each waiting for a probe for ever, and a
        teardown could reach only the last (#1235 review).
        """
        if (
            self.terminated
            or self.closed
            or self.upgrading
            or self.upgraded
            or self.websocket is not None
        ):
            return self.server._bad_request("Upgrade already in progress")
        return await super()._upgrade_websocket(environ)

    async def handle_post_request(self, environ):
        """The library's POST, packet by packet, screened and stoppable.

        The library decodes a whole payload before handling any of it, so one
        bad packet was a traceback and none of the rest; and it went on
        handling the rest after the socket had been ended. And every refusal
        it raised here - an unknown packet, a body too long - it answered by
        disconnecting the socket and waiting for its queue to drain, which
        hung the request for good when the client never polled again. Nothing
        is raised from here: a refusal is counted, and one the library would
        have disconnected for ends the socket outright.
        """
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
        except ValueError:
            await self.server.refuse(self.sid, "malformed")
            return
        if length > self.server.max_http_buffer_size:
            await self.server.refuse(self.sid, "bytes")
            await self.server.terminate_socket(self)
            return
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
            problem = self.server.inbound_problem(self.sid, item, "polling")
            if problem is not None:
                await self.server.refuse(self.sid, problem)
                continue
            try:
                # Base64 binary is decoded here, and refused if it does not.
                packet = eio_packet.Packet(encoded_packet=item)
            except (ValueError, binascii.Error):
                await self.server.refuse(self.sid, "malformed")
                continue
            try:
                await self.receive(packet)
            except exceptions.EngineIOError:
                await self.server.refuse(self.sid, "malformed")


class _ByteWindow:
    """Bytes each socket has sent inside a sliding window."""

    __slots__ = ("seconds", "clock", "_sent")

    def __init__(self, seconds: float, clock: Callable[[], float]) -> None:
        self.seconds = seconds
        self.clock = clock
        self._sent: dict[str, tuple[deque, list[int]]] = {}

    def add(self, key: str, size: int) -> int:
        """Record `size` and return the window's total, this message included."""
        now = self.clock()
        entry = self._sent.get(key)
        if entry is None:
            entry = self._sent[key] = (deque(), [0])
        records, total = entry
        while records and records[0][0] <= now - self.seconds:
            total[0] -= records.popleft()[1]
        records.append((now, size))
        total[0] += size
        return total[0]

    def forget(self, key: str) -> None:
        self._sent.pop(key, None)

    def __contains__(self, key: str) -> bool:
        return key in self._sent


class BoundedEngineServer(engineio.AsyncServer):
    """Engine.IO with screened inbound packets and a teardown that ends things."""

    def __init__(self, *args: Any, clock: Callable[[], float] = time.monotonic, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # A copy: the driver table is the library module's own dict, shared by
        # every server in the process.
        self._async = {**self._async, "websocket": GuardedWebSocket}
        self._refusal: Refusal | None = None
        self.inbound_bytes = _ByteWindow(INBOUND_BYTE_WINDOW_SECONDS, clock)

    def on_refusal(self, refusal: Refusal) -> None:
        """Where a refused packet is counted: the Socket.IO door's ledger, so a
        transport-level refusal and a Socket.IO one add up to one limit."""
        self._refusal = refusal

    async def refuse(self, sid: str, reason: str) -> None:
        if self._refusal is not None:
            await self._refusal(sid, reason)

    def inbound_problem(self, sid: str, data: Any, transport: str = "websocket") -> str | None:
        """Why this raw message must not reach Engine.IO's decoder, or None.

        Sized first: a message past the socket's byte window is refused
        without being looked at, and still counts against the window - a
        client sending faster than it may is sending, refused or not.
        """
        size = len(data) if isinstance(data, (str, bytes, bytearray, memoryview)) else 0
        if self.inbound_bytes.add(sid, size) > INBOUND_BYTES_PER_WINDOW:
            return "bytes"
        return engine_packet_problem(data, transport)

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
        self.inbound_bytes.forget(getattr(socket, "sid", None))
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
        if event == "disconnect" and args:
            self.inbound_bytes.forget(args[0])
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
