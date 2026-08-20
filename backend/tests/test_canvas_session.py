import json
import re
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
from app.canvas_history import CLEAR_TAG, FILL_TAG, PATH_TAG, SHAPE_TAG
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

    budget = re.search(r"MAX_TURN_REPLAY_WORK\s*=\s*([\d_]+)", source)
    assert budget, "the client no longer declares MAX_TURN_REPLAY_WORK"
    assert int(budget.group(1).replace("_", "")) == MAX_TURN_REPLAY_WORK
