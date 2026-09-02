"""The probe's wire handling, checked without a server.

The end-to-end run against a live server is `tests/e2e/test_probe.py`; this
is the part that can be wrong on its own: the Engine.IO payload framing,
the Socket.IO packet grammar with acknowledgements and binary attachments,
and the textfile a scrape reads.
"""
from __future__ import annotations

import pytest

from app.probe import (
    DRAW_START_FRAME,
    PROBE_METRIC_NAMES,
    PollingSocket,
    ProbeResult,
    decode_payload,
    encode_payload,
    parse_message,
)


def test_a_polling_payload_round_trips_text_and_binary():
    packets = ["40", '42["guess",{"text":"cat"}]', b"\x10\xaa\xbb\xcc\x04\x20\x03\xb0\x04"]
    assert decode_payload(encode_payload(packets)) == packets
    assert decode_payload(b"") == []
    assert encode_payload([b"\x00\x01"]) == b"bAAE="


@pytest.mark.parametrize(
    ("packet", "expected"),
    [
        ('42["room_state",{"a":1}]', ("2", 0, None, ["room_state", {"a": 1}])),
        ('427["create_room",{"nickname":"x"}]', ("2", 0, 7, ["create_room", {"nickname": "x"}])),
        ("437[{\"ok\":true}]", ("3", 0, 7, [{"ok": True}])),
        ('451-["draw",{"_placeholder":true,"num":0}]', ("5", 1, None, ["draw", {"_placeholder": True, "num": 0}])),
        ('451-3["draw",{"_placeholder":true,"num":0},[1,2]]', ("5", 1, 3, ["draw", {"_placeholder": True, "num": 0}, [1, 2]])),
        ('40{"sid":"abc"}', ("0", 0, None, {"sid": "abc"})),
        ("40", ("0", 0, None, [])),
    ],
)
def test_socket_io_packets_are_split_into_kind_attachments_ack_and_data(packet, expected):
    assert parse_message(packet) == expected


def test_an_emit_with_binary_becomes_a_placeholder_packet_and_an_attachment():
    socket = PollingSocket("http://x", transport=None, cookie="", label="t")  # type: ignore[arg-type]
    packets = socket._packets("draw", (DRAW_START_FRAME, [3, 1]))
    assert packets == [
        '451-["draw",{"_placeholder":true,"num":0},[3,1]]',
        DRAW_START_FRAME,
    ]
    assert socket._packets("leave_room", ()) == ['42["leave_room"]']
    assert socket._packets("start_game", ({},), 4) == ['424["start_game",{}]']


def test_a_binary_event_is_delivered_once_its_attachment_has_arrived():
    socket = PollingSocket("http://x", transport=None, cookie="", label="t")  # type: ignore[arg-type]
    socket._handle('451-["draw",{"_placeholder":true,"num":0},[1,2,3,4]]')
    assert socket._events.empty()
    socket._handle(DRAW_START_FRAME)
    event = socket._events.get_nowait()
    assert event.name == "draw"
    assert event.args == [DRAW_START_FRAME, [1, 2, 3, 4]]


def test_the_textfile_carries_the_three_probe_series():
    result = ProbeResult(ok=True, steps={"guest": 0.1, "draw": 0.02}, duration_seconds=1.5)
    text = result.as_textfile()
    for name in PROBE_METRIC_NAMES:
        assert f"# TYPE {name} gauge" in text
    assert "sketchy_probe_success 1\n" in text
    assert 'sketchy_probe_step_seconds{step="draw"} 0.020' in text
    failed = ProbeResult(ok=False, failed_step="join", error="refused")
    assert "sketchy_probe_success 0\n" in failed.as_textfile()
    assert failed.as_json()["failedStep"] == "join"
