"""The WebSocket transport, chosen on purpose: wsproto, with a deflate window this
module sets rather than one the client happens to ask for.

Uvicorn picks a WebSocket implementation with ``ws="auto"``: ``websockets`` if it
is importable, else ``wsproto``, else none - and *none* is silent, Socket.IO simply
falls back to long-polling. Until #561 nothing here declared a choice: ``wsproto``
only arrived because python-engineio depends on ``simple-websocket``, and a
``websockets`` package left in a dev venv switched the transport - and its deflate
window, 4 KB there against 32 KB here - without a line of configuration changing.
``server.py`` now names this class, and ``requirements.txt`` pins the library.

Three things this module does that stock uvicorn cannot be configured to do:

* **Choose the deflate window.** Uvicorn offers ``PerMessageDeflate()`` with
  wsproto's defaults (15 bits, 32 KB) and no setting to change it. The window is
  the compressor's memory of what it has already sent: a ``room_state`` is ~4.6 KB
  for 16 seats, so a 4 KB window forgets the last one before the next arrives and a
  broadcast that should cost tens of bytes costs hundreds; a 32 KB window keeps
  zlib state per connection - measured under the release gate at ~340 KB with
  the decompressor and wsproto's buffers, ~140 MB at 420 sockets. The values here come
  from ``benchmarks/deflate_windows.py`` over recorded traffic, and the reasoning is
  written next to them.
* **Say what was negotiated.** wsproto echoes only the parameters the client
  offered, and browsers offer ``client_max_window_bits`` alone, so a smaller server
  window has to be *added* to the response - which RFC 7692 §7.1.2.1 allows: a
  client that cannot honour it must fail the handshake, and every current browser
  honours it. Each accepted connection then counts once under the compression it
  actually got (``sketchy_socket_transport_total{compression}``), and one that got
  something other than the configured target is logged, so a proxy or a client
  that strips the extension is visible instead of a mystery in the byte counters.

* **Bound what an inbound message inflates to.** wsproto decompresses a whole
  network read at once, so a deflate bomb was in memory a thousandfold before
  any size check ran; ``SizedPerMessageDeflate`` caps every decompression at
  the message's remaining budget (#1234), and a close this side decides goes
  out with its code rather than as a dropped line.

And one thing it measures (#875): the bytes the WebSocket connection actually
hands to and takes from the TCP transport once the handshake is done - frames
after permessage-deflate, headers included - as ``sketchy_ws_wire_bytes_{out,in}``.
Every other byte counter is an Engine.IO packet *before* compression, so this is
the only one that says what deflate produced, and set against those it is the
compression ratio of real traffic rather than of an offline model. It is what
this process wrote: a TLS-terminating proxy in front can recompress, and a
long-polling socket never reaches this class, so neither is in it.

Nothing about the wire format changes: the same frames, compressed with the same
zlib level (6, wsproto's ``Z_DEFAULT_COMPRESSION``) and memLevel (zlib's default 8).
"""
from __future__ import annotations

from collections import deque
import dataclasses
import logging
import time
import zlib

import wsproto
from uvicorn.protocols.websockets.wsproto_impl import WSProtocol
from wsproto.connection import ConnectionState, ConnectionType
from wsproto.events import AcceptConnection, CloseConnection
from wsproto.extensions import PerMessageDeflate
from wsproto.frame_protocol import CloseReason

from app.services.telemetry import telemetry
from app.socket_server import MAX_PACKET_BYTES
from app.socket_transport import (
    ABORT_EXTENSION,
    INBOUND_BYTE_WINDOW_SECONDS,
    INBOUND_BYTES_PER_WINDOW,
)

logger = logging.getLogger("sketchy.transport")

# The compressor window for what the server sends, as a power of two. 15 is the
# wsproto default and the most zlib allows; 13 (8 KB) is the smallest window that
# still holds a maximum-size room_state plus what usually sits between two of them.
# Measured in benchmarks/deflate_windows.py; see docs/wire-protocol.md §1.
SERVER_MAX_WINDOW_BITS = 15
# What the client's compressor may use for what it sends us. Browsers offer
# `client_max_window_bits` without a value, which lets the server pick; the
# uplink is small frames a drawer sends, and the decompressor this side keeps
# costs 1 << bits, so this is the client's memory to spend, not ours.
CLIENT_MAX_WINDOW_BITS = 15
# The most one inbound message may inflate to: Engine.IO's per-packet ceiling,
# which it checks only once the whole message has been handed up - by which
# time a compressed message has already been inflated in full (#1234).
INBOUND_MESSAGE_LIMIT = MAX_PACKET_BYTES
# The most compressed input one inbound message may carry. Deflate never
# expands data by more than a few bytes per 64 KiB block, so a legitimate
# message is never much bigger compressed than inflated; the output cap alone
# never counted input that produced nothing - empty stored blocks inflate to
# no bytes at all - and one unfinished message could stream them for ever
# (#1289 review).
INBOUND_COMPRESSED_MESSAGE_LIMIT = INBOUND_MESSAGE_LIMIT + INBOUND_MESSAGE_LIMIT // 64
# What one connection may send on the wire in a window: the Engine.IO byte
# window's allowance, counted there after inflating, plus a quarter for
# framing. Counted here before anything is inflated, so compressed input
# that inflates to little - a 1 MiB message of empty blocks around a pong
# counted as one byte up there - is bounded too (#1289 review).
INBOUND_WIRE_BYTES_PER_WINDOW = INBOUND_BYTES_PER_WINDOW + INBOUND_BYTES_PER_WINDOW // 4
# What permessage-deflate strips from the end of every compressed message, and
# the receiver appends back before the final inflate (RFC 7692 §7.2.2).
SYNC_FLUSH_TAIL = b"\x00\x00\xff\xff"


class SizedPerMessageDeflate(PerMessageDeflate):
    """permessage-deflate that states the server window even when not asked,
    and never inflates an inbound message past `INBOUND_MESSAGE_LIMIT`.

    wsproto calls ``decompress(data)`` with no ``max_length``, so one network
    read of a deflate bomb inflates about a thousandfold before anything
    counts it: 32 KB on the wire became 32 MiB in memory, and 100 sockets
    sending one 15 MiB message each - 1.5 MB uploaded - took the worker from
    194 MB to 1.76 GB, where it stayed (#1234). Here every decompression is
    capped at what is left of the message's budget plus one byte, the probe
    that proves it is over, across every frame of a fragmented message and
    the tail that completes it; the connection closes with 1009 at the first
    byte past it, having produced at most that one.
    """

    def __init__(self) -> None:
        super().__init__(
            client_max_window_bits=CLIENT_MAX_WINDOW_BITS,
            server_max_window_bits=SERVER_MAX_WINDOW_BITS,
        )
        # Bytes this message has inflated to so far, across its frames, and
        # the compressed bytes that produced them.
        self._inbound_inflated = 0
        self._inbound_input = 0

    def frame_inbound_header(self, proto, opcode, rsv, payload_length):
        if self._inbound_compressed is None:
            # The first frame of a message: continuation frames and the
            # control frames between them keep the message's running total.
            self._inbound_inflated = 0
            self._inbound_input = 0
        return super().frame_inbound_header(proto, opcode, rsv, payload_length)

    def frame_inbound_payload_data(self, proto, data):
        if not self._inbound_compressed or not self._inbound_is_compressible:
            return data
        assert self._decompressor is not None
        self._inbound_input += len(data)
        if self._inbound_input > INBOUND_COMPRESSED_MESSAGE_LIMIT:
            return CloseReason.MESSAGE_TOO_BIG
        room = INBOUND_MESSAGE_LIMIT - self._inbound_inflated
        try:
            # Never `max_length=0`, which zlib reads as "unlimited": room is
            # never negative, since the message closes the moment it is.
            inflated = self._decompressor.decompress(bytes(data), room + 1)
        except zlib.error:
            return CloseReason.INVALID_FRAME_PAYLOAD_DATA
        if self._decompressor.unused_data:
            # Input after the stream's final block (BFINAL): nothing inflates
            # it, zlib keeps every byte of it, and the budget - which counts
            # output - never sees it. Fifty 1 MiB continuations after a final
            # block were 50 MiB held with the count at 7 (#1234 review).
            return CloseReason.INVALID_FRAME_PAYLOAD_DATA
        # Output short of the cap means every input byte was consumed; output
        # at the cap is over the budget, and what is left unconsumed is never
        # inflated.
        self._inbound_inflated += len(inflated)
        if self._inbound_inflated > INBOUND_MESSAGE_LIMIT:
            return CloseReason.MESSAGE_TOO_BIG
        return inflated

    def frame_inbound_complete(self, proto, fin):
        if not fin or not self._inbound_is_compressible or not self._inbound_compressed:
            return super().frame_inbound_complete(proto, fin)
        assert self._decompressor is not None
        room = INBOUND_MESSAGE_LIMIT - self._inbound_inflated
        try:
            tail = self._decompressor.decompress(SYNC_FLUSH_TAIL, room + 1)
            if len(tail) <= room and not self._decompressor.unconsumed_tail:
                # Everything was consumed below the cap, so nothing is left
                # pending for the flush to produce beyond it.
                tail += self._decompressor.flush()
        except zlib.error:
            return CloseReason.INVALID_FRAME_PAYLOAD_DATA
        # A message that ended its stream with a final block (RFC 7692
        # §7.2.3.4 allows it) leaves only the tail appended above unused; the
        # next message then needs a stream of its own, which wsproto never
        # started - it went on feeding a finished one.
        ended = self._decompressor.eof
        if ended and self._decompressor.unused_data not in (b"", SYNC_FLUSH_TAIL):
            return CloseReason.INVALID_FRAME_PAYLOAD_DATA
        self._inbound_inflated += len(tail)
        if self._inbound_inflated > INBOUND_MESSAGE_LIMIT:
            return CloseReason.MESSAGE_TOO_BIG
        no_context_takeover = (
            self.server_no_context_takeover if proto.client else self.client_no_context_takeover
        )
        if no_context_takeover or ended:
            self._decompressor = None
        self._inbound_compressed = None
        self._inbound_inflated = 0
        return tail

    def accept(self, offer: str) -> bool | None | str:
        response = super().accept(offer)
        if response is None or response is False:
            return response
        # wsproto echoes the client's `server_max_window_bits` if it sent one and
        # says nothing if it did not. RFC 7692 lets the server answer with any
        # window no larger than what the client allowed, so the window used is
        # the smaller of the client's cap and the configured one, and it is
        # always stated - a client that offered nothing has no other way to know.
        parameters = [
            p.strip()
            for p in str(response).split(";")
            if p.strip() and not p.strip().startswith("server_max_window_bits")
        ]
        self.server_max_window_bits = min(self.server_max_window_bits, SERVER_MAX_WINDOW_BITS)
        parameters.append(f"server_max_window_bits={self.server_max_window_bits}")
        return "; ".join(parameters)


def compression_label(extensions) -> str:
    """One bounded label per connection: `deflate-<server bits>` or `none`."""
    for extension in extensions:
        if isinstance(extension, PerMessageDeflate) and extension.enabled():
            return f"deflate-{extension.server_max_window_bits}"
    return "none"


# When a connection sends and receives frames, in wsproto's own terms
# (`WSConnection.send` / `receive_data`): the wire counters use the same states,
# so a rejected handshake's HTTP response is never counted and neither half of
# a closing handshake is missed.
FRAME_SEND_STATES = (ConnectionState.OPEN, ConnectionState.REMOTE_CLOSING)
FRAME_RECEIVE_STATES = (ConnectionState.OPEN, ConnectionState.LOCAL_CLOSING)


class NegotiatingConnection(wsproto.WSConnection):
    """A server connection that swaps in the sized extension at accept time.

    Uvicorn builds ``AcceptConnection(extensions=[PerMessageDeflate()])`` inline
    and hands it to ``conn.send``; this is the one place both that event and the
    negotiated result pass through, so the substitution and the record happen
    here rather than by copying uvicorn's accept path.
    """

    def send(self, event):
        if isinstance(event, AcceptConnection) and any(
            isinstance(e, PerMessageDeflate) for e in event.extensions
        ):
            extensions = [
                SizedPerMessageDeflate() if isinstance(e, PerMessageDeflate) else e
                for e in event.extensions
            ]
            event = dataclasses.replace(event, extensions=extensions)
            output = super().send(event)
            self._record(compression_label(extensions))
            return output
        sends_a_frame = self.state in FRAME_SEND_STATES
        output = super().send(event)
        if isinstance(event, AcceptConnection):
            self._record("none")
        elif output and sends_a_frame:
            telemetry.note_ws_wire_bytes_out(len(output))
        return output

    def receive_data(self, data: bytes | None) -> None:
        # The upgrade request arrives before the connection is open; only
        # frames count, so the ratio compares like with like.
        if data and self.state in FRAME_RECEIVE_STATES:
            telemetry.note_ws_wire_bytes_in(len(data))
        super().receive_data(data)

    @staticmethod
    def _record(label: str) -> None:
        telemetry.note_socket_transport(label)
        expected = f"deflate-{SERVER_MAX_WINDOW_BITS}"
        if label != expected:
            logger.info("websocket accepted without the configured compression: %s", label)
        else:
            logger.debug("websocket accepted: %s", label)


class SketchyWebSocketProtocol(WSProtocol):
    """uvicorn's wsproto protocol, with the connection above in place of its own,
    and a way for the application to end the connection outright (#1235)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.conn = NegotiatingConnection(connection_type=ConnectionType.SERVER)
        # (arrival, size) of each read inside the wire window, and their sum.
        self._wire_reads: deque[tuple[float, int]] = deque()
        self._wire_bytes = 0

    def data_received(self, data: bytes) -> None:
        if self.conn.state in FRAME_RECEIVE_STATES and self._past_wire_window(len(data)):
            # Past what any client inflating under the Engine.IO window could
            # send: closed with 1008 and nothing more of it read (#1289 review).
            telemetry.note_socket_packet_rejected("bytes")
            if self.conn.state is ConnectionState.OPEN:
                self.transport.write(
                    self.conn.send(CloseConnection(code=1008, reason="Too much data"))
                )
            self.close_sent = True
            self.transport.close()
            return
        super().data_received(data)

    def _past_wire_window(self, size: int) -> bool:
        now = time.monotonic()
        reads = self._wire_reads
        while reads and reads[0][0] <= now - INBOUND_BYTE_WINDOW_SECONDS:
            self._wire_bytes -= reads.popleft()[1]
        reads.append((now, size))
        self._wire_bytes += size
        return self._wire_bytes > INBOUND_WIRE_BYTES_PER_WINDOW

    def handle_connect(self, event) -> None:
        super().handle_connect(event)
        # Offered through the scope, the ASGI way to hand an application an
        # extra: the task that will read it has been created, not yet run.
        self.scope["extensions"][ABORT_EXTENSION] = self.abort_connection

    def abort_connection(self) -> None:
        """Drop the connection now: nothing more is read, nothing more framed.

        A close handshake is a request the peer may ignore, and a peer
        sending garbage, or one that stopped reading, does. `abort` discards
        the write buffer and closes the socket without waiting on either, and
        `close_sent` stops `handle_events` framing anything already read.
        """
        self.close_sent = True
        if self.transport is not None:
            self.transport.abort()
        self.writable.set()

    def handle_close(self, event) -> None:
        if self.conn.state is ConnectionState.OPEN:
            # A close this side decided - a frame wsproto refused, a message
            # past the inflate budget (1009) - rather than one the peer sent:
            # wsproto leaves the connection open, and uvicorn would only drop
            # the transport. Say why first, as RFC 6455 asks.
            self.transport.write(
                self.conn.send(CloseConnection(code=event.code, reason=event.reason or ""))
            )
        super().handle_close(event)

    def connection_lost(self, exc) -> None:
        super().connection_lost(exc)
        # A send waiting for the peer to read (`writable`) is otherwise never
        # woken once the peer is gone: stock uvicorn leaves it blocked, and
        # with it Engine.IO's writer, its handler and everything it had
        # queued (#1235).
        self.writable.set()


WS_PROTOCOL = f"{__name__}:{SketchyWebSocketProtocol.__name__}"
