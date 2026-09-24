import json
import re
from pathlib import Path

import pytest

from app.canvas_history import (
    FillAction,
    PathAction,
    canvas_history_hash,
    decode_binary_canvas_history,
)
from app.canvas_history import (
    CLEAR_TAG,
    FILL_TAG,
    MAX_CANVAS_ACTIONS,
    MAX_CANVAS_POINTS,
    PATH_TAG,
    SHAPE_TAG,
)
from app.canvas_session import (
    CanvasSession,
    MAX_TURN_REPLAY_WORK,
    REPLAY_WORK_BY_EVENT,
    REPLAY_WORK_BY_TAG,
)
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
        assert history.binary_payload().hex() == fixture["binary"]
        assert canvas_history_hash(history) == fixture["hash"]


def test_versioned_cross_language_fixtures_reject_malformed_versions():
    for wire in FIXTURES["malformedVersions"]["frames"]:
        with pytest.raises(ValueError):
            decode_live_drawing(bytes.fromhex(wire))
    for fixture in FIXTURES["malformedVersions"]["histories"]:
        with pytest.raises(ValueError):
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


def fill_payload(index: int = 0) -> dict:
    return {"x": (index % 10) / 10, "y": (index % 7) / 10, "color": "#123456"}


def path_payload() -> dict:
    return {"x": 0.1, "y": 0.2, "color": "#000000", "width": 4}


def test_a_turn_stops_accepting_once_its_replay_budget_is_spent():
    """Replay runs on every other client, so one turn cannot cost them forever."""
    canvas = CanvasSession()
    affordable = MAX_TURN_REPLAY_WORK // REPLAY_WORK_BY_EVENT["draw_fill"]

    for index in range(affordable):
        assert canvas.record_stroke("draw_fill", fill_payload(index)) is True
    assert canvas.replay_work == MAX_TURN_REPLAY_WORK

    # The next fill is refused, and refusing costs nothing.
    assert canvas.record_stroke("draw_fill", fill_payload(99)) is False
    assert len(canvas.history) == affordable
    assert canvas.replay_work == MAX_TURN_REPLAY_WORK
    # Cheap actions are refused too once the budget is gone: the ceiling is
    # the turn's replay cost, not a per-action-type quota.
    assert canvas.record_stroke("draw_start", path_payload()) is False


def test_strokes_and_shapes_are_charged_far_less_than_fills():
    """A drawing is thousands of strokes; the budget must not notice them."""
    canvas = CanvasSession()
    for _ in range(600):
        assert canvas.record_stroke("draw_start", path_payload()) is True
        assert canvas.record_stroke("draw_move", {"points": [{"x": 0.3, "y": 0.4}]}) is True
        assert canvas.record_stroke("draw_end", {}) is True
    for _ in range(8):
        assert canvas.record_stroke("draw_shape", shape_payload()) is True
    for index in range(12):
        assert canvas.record_stroke("draw_fill", fill_payload(index)) is True

    # A busy real drawing: 600 strokes, 8 shapes, 12 fills.
    assert canvas.replay_work == 600 + 8 + 12 * 200
    assert canvas.replay_work < MAX_TURN_REPLAY_WORK
    # Extending a path costs nothing: the points ride inside one replayed action.
    assert canvas.record_stroke("draw_start", path_payload()) is True
    before = canvas.replay_work
    for _ in range(50):
        assert canvas.record_stroke("draw_move", {"points": [{"x": 0.5, "y": 0.5}]}) is True
    assert canvas.replay_work == before


def test_undo_hands_back_what_the_removed_action_was_charged():
    canvas = CanvasSession()
    for index in range(3):
        assert canvas.record_stroke("draw_fill", fill_payload(index)) is True
    assert canvas.replay_work == 3 * REPLAY_WORK_BY_EVENT["draw_fill"]

    assert canvas.undo_last_stroke() is True
    assert canvas.replay_work == 2 * REPLAY_WORK_BY_EVENT["draw_fill"]

    # A drawer who spends the budget and undoes their way back can carry on.
    while canvas.undo_last_stroke():
        pass
    assert canvas.replay_work == 0
    assert canvas.record_stroke("draw_fill", fill_payload(9)) is True


def test_discarding_an_active_path_refunds_it_too():
    canvas = CanvasSession()
    assert canvas.record_stroke("draw_start", path_payload()) is True
    assert canvas.replay_work == REPLAY_WORK_BY_EVENT["draw_start"]
    assert canvas.restart_active_path() is True
    assert canvas.replay_work == 0


def test_clearing_the_canvas_returns_the_whole_budget():
    """The next action after a clear throws the history away, and its cost."""
    canvas = CanvasSession()
    for index in range(20):
        assert canvas.record_stroke("draw_fill", fill_payload(index)) is True
    assert canvas.clear_canvas_stroke() is True
    # Clear itself is free, and the pre-clear history is still there for Undo.
    assert canvas.replay_work == 20 * REPLAY_WORK_BY_EVENT["draw_fill"]

    # Drawing on marks the clear permanent, and the budget resets with it.
    assert canvas.record_stroke("draw_start", path_payload()) is True
    assert canvas.replay_work == REPLAY_WORK_BY_EVENT["draw_start"]
    assert len(canvas.history) == 1


def test_the_client_cost_model_still_agrees_with_this_one():
    """The browser keeps its own copy so it can grey the fill tool out early.

    Two copies of a cost model drift, and drifting here is quiet: the client
    would refuse fills the server would have taken, or offer fills the server
    refuses - which is the silent stop the affordance exists to prevent.
    """
    source = (
        Path(__file__).parents[2] / "frontend" / "src" / "lib" / "canvasHistory.ts"
    ).read_text()

    table = re.search(
        r"REPLAY_WORK_BY_KIND[^=]*=\s*\{(?P<body>[^}]*)\}", source
    )
    assert table, "the client no longer declares REPLAY_WORK_BY_KIND"
    client_costs = {
        kind: int(cost)
        for kind, cost in re.findall(r"(\w+):\s*(\d+)", table.group("body"))
    }
    assert client_costs == {
        "path": REPLAY_WORK_BY_TAG[PATH_TAG],
        "shape": REPLAY_WORK_BY_TAG[SHAPE_TAG],
        "fill": REPLAY_WORK_BY_TAG[FILL_TAG],
        "clear": REPLAY_WORK_BY_TAG[CLEAR_TAG],
    }

    for name, expected in (
        ("MAX_TURN_REPLAY_WORK", MAX_TURN_REPLAY_WORK),
        # Long duplicated without a guard. The client now greys the pen out on
        # this one too, so a divergence would take the affordance with it.
        ("MAX_CANVAS_POINTS", MAX_CANVAS_POINTS),
        ("MAX_CANVAS_ACTIONS", MAX_CANVAS_ACTIONS),
    ):
        declared = re.search(rf"{name}\s*=\s*([\d_]+)", source)
        assert declared, f"the client no longer declares {name}"
        assert int(declared.group(1).replace("_", "")) == expected, name


# --- width changes inside a path (#828) -----------------------------------------


def _pen_path(canvas: CanvasSession) -> None:
    assert canvas.record_stroke("draw_start", {"x": 0.25, "y": 0.25, "color": "#102030", "width": 6})
    assert canvas.record_stroke(
        "draw_move",
        {"points": [{"x": 0.26, "y": 0.25}, {"x": 0.27, "y": 0.26}, {"x": 0.28, "y": 0.26}], "widths": [(0, 4), (2, 5)]},
    )
    assert canvas.record_stroke("draw_move", {"points": [{"x": 0.29, "y": 0.27}], "widths": [(0, 6)]})


def test_width_changes_are_recorded_against_the_whole_path_not_the_batch():
    canvas = CanvasSession(generation=1)
    _pen_path(canvas)
    assert canvas.record_stroke("draw_end", {})

    (path,) = canvas.history
    assert path.width == 6
    assert path.widths == [(1, 4), (3, 5), (4, 6)]
    assert len(path.points) == 5
    # A marker is never the path's last entry, so the last four bytes are
    # still its last point: what a relative frame is resolved against.
    assert canvas.history.last_path_point(0) == pytest.approx((0.29, 0.27))


def test_a_width_change_is_charged_and_refunded_as_a_point():
    canvas = CanvasSession(generation=1)
    _pen_path(canvas)
    assert canvas.point_count == 5 + 3

    assert canvas.undo_last_stroke()
    assert canvas.point_count == 0


def test_a_batch_whose_width_changes_do_not_fit_is_refused_whole():
    canvas = CanvasSession(generation=1)
    assert canvas.record_stroke("draw_start", {"x": 0.5, "y": 0.5, "color": "#000000", "width": 6})
    canvas.point_count = MAX_CANVAS_POINTS - 2
    before = bytes(canvas.history.data)

    assert not canvas.record_stroke(
        "draw_move", {"points": [{"x": 0.5, "y": 0.51}, {"x": 0.5, "y": 0.52}], "widths": [(1, 3)]}
    )
    assert bytes(canvas.history.data) == before
    assert canvas.record_stroke("draw_move", {"points": [{"x": 0.5, "y": 0.51}, {"x": 0.5, "y": 0.52}]})


def test_a_path_with_width_changes_survives_the_wire_and_the_stored_format():
    """The stored delta walk is frozen and knows nothing of markers: it recodes
    one like any other four-byte entry, and restores it exactly."""
    from app.canvas_storage import STORED_DELTA_MAGIC, prepare_stored_drawing, stored_drawing_wire_payload

    canvas = CanvasSession(generation=1)
    for stroke in range(40):
        assert canvas.record_stroke("draw_start", {"x": 0.1, "y": stroke / 50, "color": "#000000", "width": 12})
        points = [{"x": 0.1 + step / 400, "y": stroke / 50} for step in range(1, 40)]
        widths = [(step, 3 + (step // 3) % 9) for step in range(0, 39, 3)]
        assert canvas.record_stroke("draw_move", {"points": points, "widths": widths})
        assert canvas.record_stroke("draw_end", {})
    frame = canvas.sync_payload()

    decoded = decode_binary_canvas_history(frame)
    assert decoded == canvas.history
    assert canvas_history_hash(decoded) == canvas.hash
    blob, magic, _, checksum = prepare_stored_drawing(frame)
    assert magic == STORED_DELTA_MAGIC and len(blob) < len(frame)
    assert stored_drawing_wire_payload(blob, checksum=checksum) == frame


@pytest.mark.parametrize(
    "entries",
    [
        [(-32768, 5), (0, 0)],  # first: nothing to change from
        [(0, 0), (-32768, 5)],  # last: nothing to apply to
        [(0, 0), (-32768, 5), (-32768, 6), (4, 4)],  # beside another
        [(0, 0), (-32768, 0), (4, 4)],
        [(0, 0), (-32768, 65), (4, 4)],
        [(0, 0), (-32768, -1), (4, 4)],
    ],
)
def test_a_history_with_a_misplaced_or_invalid_width_marker_is_refused(entries):
    import struct

    record = struct.pack("<B3sB", 0, b"\x00\x00\x00", 6) + b"".join(struct.pack("<hh", *entry) for entry in entries)
    frame = struct.pack("<4sBH", b"SKCH", 1, 1) + struct.pack("<II", 0, len(record)) + record

    with pytest.raises(ValueError):
        decode_binary_canvas_history(frame)


def test_a_full_sync_taken_mid_stroke_carries_the_open_path():
    """#1043's premise, refuted and pinned: a viewer that painted a stroke's
    first frames and then adopted a full reply keeps the stroke, because the
    reply is built when it is sent and already holds the open path as it
    stands, hashed. The bytes are the ones
    `frontend/tests/syncAfterLiveFrames.test.mjs` feeds a viewer; this keeps
    that fixture the server's truth rather than a guess at it."""
    canvas = CanvasSession(generation=3)
    canvas.record_stroke("draw_start", {"x": 0.1, "y": 0.1, "color": "#e03131", "width": 8})
    canvas.active_draw_sequence = 1
    canvas.record_stroke("draw_move", {"points": [{"x": 0.2, "y": 0.1}, {"x": 0.3, "y": 0.2}]})

    reply = canvas.sync_payload()
    assert reply.hex() == "534b4348010100000000001100000000e03131084001f0008002f000c003e001"
    assert (canvas.revision, canvas.generation, canvas.sequence, canvas.hash) == (
        1, 3, 0, 2229650042
    )
    assert len(decode_binary_canvas_history(reply)) == 1, "the open path is in it"

    canvas.record_stroke("draw_move", {"points": [{"x": 0.4, "y": 0.3}]})
    canvas.record_stroke("draw_end", {})
    canvas.active_draw_sequence = None
    assert [canvas.generation, 1, *canvas.commit_sequence(1)[:2]] == [3, 1, 1, 3966873977]
    assert canvas.sync_payload().hex() == (
        "534b4348010100000000001500000000e03131084001f0008002f000c003e0010005d002"
    )
