"""Count what crosses the Socket.IO wire, in bytes.

The command counters say how many events the server handled and how long
each took; nothing said how much data they carried. A room of drawers is
mostly draw frames fanned out to every seat, and whether that is a
bandwidth problem is not answerable from an event count.

Three hooks, each at the narrowest place the library offers:

* every Engine.IO message the server *receives* (`_handle_eio_message`) -
  exact packet bytes in, whatever the event turns out to be;
* every Engine.IO message the server *sends* (`eio.send`) - exact packet
  bytes out, once per recipient, which is what a fan-out costs;
* every emit, at the manager `sio.emit` delegates to - the payload size
  once, by event name, so the size distribution of what the server says is
  known per event without paying the recipient count twice. The manager
  rather than `sio.emit` itself, so a test that stands in a mock for the
  latter still gets the mock it asked for.

All of it is measured before compression. The wire deflates, so these
numbers overstate what a network sees; they are the right numbers for "is
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


def instrument_socket_server(
    sio: socketio.AsyncServer, store: Telemetry | None = None
) -> None:
    """Wrap the server's send, receive and emit paths to count bytes.

    Fails loudly if the library has renamed what this leans on: a silent
    no-op here would be a page reporting zero traffic under load.
    """
    target = store if store is not None else default_telemetry
    if not hasattr(sio, "_handle_eio_message"):
        raise AttributeError("socketio.AsyncServer has no _handle_eio_message; wire counting needs it")
    if not hasattr(sio.eio, "send"):
        raise AttributeError("engineio server has no send; wire counting needs it")
    if not hasattr(sio.manager, "emit"):
        raise AttributeError("socketio manager has no emit; wire counting needs it")

    receive = sio._handle_eio_message
    send = sio.eio.send
    emit = sio.manager.emit

    async def counted_receive(eio_sid, data):
        target.note_socket_bytes_in(_packet_size(data))
        return await receive(eio_sid, data)

    async def counted_send(sid, data):
        target.note_socket_bytes_out(_packet_size(data))
        return await send(sid, data)

    async def counted_emit(event, data=None, *args, **kwargs):
        target.socket_emit_payload(str(event), payload_bytes(data))
        return await emit(event, data, *args, **kwargs)

    sio._handle_eio_message = counted_receive
    sio.eio.send = counted_send
    sio.manager.emit = counted_emit
