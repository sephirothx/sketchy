"""The Socket.IO server with the inbound envelope checked before anything is kept.

python-socketio reads an inbound packet in two steps. A text packet is decoded
and dispatched at once. A *binary* event arrives as a text header that declares
how many binary attachments follow, then that many binary messages; the
library keeps every attachment in memory until the declared count is met, and
only then rebuilds the event and hands it to a handler - where R-RATE-08's
budgets and `payloads.py`'s bounds finally run. Nothing in that library path
asks whether the declaration is *possible*. #596 measured it: a header
declaring 1,000 attachments followed by three 1 KiB chunks left all 3 KiB
waiting for the other 997, no handler run, no budget spent - and the header
syntax allows ten billion, each up to the 1 MiB per-packet limit.

This subclass keeps the library's assembly and puts the questions in front of
it, at `_handle_eio_message`, the one door every inbound packet uses:

* **Is this a binary envelope the client could have sent?** The only command
  that carries bytes is `draw`, with exactly one attachment (the frame), a
  placeholder in argument position 1, and at most one more argument (the
  action identity). Anything else - another event, a count other than one,
  a `BINARY_ACK` (the server never asks the client for an acknowledgement),
  a malformed placeholder - is refused before a byte is retained.
* **Is the attachment a frame?** The largest frame the codec can produce is
  `MAX_FRAME_BYTES` (a full path-points frame); an attachment past that is
  refused, so what one socket can hold in assembly is one frame, not
  attachment-count × 1 MiB.
* **Is the assembly still live?** Text arriving mid-assembly is a protocol
  violation, and an assembly older than `ASSEMBLY_DEADLINE_SECONDS` is stale;
  both drop the half-built packet.
* **Is the socket sending at a rate a client would?** A cheap per-socket
  packet count, checked before decoding, ahead of the per-command budgets
  that need the decoded event to know which class it is. Sized from the
  drawing budget's tunable maximum, and an attachment does not count.

A refused packet is dropped, not answered: an answer per malformed packet is
the amplification a flood wants. It is counted once per reason
(`sketchy_socket_packets_rejected_total{reason}`) and logged at most once per
window per socket; a socket that keeps at it past `MAX_REJECTIONS` in a
window is disconnected - it is not speaking this protocol.

Handler *arity* is the other half of "validated before a Python handler runs"
and lives beside the budgets in `HandlerContext.on`: a command with more
arguments than it takes is refused with `invalid_payload` rather than
reaching a `TypeError` inside python-socketio.

Normal traffic pays nothing it did not already pay: one dictionary lookup and
a counter per packet. See docs/wire-protocol.md §3.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

import socketio
from socketio import packet

from app.handlers.budgets import DRAWING
from app.handlers.socket_wire import engineio_packet_size
from app.live_drawing import MAX_FRAME_BYTES
from app.services.telemetry import telemetry

logger = logging.getLogger("sketchy.socket_server")

#: Commands allowed to arrive as a binary event, with the most arguments each takes
#: (the frame's placeholder plus, for `draw`, the optional action identity).
BINARY_COMMANDS: dict[str, int] = {"draw": 2}
#: One frame is one attachment; the codec cannot spread a frame over two.
MAX_ATTACHMENTS = 1
#: Bytes one attachment may carry: the largest frame the codec produces.
MAX_ATTACHMENT_BYTES = MAX_FRAME_BYTES
#: How long a declared attachment may take to arrive. A client sends the two
#: WebSocket messages back to back; seconds apart means it is not coming.
ASSEMBLY_DEADLINE_SECONDS = 5.0
#: Inbound packets one socket may send per second, counted before decoding.
#: Derived from the drawing budget's *tunable maximum*, not its default: an
#: administrator may raise drawing to `DRAWING.maximum` frames per window, and
#: after a stall a client bunches its frames, so the whole allowance can land
#: inside one second. A binary frame's attachment is not counted - it can only
#: arrive inside an assembly this door already admitted, and the assembly bounds
#: it - so a frame is one count whichever shape it took. The margin is for
#: everything else a seat sends at once (heartbeat, chat, a sync request).
#: This is a guard against a flood; the per-command budgets are the limits.
PACKET_WINDOW_SECONDS = 1.0
MAX_PACKETS_PER_WINDOW = DRAWING.maximum + 100
#: Refusals in one window after which the socket is closed.
MAX_REJECTIONS = 20
#: The per-packet ceiling engineio enforces; made explicit here rather than
#: inherited as a default. #566 owns its sizing (a custom-prompts blob is the
#: largest JSON command, 80,000 characters before escaping and UTF-8).
MAX_PACKET_BYTES = 1024 * 1024

#: Outbound backlog budget per socket (#602). Engine.IO queues every packet
#: for a socket without a bound and its writer drains the queue as fast as the
#: peer reads; a peer that stops reading holds the writer on the transport's
#: 64 KiB of slack and everything after that piles up in the queue - a full
#: canvas sync at a time, for as long as it takes the ping timeout (~45 s) to
#: notice. These two are the budget: the oldest queued packet's age, which a
#: healthy socket keeps at milliseconds and a stalled one grows at the rate of
#: the stall, and the bytes queued, the hard cap a burst of syncs cannot pass.
#: Past either the socket is closed and its queue discarded whole; the client
#: reconnects, rebinds its seat inside the grace and takes a fresh sync (§7),
#: so nothing partial is ever delivered and no draw packet is dropped
#: mid-stream. Measured under the load gate (#461): healthy sockets under the
#: full population never held more than a few packets or a few kilobytes.
BACKLOG_MAX_AGE_SECONDS = 10.0
BACKLOG_MAX_BYTES = 4 * 1024 * 1024
BACKLOG_REASONS = ("age", "bytes")
#: How often every backlog's age is re-read. Age is a property of time, not
#: of the next packet: a stalled peer on a quiet room would otherwise sit at
#: nine seconds old until something new was sent to it, and measured, the
#: ping timeout got there first (#602).
BACKLOG_SWEEP_SECONDS = 1.0

REJECTION_REASONS = (
    "flood",
    "binary_ack",
    "binary_event",
    "attachment_count",
    "envelope",
    "attachment_size",
    "text_in_assembly",
    "stale_assembly",
    "unexpected_binary",
)


class _Backlog:
    """What one socket's outbound queue holds: a size and a time per packet."""

    __slots__ = ("_records", "bytes")

    def __init__(self) -> None:
        self._records: deque[tuple[int, float]] = deque()
        self.bytes = 0

    def add(self, size: int, at: float) -> None:
        self._records.append((size, at))
        self.bytes += size

    def trim(self, queued: int) -> None:
        """Forget the oldest records past what the queue still holds."""
        while len(self._records) > max(0, queued):
            size, _ = self._records.popleft()
            self.bytes -= size

    def age(self, now: float) -> float:
        return now - self._records[0][1] if self._records else 0.0

    def __len__(self) -> int:
        return len(self._records)


class _Window:
    """Timestamps inside a sliding window, per key."""

    def __init__(self, seconds: float, clock=time.monotonic) -> None:
        self.seconds = seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> int:
        now = self.clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.seconds:
            hits.popleft()
        hits.append(now)
        return len(hits)

    def forget(self, key: str) -> None:
        self._hits.pop(key, None)


class BoundedSocketServer(socketio.AsyncServer):
    """`socketio.AsyncServer` that refuses impossible inbound envelopes first."""

    def __init__(self, *args: Any, clock=time.monotonic, **kwargs: Any) -> None:
        kwargs.setdefault("max_http_buffer_size", MAX_PACKET_BYTES)
        super().__init__(*args, **kwargs)
        self._clock = clock
        self._assembly_started: dict[str, float] = {}
        self._packets = _Window(PACKET_WINDOW_SECONDS, clock)
        self._rejections = _Window(PACKET_WINDOW_SECONDS, clock)
        # What each socket's queue holds, as (bytes, queued at) per packet,
        # trimmed to the queue's length on every send so it never describes
        # packets the writer has already taken.
        self._backlogs: dict[str, _Backlog] = {}
        self._closing_backlogs: set[str] = set()
        self._sweep_task: asyncio.Task | None = None
        original_send_packet = self.eio.send_packet

        async def bounded_send_packet(eio_sid, pkt):
            await original_send_packet(eio_sid, pkt)
            self._note_queued(eio_sid, pkt)

        self.eio.send_packet = bounded_send_packet

    # --- the door ---------------------------------------------------------

    async def _handle_eio_message(self, eio_sid: str, data: Any) -> None:
        assembling = eio_sid in self._binary_packet
        if not assembling and self._packets.hit(eio_sid) > MAX_PACKETS_PER_WINDOW:
            await self._reject(eio_sid, "flood")
            return
        if assembling:
            reason = self._attachment_problem(eio_sid, data)
            if reason is not None:
                self._drop_assembly(eio_sid)
                await self._reject(eio_sid, reason)
                if reason == "text_in_assembly" or reason == "stale_assembly":
                    # The packet itself may be a well-formed text command;
                    # judge it on its own once the dead assembly is gone.
                    if isinstance(data, str):
                        await self._handle_eio_message(eio_sid, data)
                return
            await super()._handle_eio_message(eio_sid, data)
            if eio_sid not in self._binary_packet:
                self._assembly_started.pop(eio_sid, None)
            return
        if isinstance(data, (bytes, bytearray, memoryview)):
            await self._reject(eio_sid, "unexpected_binary")
            return
        reason = self._envelope_problem(eio_sid, data)
        if reason is not None:
            await self._reject(eio_sid, reason)
            return
        await super()._handle_eio_message(eio_sid, data)
        if eio_sid in self._binary_packet:
            self._assembly_started[eio_sid] = self._clock()

    def _envelope_problem(self, eio_sid: str, data: str) -> str | None:
        """Why a text packet must not start an assembly, or None."""
        if not isinstance(data, str) or not data or data[0] not in "56":
            return None  # not a binary envelope; the library decodes it as usual
        try:
            pkt = self.packet_class(encoded_packet=data)
        except ValueError:
            return "envelope"
        if pkt.packet_type == packet.BINARY_ACK:
            return "binary_ack"
        if pkt.attachment_count != MAX_ATTACHMENTS:
            return "attachment_count"
        args = pkt.data
        if not isinstance(args, list) or not args or not isinstance(args[0], str):
            return "envelope"
        limit = BINARY_COMMANDS.get(args[0])
        if limit is None:
            return "binary_event"
        if len(args) < 2 or len(args) > limit + 1:
            return "envelope"
        if args[1] != {"_placeholder": True, "num": 0}:
            return "envelope"
        for extra in args[2:]:
            if isinstance(extra, dict) and "_placeholder" in extra:
                return "envelope"
        return None

    def _attachment_problem(self, eio_sid: str, data: Any) -> str | None:
        started = self._assembly_started.get(eio_sid)
        if started is not None and self._clock() - started > ASSEMBLY_DEADLINE_SECONDS:
            return "stale_assembly"
        if isinstance(data, str):
            return "text_in_assembly"
        if len(data) > MAX_ATTACHMENT_BYTES:
            return "attachment_size"
        return None

    def _drop_assembly(self, eio_sid: str) -> None:
        self._binary_packet.pop(eio_sid, None)
        self._assembly_started.pop(eio_sid, None)

    async def _reject(self, eio_sid: str, reason: str) -> None:
        telemetry.note_socket_packet_rejected(reason)
        count = self._rejections.hit(eio_sid)
        if count == 1:
            logger.warning("refused inbound packet from %s: %s", eio_sid, reason)
        if count > MAX_REJECTIONS:
            logger.warning("closing %s: %d malformed packets in %.0fs", eio_sid, count, PACKET_WINDOW_SECONDS)
            self._drop_assembly(eio_sid)
            try:
                await self.eio.disconnect(eio_sid)
            except Exception:  # pragma: no cover - the socket may already be gone
                logger.debug("could not close %s", eio_sid, exc_info=True)

    # --- the outbound budget (#602) ---------------------------------------

    def _note_queued(self, eio_sid: str, pkt: Any) -> None:
        """Account for a packet just queued for `eio_sid`, and close the
        socket if its backlog has passed the budget. Synchronous and cheap:
        it runs on every packet of every fan-out."""
        socket = self.eio.sockets.get(eio_sid)
        queue = getattr(socket, "queue", None)
        if socket is None or queue is None or eio_sid in self._closing_backlogs:
            return
        now = self._clock()
        backlog = self._backlogs.get(eio_sid)
        if backlog is None:
            backlog = self._backlogs[eio_sid] = _Backlog()
        backlog.add(engineio_packet_size(pkt), now)
        self._judge(eio_sid, socket, backlog, now)
        if self._sweep_task is None or self._sweep_task.done():
            self._sweep_task = asyncio.create_task(self._sweep_backlogs())

    def _judge(self, eio_sid: str, socket: Any, backlog: _Backlog, now: float) -> None:
        """Trim the record to what is still queued, note the high-water,
        and close the socket if it is past the budget."""
        backlog.trim(socket.queue.qsize())
        age = backlog.age(now)
        telemetry.note_socket_backlog(backlog.bytes, age)
        reason = "age" if age > BACKLOG_MAX_AGE_SECONDS else "bytes" if backlog.bytes > BACKLOG_MAX_BYTES else None
        if reason is None:
            return
        logger.warning(
            "closing %s: outbound backlog of %d packets, %d bytes, oldest %.1fs (%s)",
            eio_sid, len(backlog), backlog.bytes, age, reason,
        )
        telemetry.note_socket_backlog_closed(reason)
        self._closing_backlogs.add(eio_sid)
        self._backlogs.pop(eio_sid, None)
        asyncio.create_task(self._close_stalled(eio_sid, socket))

    def sweep_backlogs_once(self) -> None:
        """Re-read every socket's backlog against the clock."""
        now = self._clock()
        for eio_sid, backlog in list(self._backlogs.items()):
            socket = self.eio.sockets.get(eio_sid)
            if socket is None or getattr(socket, "queue", None) is None:
                self._backlogs.pop(eio_sid, None)
                continue
            if eio_sid in self._closing_backlogs:
                continue
            self._judge(eio_sid, socket, backlog, now)

    async def _sweep_backlogs(self) -> None:
        while True:
            await asyncio.sleep(BACKLOG_SWEEP_SECONDS)
            try:
                self.sweep_backlogs_once()
            except Exception:  # pragma: no cover - a sweep must never kill the sweeper
                logger.exception("backlog sweep failed")

    async def _close_stalled(self, eio_sid: str, socket: Any) -> None:
        """Close a socket whose writer may be stuck on the transport.

        Not `eio.disconnect`: that waits for the queue to drain, which is
        exactly what a stalled writer never does. The close aborts - no
        CLOSE packet, no join - fires the disconnect handlers so the seat
        starts its grace, and the socket is dropped from the server's
        table so the room's next fan-out simply finds nobody there. The
        transport's own slack (64 KiB) lives on until TCP gives up on the
        peer; the queue behind it does not.
        """
        try:
            await socket.close(wait=False, abort=True)
        except Exception:  # pragma: no cover - the socket may already be gone
            logger.debug("could not close stalled socket %s", eio_sid, exc_info=True)
        finally:
            if self.eio.sockets.get(eio_sid) is socket:
                del self.eio.sockets[eio_sid]
            self._closing_backlogs.discard(eio_sid)

    # --- cleanup ----------------------------------------------------------

    async def _handle_eio_disconnect(self, eio_sid: str, reason: Any) -> None:
        self._assembly_started.pop(eio_sid, None)
        self._packets.forget(eio_sid)
        self._rejections.forget(eio_sid)
        self._backlogs.pop(eio_sid, None)
        await super()._handle_eio_disconnect(eio_sid, reason)
