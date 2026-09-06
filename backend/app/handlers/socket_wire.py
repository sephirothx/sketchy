"""Count what crosses the Socket.IO wire, in bytes.

The command counters say how many events the server handled and how long
each took; nothing said how much data they carried. A room of drawers is
mostly draw frames fanned out to every seat, and whether that is a
bandwidth problem is not answerable from an event count.

Three hooks, each at the narrowest place the library offers:

* every Engine.IO message the server *receives* (`_handle_eio_message`) -
  exact packet bytes in, whatever the event turns out to be;
* every Engine.IO packet the server *sends* (`eio.send_packet`) - exact
  packet bytes out, once per recipient, which is what a fan-out costs. This
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
"""
from __future__ import annotations

import socketio

from app.services.telemetry import Telemetry, payload_bytes, telemetry as default_telemetry


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

    async def counted_send_packet(sid, pkt):
        target.note_socket_bytes_out(engineio_packet_size(pkt))
        return await send_packet(sid, pkt)

    async def counted_emit(event, data=None, *args, **kwargs):
        target.socket_emit_payload(str(event), payload_bytes(data))
        return await emit(event, data, *args, **kwargs)

    sio._handle_eio_message = counted_receive
    sio.eio.send_packet = counted_send_packet
    sio.manager.emit = counted_emit
