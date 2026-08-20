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


def test_hash_during_active_path_matches_a_full_rescan():
    """The mid-stroke hash must equal what rescanning every action produces.

    While a path is open its record is the only one missing from the prefix
    array, so `hash` extends the stored prefix rather than walking the whole
    history. Committed actions sit behind the open path here so a regression
    that drops or double-counts the prefix cannot pass.
    """
    canvas = CanvasSession()
    for shape in ("rectangle", "ellipse", "triangle"):
        assert canvas.record_stroke("draw_shape", shape_payload(shape))
    assert canvas.record_stroke("draw_fill", {"x": 0.5, "y": 0.5, "color": "#123456"})

    assert canvas.record_stroke(
        "draw_start",
        {"x": 0.1, "y": 0.2, "color": "#ff0000", "width": 6},
    )
    assert len(canvas.hashes) == len(canvas.history) - 1
    assert canvas.hash == canvas_history_hash(canvas.history)

    # Every extension rewrites the open record, so the two must stay in step.
    for step in range(4):
        assert canvas.record_stroke(
            "draw_move",
            {"points": [{"x": 0.2 + step / 100, "y": 0.3}]},
        )
        assert len(canvas.hashes) == len(canvas.history) - 1
        assert canvas.hash == canvas_history_hash(canvas.history)

    assert canvas.record_stroke("draw_end", {})
    assert len(canvas.hashes) == len(canvas.history)
    assert canvas.hash == canvas_history_hash(canvas.history)


def test_hash_after_undo_of_an_open_path_matches_a_full_rescan():
    """Discarding or undoing the open path must leave the fast path correct."""
    canvas = CanvasSession()
    assert canvas.record_stroke("draw_shape", shape_payload())
    assert canvas.record_stroke(
        "draw_start",
        {"x": 0.4, "y": 0.4, "color": "#00ff00", "width": 2},
    )
    assert canvas.restart_active_path()
    assert canvas.hash == canvas_history_hash(canvas.history)

    assert canvas.undo_last_stroke()
    assert not canvas.history
    assert canvas.hash == canvas_history_hash(canvas.history)
