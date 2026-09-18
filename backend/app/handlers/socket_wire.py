"""Count what crosses the Socket.IO wire, in bytes.

The command counters say how many events the server handled and how long
each took; nothing said how much data they carried. A room of drawers is
mostly draw frames fanned out to every seat, and whether that is a
bandwidth problem is not answerable from an event count.

Three hooks, each at the narrowest place the library offers:

* every Engine.IO message the server *receives* (`_handle_eio_message`) -
  exact packet bytes in, whatever the event turns out to be;
* every Engine.IO packet the server *sends* (`eio.send_packet`) - exact
  packet bytes out, once per recipient, which is what a fan-out costs, and
  the same bytes by the event they carried (#874). This
  is the one boundary every outbound path shares: a room broadcast encodes
  its packet once and hands a copy per seat to `_send_eio_packet`, while an
  acknowledgement, a connect reply or an emit with a callback goes through
  `_send_packet` and `eio.send`. Wrapping `eio.send` alone - which is what
  #563 found - counted the second kind and missed every ordinary broadcast;
* every emit, at the manager `sio.emit` delegates to - the payload size
  once, by event name, so the size distribution of what the server says is
  known per event without paying the recipient count twice. The manager
  rather than `sio.emit` itself, so a test that stands in a mock for the
  latter still gets the mock it asked for.

The outbound size is computed from the packet, not by encoding it: an
Engine.IO packet caches its first encoding whatever the arguments, so
encoding here for the size would hand a polling writer - which needs the
base64 form of a binary packet - the raw bytes instead. The size counted is
the WebSocket shape (one type byte plus the text, or the bare bytes of a
binary attachment); the base64 growth a polling transport adds is not
modelled, nor is anything the transport does after this point: WebSocket
frame headers, permessage-deflate, TLS. These are the right numbers for "is
this room too chatty", not for a bandwidth bill.

The event is read off the packet at the same boundary rather than counted
at the emit: an emit knows its payload but not its recipients, and the one
place that sees each recipient sees only an encoded packet. Reading the name
from the packet's prefix (`2["name",…` or `51-["name",…`) is a slice and a
`find`, and a broadcast hands the *same* packet object to every seat, so it
is paid once per emit, not per recipient. A binary event goes out as a text
header announcing N attachments followed by N bare-bytes packets to the same
socket; the attachments are charged to the header's event through a small
per-socket count, removed when the last one lands. What this cannot name -
an acknowledgement, Socket.IO's connect and disconnect, a packet Engine.IO
sends itself - is `<ack>` or `<control>`, so the labelled series sums to the
unlabelled one.
"""
from __future__ import annotations

import socketio
from engineio import packet as eio_packet

from app.services.telemetry import Telemetry, payload_bytes, telemetry as default_telemetry

ACK_LABEL = "<ack>"
CONTROL_LABEL = "<control>"


def _packet_size(data) -> int:
    if isinstance(data, (bytes, bytearray, memoryview)):
        return len(data)
    if isinstance(data, str):
        return len(data.encode("utf-8"))
    return payload_bytes(data)


def engineio_packet_size(pkt) -> int:
    """Bytes one Engine.IO packet occupies as a WebSocket message.

    Deliberately not `pkt.encode()`: see the module docstring.
    """
    if pkt.binary:
        return len(pkt.data)
    if pkt.data is None:
        return 1
    return 1 + _packet_size(pkt.data)


def socketio_packet_label(data: str) -> tuple[str, int]:
    """The event an encoded Socket.IO text packet carries, and how many binary
    attachments follow it. Only the default namespace is served here, but a
    namespace prefix is skipped anyway rather than misread as a name."""
    kind = data[:1]
    attachments = 0
    start = 1
    if kind in ("5", "6"):
        dash = data.find("-")
        if dash > 1 and data[1:dash].isdigit():
            attachments = int(data[1:dash])
            start = dash + 1
    if kind in ("3", "6"):
        return ACK_LABEL, attachments
    if kind not in ("2", "5"):
        return CONTROL_LABEL, 0
    open_quote = data.find('["', start)
    close_quote = data.find('"', open_quote + 2) if open_quote >= 0 else -1
    if close_quote < 0:
        return CONTROL_LABEL, attachments
    return data[open_quote + 2:close_quote], attachments


def instrument_socket_server(
    sio: socketio.AsyncServer, store: Telemetry | None = None
) -> None:
    """Wrap the server's receive, send-packet and emit paths to count bytes.

    Fails loudly if the library has renamed what this leans on: a silent
    no-op here would be a page reporting zero traffic under load.
    """
    target = store if store is not None else default_telemetry
    if not hasattr(sio, "_handle_eio_message"):
        raise AttributeError("socketio.AsyncServer has no _handle_eio_message; wire counting needs it")
    if not hasattr(sio.eio, "send_packet"):
        raise AttributeError("engineio server has no send_packet; wire counting needs it")
    if not hasattr(sio.manager, "emit"):
        raise AttributeError("socketio manager has no emit; wire counting needs it")

    receive = sio._handle_eio_message
    send_packet = sio.eio.send_packet
    emit = sio.manager.emit

    async def counted_receive(eio_sid, data):
        target.note_socket_bytes_in(_packet_size(data))
        return await receive(eio_sid, data)

    # The last text packet labelled, by identity: a broadcast sends one packet
    # object to every recipient in turn, so the parse is paid once per emit.
    last_labelled: list = [None, CONTROL_LABEL, 0]
    # Attachments still owed to a binary header, per socket.
    pending_attachments: dict[str, list] = {}

    def label_of(sid, pkt) -> str:
        if pkt.packet_type != eio_packet.MESSAGE:
            return CONTROL_LABEL
        if pkt.binary:
            owed = pending_attachments.get(sid)
            if owed is None:
                return CONTROL_LABEL
            owed[1] -= 1
            if owed[1] <= 0:
                del pending_attachments[sid]
            return owed[0]
        if pkt is last_labelled[0]:
            label, attachments = last_labelled[1], last_labelled[2]
        else:
            label, attachments = (
                socketio_packet_label(pkt.data) if isinstance(pkt.data, str) else (CONTROL_LABEL, 0)
            )
            last_labelled[:] = [pkt, label, attachments]
        if attachments:
            pending_attachments[sid] = [label, attachments]
        return label

    async def counted_send_packet(sid, pkt):
        target.note_socket_bytes_out(engineio_packet_size(pkt), label_of(sid, pkt))
        return await send_packet(sid, pkt)

    async def counted_emit(event, data=None, *args, **kwargs):
        target.socket_emit_payload(str(event), payload_bytes(data))
        return await emit(event, data, *args, **kwargs)

    sio._handle_eio_message = counted_receive
    # The attribute alone counts nothing on the wire: socketio registered the
    # *bound* method with engineio at construction, so engineio keeps calling
    # the original whatever the instance attribute says. The registered
    # handler is what real packets reach; the attribute is what tests and
    # the bounded door call. Both are wrapped, and the load gate (#461) is
    # what noticed that only one had been.
    handlers = getattr(sio.eio, "handlers", None)
    if isinstance(handlers, dict) and "message" in handlers:
        handlers["message"] = counted_receive
    sio.eio.send_packet = counted_send_packet
    sio.manager.emit = counted_emit
