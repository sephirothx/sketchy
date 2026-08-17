import json
from pathlib import Path

import pytest

from app.canvas_history import (
    FillAction,
    PathAction,
    canvas_history_hash,
    decode_binary_canvas_history,
    decode_canvas_history,
    encode_canvas_history,
)
from app.canvas_session import CanvasSession
from app.live_drawing import decode_live_drawing, encode_live_drawing
from tests.checkpoint_png import tiny_png


FIXTURES = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "canvas_protocol_v1.json").read_text()
)


def shape_payload(shape="rectangle"):
    return {
        "shape": shape,
        "from": {"x": 0.1, "y": 0.2},
        "to": {"x": 0.8, "y": 0.9},
        "color": "#000000",
        "width": 4,
    }


def test_canvas_session_characterizes_history_revision_hash_and_reset():
    canvas = CanvasSession(revision=7, generation=41)

    assert canvas.record_stroke(
        "draw_start",
        {"x": 0.1, "y": 0.2, "color": "#ffffff", "width": 4},
    )
    assert canvas.record_stroke(
        "draw_move",
        {"points": [{"x": 0.2, "y": 0.3}]},
    )
    assert canvas.record_stroke("draw_end", {})
    path_hash = canvas.hash
    assert canvas.revision == 8
    assert canvas.commit_sequence(1) == (8, path_hash, "action")

    assert canvas.record_stroke("draw_shape", shape_payload())
    assert canvas.revision == 9
    assert canvas.hash != path_hash
    assert canvas.clear_canvas_stroke()
    assert canvas.undo_last_stroke()
    assert canvas.undo_last_stroke()
    assert canvas.hash == path_hash
    assert canvas.history == [
        PathAction(points=[(0.1, 0.2), (0.2, 0.3)], color=0xFFFFFF, width=4)
    ]

    replacement = CanvasSession(
        revision=canvas.revision + 1,
        generation=42,
    )
    assert replacement.history == []
    assert replacement.revision == 13
    assert replacement.generation == 42
    assert replacement.sequence == 0
    assert replacement.hash == 0


def test_canvas_session_binary_sync_and_undo_preserve_semantic_history():
    canvas = CanvasSession()
    canvas.record_stroke(
        "draw_fill",
        {"x": 0.999, "y": 0.999, "color": "#123456"},
    )

    assert decode_binary_canvas_history(canvas.sync_payload()) == [
        FillAction(x=799, y=599, color=0x123456)
    ]
    assert canvas.undo_last_stroke()
    assert canvas.history == []
    assert canvas.hash == 0


def test_versioned_cross_language_canvas_protocol_fixtures():
    assert FIXTURES["schemaVersion"] == 1
    for fixture in FIXTURES["frames"]:
        encoded = encode_live_drawing(fixture["event"], fixture["payload"])
        wire = bytes((encoded,)) if isinstance(encoded, int) else encoded
        assert wire.hex() == fixture["wire"]
        assert decode_live_drawing(encoded).event == fixture["event"]

    for fixture in FIXTURES["histories"]:
        history = decode_binary_canvas_history(bytes.fromhex(fixture["binary"]))
        assert encode_canvas_history(history) == fixture["payload"]
        assert history.binary_payload().hex() == fixture["binary"]
        assert canvas_history_hash(history) == fixture["hash"]


def test_versioned_cross_language_fixtures_reject_malformed_versions():
    for wire in FIXTURES["malformedVersions"]["frames"]:
        with pytest.raises(ValueError):
            decode_live_drawing(bytes.fromhex(wire))
    for fixture in FIXTURES["malformedVersions"]["histories"]:
        with pytest.raises(ValueError):
            if "payload" in fixture:
                decode_canvas_history(fixture["payload"])
            else:
                decode_binary_canvas_history(bytes.fromhex(fixture["binary"]))


def test_canvas_session_rejects_the_fifty_first_fill_until_checkpoint():
    canvas = CanvasSession()
    fill = {"x": 0.1, "y": 0.1, "color": "#000000"}
    for _ in range(50):
        assert canvas.record_stroke("draw_fill", fill)
    assert canvas.replay_work == 10_000
    assert canvas.record_stroke("draw_fill", fill) is False
    assert canvas.reject_reason == "replay_work"
    assert canvas.apply_checkpoint(tiny_png(), 1, canvas.hashes[0]) is None
    assert canvas.history.has_checkpoint()
    assert canvas.record_stroke("draw_fill", fill)


def test_debug_summary_tracks_window_headroom_and_compact_need():
    canvas = CanvasSession()
    fill = {"x": 0.1, "y": 0.1, "color": "#000000"}
    empty = canvas.debug_summary()
    assert "work=0/10000 (0%)" in empty
    assert "compact80=ok" in empty
    assert "next_fill=ok" in empty
    for _ in range(40):
        assert canvas.record_stroke("draw_fill", fill)
    at_threshold = canvas.debug_summary()
    assert "work=8000/10000 (80%)" in at_threshold
    assert "compact80=ok" in at_threshold
    assert "next_fill=ok" in at_threshold
    assert "hottest=work@80%" in at_threshold
    assert canvas.record_stroke("draw_fill", fill)
    over_threshold = canvas.debug_summary()
    assert "work=8200/10000 (82%)" in over_threshold
    assert "compact80=fold 1" in over_threshold
    for _ in range(9):
        assert canvas.record_stroke("draw_fill", fill)
    full = canvas.debug_summary()
    assert "work=10000/10000 (100%)" in full
    assert "next_fill=fold 1" in full
    assert canvas.history.checkpoint_png_size() == 0
    prefix = canvas.hashes[0]
    assert canvas.apply_checkpoint(tiny_png(), 1, prefix) is None
    after = canvas.debug_summary()
    assert canvas.history.checkpoint_png_size() == len(tiny_png())
    assert f"png={len(tiny_png())}B" in after
    assert "work=9800/10000 (98%)" in after


def test_canvas_session_undo_stops_at_checkpoint():
    canvas = CanvasSession()
    fill = {"x": 0.2, "y": 0.2, "color": "#abcdef"}
    assert canvas.record_stroke("draw_fill", fill)
    prefix = canvas.hash
    assert canvas.record_stroke("draw_fill", fill)
    assert canvas.apply_checkpoint(tiny_png(), 1, prefix) is None
    assert canvas.undo_last_stroke() is True
    assert canvas.history.has_checkpoint()
    assert canvas.undo_last_stroke() is False


def test_clear_then_new_action_drops_checkpoint():
    canvas = CanvasSession()
    fill = {"x": 0.3, "y": 0.3, "color": "#123456"}
    assert canvas.record_stroke("draw_fill", fill)
    prefix = canvas.hash
    assert canvas.record_stroke("draw_fill", fill)
    assert canvas.apply_checkpoint(tiny_png(), 1, prefix) is None
    assert canvas.clear_canvas_stroke()
    assert canvas.record_stroke("draw_shape", shape_payload())
    assert canvas.history.has_checkpoint() is False
    assert len(canvas.history) == 1


def test_canvas_session_rejects_invalid_checkpoint_png():
    canvas = CanvasSession()
    canvas.record_stroke("draw_fill", {"x": 0.1, "y": 0.1, "color": "#000000"})
    assert canvas.apply_checkpoint(b"not-a-png", 1, canvas.hash) == "checkpoint"
    assert canvas.apply_checkpoint(tiny_png(), 2, canvas.hash) == "checkpoint"
    assert canvas.apply_checkpoint(tiny_png(), 1, 0xDEADBEEF) == "checkpoint"

