"""Inbound envelopes are judged before a byte is kept (#596).

Every test drives the real `BoundedSocketServer` through `_handle_eio_message`,
the door engineio hands each packet to, with a fake engine socket underneath
so nothing needs a transport. The invariant: what one socket can hold in
assembly is one frame, whatever it declares, and a malformed packet costs the
server a counter and nothing else - no reply, no handler, no memory.
"""
from __future__ import annotations

import base64

import pytest

from app import socket_server
from app.handlers.context import HandlerContext
from app.handlers.budgets import DRAWING
from app.live_drawing import MAX_FRAME_BYTES, MAX_POINTS_PER_FRAME, encode_live_drawing
from app.rooms import RoomManager
from app.services.telemetry import Telemetry
from app.socket_server import (
    ASSEMBLY_DEADLINE_SECONDS,
    MAX_PACKETS_PER_WINDOW,
    MAX_REJECTIONS,
    BoundedSocketServer,
)

pytestmark = pytest.mark.asyncio


class FakeEngineSocket:
    closed = False

    def __init__(self) -> None:
        self.packets: list = []

    async def send(self, pkt) -> None:
        self.packets.append(pkt.encode())


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


HEADER = '51-["draw",{"_placeholder":true,"num":0}]'
HEADER_WITH_IDENTITY = '51-["draw",{"_placeholder":true,"num":0},[1,1]]'
START_FRAME = encode_live_drawing("draw_start", {"x": 0.5, "y": 0.5, "color": "#aabbcc", "width": 6})


async def server(monkeypatch, seats: int = 1):
    store = Telemetry()
    monkeypatch.setattr(socket_server, "telemetry", store)
    clock = Clock()
    sio = BoundedSocketServer(async_mode="asgi", clock=clock, async_handlers=False)
    sockets = {}
    for index in range(seats):
        eio_sid = f"eio{index}"
        sockets[eio_sid] = sio.eio.sockets[eio_sid] = FakeEngineSocket()
        await sio.manager.connect(eio_sid, "/")
    received: list = []

    @sio.on("draw")
    async def draw(sid, *args):
        received.append(("draw", args))

    @sio.on("send_chat")
    async def chat(sid, data):
        received.append(("send_chat", data))
        return {"ok": True}

    return sio, store, sockets, received, clock


def retained(sio, eio_sid="eio0") -> int:
    pkt = sio._binary_packet.get(eio_sid)
    return 0 if pkt is None else sum(len(a) for a in pkt.attachments)


def rejected(store) -> dict[str, int]:
    return {labels[0]: count for labels, count in store.socket_packets_rejected.items()}


# --- the finding ------------------------------------------------------------


async def test_a_header_declaring_many_attachments_retains_nothing(monkeypatch):
    """#596's probe: 1,000 declared, three 1 KiB chunks sent, all kept before."""
    sio, store, sockets, received, clock = await server(monkeypatch)
    await sio._handle_eio_message("eio0", '51000-["draw",{"_placeholder":true,"num":0}]')
    for _ in range(3):
        await sio._handle_eio_message("eio0", b"\x00" * 1024)
    assert retained(sio) == 0
    assert "eio0" not in sio._binary_packet
    assert received == []
    assert rejected(store) == {"attachment_count": 1, "unexpected_binary": 3}
    assert sockets["eio0"].packets == [], "a refusal is never answered"


async def test_an_attachment_larger_than_any_frame_is_dropped_with_its_assembly(monkeypatch):
    sio, store, sockets, received, clock = await server(monkeypatch)
    await sio._handle_eio_message("eio0", HEADER)
    assert "eio0" in sio._binary_packet
    await sio._handle_eio_message("eio0", b"\x11" + b"\x00" * MAX_FRAME_BYTES)
    assert retained(sio) == 0 and "eio0" not in sio._binary_packet
    assert rejected(store) == {"attachment_size": 1}
    assert received == []


async def test_an_incomplete_assembly_expires(monkeypatch):
    sio, store, sockets, received, clock = await server(monkeypatch)
    await sio._handle_eio_message("eio0", HEADER)
    clock.now += ASSEMBLY_DEADLINE_SECONDS + 1
    # The attachment finally arrives: too late, and it belongs to nothing.
    await sio._handle_eio_message("eio0", START_FRAME)
    assert "eio0" not in sio._binary_packet and "eio0" not in sio._assembly_started
    assert rejected(store) == {"stale_assembly": 1}
    assert received == []


async def test_text_during_an_assembly_drops_the_assembly_and_is_then_judged_on_its_own(monkeypatch):
    sio, store, sockets, received, clock = await server(monkeypatch)
    await sio._handle_eio_message("eio0", HEADER)
    await sio._handle_eio_message("eio0", '2["send_chat",{"text":"hi"}]')
    assert "eio0" not in sio._binary_packet
    assert rejected(store) == {"text_in_assembly": 1}
    assert received == [("send_chat", {"text": "hi"})]


@pytest.mark.parametrize(
    ("header", "reason"),
    [
        ('61-["draw",{"_placeholder":true,"num":0}]', "binary_ack"),
        ('51-["send_chat",{"_placeholder":true,"num":0}]', "binary_event"),
        ('52-["draw",{"_placeholder":true,"num":0},{"_placeholder":true,"num":1}]', "attachment_count"),
        ('50-["draw",{"_placeholder":true,"num":0}]', "attachment_count"),
        ('51-["draw",{"_placeholder":true,"num":1}]', "envelope"),
        ('51-["draw",{"_placeholder":true}]', "envelope"),
        ('51-["draw",{"text":"AQID"}]', "envelope"),
        ('51-["draw"]', "envelope"),
        ('51-["draw",{"_placeholder":true,"num":0},[1,1],[2,2]]', "envelope"),
        ('51-["draw",{"_placeholder":true,"num":0},{"_placeholder":true,"num":0}]', "envelope"),
        ('51-[{"_placeholder":true,"num":0}]', "envelope"),
        ('51-not json', "envelope"),
    ],
)
async def test_impossible_envelopes_start_no_assembly(monkeypatch, header, reason):
    sio, store, sockets, received, clock = await server(monkeypatch)
    await sio._handle_eio_message("eio0", header)
    assert "eio0" not in sio._binary_packet
    assert rejected(store) == {reason: 1}
    await sio._handle_eio_message("eio0", START_FRAME)
    assert rejected(store) == {reason: 1, "unexpected_binary": 1}
    assert received == []


async def test_binary_with_no_assembly_is_dropped(monkeypatch):
    sio, store, sockets, received, clock = await server(monkeypatch)
    await sio._handle_eio_message("eio0", b"\x10\x00")
    assert rejected(store) == {"unexpected_binary": 1}


async def test_a_flood_is_dropped_before_decoding(monkeypatch):
    sio, store, sockets, received, clock = await server(monkeypatch)
    for _ in range(MAX_PACKETS_PER_WINDOW):
        await sio._handle_eio_message("eio0", '2["send_chat",{"text":"hi"}]')
    assert len(received) == MAX_PACKETS_PER_WINDOW
    await sio._handle_eio_message("eio0", '2["send_chat",{"text":"one more"}]')
    assert len(received) == MAX_PACKETS_PER_WINDOW
    assert rejected(store) == {"flood": 1}
    clock.now += 1.1
    await sio._handle_eio_message("eio0", '2["send_chat",{"text":"later"}]')
    assert received[-1] == ("send_chat", {"text": "later"})


async def test_a_burst_at_the_drawing_budget_s_maximum_is_not_a_flood(monkeypatch):
    """The whole tunable drawing allowance, binary, inside one second, plus a
    heartbeat and a chat line: what a client bunching frames after a stall
    sends. The flood guard must sit above it (R-RATE-10)."""
    sio, store, sockets, received, clock = await server(monkeypatch)
    for _ in range(DRAWING.maximum):
        await sio._handle_eio_message("eio0", HEADER)
        await sio._handle_eio_message("eio0", START_FRAME)
    await sio._handle_eio_message("eio0", '2["session_ping",null]')
    await sio._handle_eio_message("eio0", '2["send_chat",{"text":"still here"}]')
    assert rejected(store) == {}
    assert len([r for r in received if r[0] == "draw"]) == DRAWING.maximum
    assert MAX_PACKETS_PER_WINDOW > DRAWING.maximum


async def test_a_socket_that_keeps_sending_garbage_is_closed(monkeypatch):
    sio, store, sockets, received, clock = await server(monkeypatch)
    closed = []

    async def disconnect(eio_sid):
        closed.append(eio_sid)

    monkeypatch.setattr(sio.eio, "disconnect", disconnect)
    for _ in range(MAX_REJECTIONS):
        await sio._handle_eio_message("eio0", b"\x00")
    assert closed == []
    await sio._handle_eio_message("eio0", b"\x00")
    assert closed == ["eio0"]


async def test_disconnect_clears_every_per_socket_record(monkeypatch):
    sio, store, sockets, received, clock = await server(monkeypatch)
    await sio._handle_eio_message("eio0", HEADER)
    await sio._handle_eio_message("eio0", b"\x00" * 5000)  # a rejection, and a packet count
    assert "eio0" in sio._packets._hits and "eio0" in sio._rejections._hits
    await sio._handle_eio_disconnect("eio0", "client disconnect")
    assert "eio0" not in sio._binary_packet
    assert "eio0" not in sio._assembly_started
    assert "eio0" not in sio._packets._hits and "eio0" not in sio._rejections._hits


# --- what must still pass -------------------------------------------------------


async def test_the_largest_legitimate_binary_draw_still_passes(monkeypatch):
    sio, store, sockets, received, clock = await server(monkeypatch)
    points = [{"x": (i % 2) * 0.999, "y": ((i // 2) % 2) * 0.999} for i in range(MAX_POINTS_PER_FRAME)]
    frame = encode_live_drawing("draw_move", {"points": points})
    assert len(frame) == MAX_FRAME_BYTES
    await sio._handle_eio_message("eio0", HEADER)
    assert "eio0" in sio._assembly_started
    await sio._handle_eio_message("eio0", frame)
    assert received == [("draw", (frame,))]
    assert "eio0" not in sio._binary_packet and "eio0" not in sio._assembly_started
    assert rejected(store) == {}


async def test_a_binary_draw_with_its_action_identity_passes(monkeypatch):
    sio, store, sockets, received, clock = await server(monkeypatch)
    await sio._handle_eio_message("eio0", HEADER_WITH_IDENTITY)
    await sio._handle_eio_message("eio0", START_FRAME)
    assert received == [("draw", (START_FRAME, [1, 1]))]


async def test_base64_draws_and_json_commands_are_untouched(monkeypatch):
    sio, store, sockets, received, clock = await server(monkeypatch)
    encoded = base64.b64encode(START_FRAME).decode()
    await sio._handle_eio_message("eio0", f'2["draw","{encoded}",[1,1]]')
    await sio._handle_eio_message("eio0", '21["send_chat",{"text":"hello"}]')
    assert received == [("draw", (encoded, [1, 1])), ("send_chat", {"text": "hello"})]
    assert sockets["eio0"].packets == ['431[{"ok":true}]']  # engine.io message + socket.io ack
    assert rejected(store) == {}


async def test_polling_shape_arrives_the_same_way(monkeypatch):
    """engineio decodes a polling POST's base64 attachment into bytes before
    this door, so the door sees exactly what a WebSocket delivers."""
    from engineio import packet as eio_packet

    sio, store, sockets, received, clock = await server(monkeypatch)
    polled = eio_packet.Packet(encoded_packet="b" + base64.b64encode(START_FRAME).decode())
    assert polled.binary and polled.data == START_FRAME
    await sio._handle_eio_message("eio0", HEADER_WITH_IDENTITY)
    await sio._handle_eio_message("eio0", polled.data)
    assert received == [("draw", (START_FRAME, [1, 1]))]


def test_the_packet_ceiling_is_explicit():
    sio = BoundedSocketServer(async_mode="asgi")
    assert sio.eio.max_http_buffer_size == socket_server.MAX_PACKET_BYTES


# --- arity, the other half ------------------------------------------------------


async def test_a_command_with_too_many_arguments_is_refused_not_a_type_error(monkeypatch):
    from app.handlers import context as context_module

    store = Telemetry()
    monkeypatch.setattr(context_module, "telemetry", store)
    sio = BoundedSocketServer(async_mode="asgi")
    ctx = HandlerContext(sio, RoomManager())
    seen = []

    async def session_ping(sid, data=None):
        seen.append(data)
        return [1, 0, 0, 0, 0, 0]

    ctx.on("session_ping", session_ping)
    assert await sio.handlers["/"]["session_ping"]("s1", None) == [1, 0, 0, 0, 0, 0]
    answer = await sio.handlers["/"]["session_ping"]("s1", None, "extra")
    assert answer == {"ok": False, "errorCode": "invalid_payload", "error": "Invalid request payload"}
    assert seen == [None]

    async def draw(sid, frame, identity=None):
        seen.append(("draw", frame, identity))

    ctx.on("draw", draw)
    await sio.handlers["/"]["draw"]("s1", 1, [1, 1])
    assert await sio.handlers["/"]["draw"]("s1", 1, [1, 1], "extra") is None, "draw is silent"
    assert seen[-1] == ("draw", 1, [1, 1])


def test_the_metrics_carry_the_rejection_rows():
    store = Telemetry()
    store.note_socket_packet_rejected("attachment_count")
    assert store.snapshot()["socket"]["packetsRejected"] == {"attachment_count": 1}
    assert 'sketchy_socket_packets_rejected_total{reason="attachment_count"} 1' in "\n".join(store.prometheus_lines())
