from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from benchmarks.canvas import (  # noqa: E402
    captured_socketio_events,
    socketio_event_frame_bytes,
    socketio_event_name,
)


def test_socketio_event_name_handles_text_binary_and_control_frames():
    assert socketio_event_name(1, '42["canvas_undo",{"revision":2}]') == "canvas_undo"
    assert socketio_event_name(1, '451-["sync_strokes",{"_placeholder":true,"num":0}]') == "sync_strokes"
    assert socketio_event_name(2, "AAEC") is None
    assert socketio_event_name(1, "2") is None


def test_socketio_event_frame_bytes_includes_binary_attachments():
    frames = [
        (1, '42["canvas_undo",1]'),
        (1, '451-["sync_strokes",{"_placeholder":true,"num":0}]'),
        (2, "AAEC"),
        (1, '42["room_state",{}]'),
    ]

    expected = len(frames[1][1].encode("utf-8")) + 3
    assert socketio_event_frame_bytes(frames, "sync_strokes") == expected
    assert socketio_event_frame_bytes(frames, "missing") == 0
    assert captured_socketio_events(frames) == [
        "canvas_undo",
        "room_state",
        "sync_strokes",
    ]
