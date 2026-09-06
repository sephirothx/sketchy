"""The WebSocket transport, chosen on purpose: wsproto, with a deflate window this
module sets rather than one the client happens to ask for.

Uvicorn picks a WebSocket implementation with ``ws="auto"``: ``websockets`` if it
is importable, else ``wsproto``, else none - and *none* is silent, Socket.IO simply
falls back to long-polling. Until #561 nothing here declared a choice: ``wsproto``
only arrived because python-engineio depends on ``simple-websocket``, and a
``websockets`` package left in a dev venv switched the transport - and its deflate
window, 4 KB there against 32 KB here - without a line of configuration changing.
``server.py`` now names this class, and ``requirements.txt`` pins the library.

Two things this class does that stock uvicorn cannot be configured to do:

* **Choose the deflate window.** Uvicorn offers ``PerMessageDeflate()`` with
  wsproto's defaults (15 bits, 32 KB) and no setting to change it. The window is
  the compressor's memory of what it has already sent: a ``room_state`` is ~4.6 KB
  for 16 seats, so a 4 KB window forgets the last one before the next arrives and a
  broadcast that should cost tens of bytes costs hundreds; a 32 KB window keeps
  ~256 KB of zlib state per connection, 100 MB at 400 seats. The values here come
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

Nothing about the wire format changes: the same frames, compressed with the same
zlib level (6, wsproto's ``Z_DEFAULT_COMPRESSION``) and memLevel (zlib's default 8).
"""
from __future__ import annotations

import dataclasses
import logging

import wsproto
from uvicorn.protocols.websockets.wsproto_impl import WSProtocol
from wsproto.connection import ConnectionType
from wsproto.events import AcceptConnection
from wsproto.extensions import PerMessageDeflate

from app.services.telemetry import telemetry

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


class SizedPerMessageDeflate(PerMessageDeflate):
    """permessage-deflate that states the server window even when not asked."""

    def __init__(self) -> None:
        super().__init__(
            client_max_window_bits=CLIENT_MAX_WINDOW_BITS,
            server_max_window_bits=SERVER_MAX_WINDOW_BITS,
        )

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
        output = super().send(event)
        if isinstance(event, AcceptConnection):
            self._record("none")
        return output

    @staticmethod
    def _record(label: str) -> None:
        telemetry.note_socket_transport(label)
        expected = f"deflate-{SERVER_MAX_WINDOW_BITS}"
        if label != expected:
            logger.info("websocket accepted without the configured compression: %s", label)
        else:
            logger.debug("websocket accepted: %s", label)


class SketchyWebSocketProtocol(WSProtocol):
    """uvicorn's wsproto protocol, with the connection above in place of its own."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.conn = NegotiatingConnection(connection_type=ConnectionType.SERVER)


WS_PROTOCOL = f"{__name__}:{SketchyWebSocketProtocol.__name__}"
