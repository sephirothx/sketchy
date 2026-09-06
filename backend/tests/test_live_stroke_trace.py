"""The recorded drawing traces the wire benchmarks measure against.

It is a benchmark input, not a protocol golden, but the benchmark's numbers
are only worth reading if every frame in it is a frame the server would
accept, in the order the client would send them.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from app.live_drawing import MAX_BASE64_FRAME_BYTES, decode_live_drawing

import pytest

TRACE_DIR = Path(__file__).parents[2] / "fixtures" / "live_strokes"
TRACES = sorted(TRACE_DIR.glob("*.json"))


def test_there_are_traces_to_measure():
    assert TRACES, "an empty directory measures nothing"


@pytest.mark.parametrize("path", TRACES, ids=[p.stem for p in TRACES])
def test_every_recorded_frame_decodes_and_strokes_are_well_formed(path):
    trace = json.loads(path.read_text())
    assert trace["schemaVersion"] == 1
    assert trace["strokes"], "an empty trace measures nothing"
    total = 0
    for stroke in trace["strokes"]:
        frames = stroke["frames"]
        assert "identity" in frames[0], "an action opener carries [generation, sequence]"
        if stroke["kind"] == "path":
            assert frames[0]["event"] == "draw_start"
            assert frames[-1]["event"] == "draw_end"
            assert all(f["event"] == "draw_move" for f in frames[1:-1])
        else:
            assert len(frames) == 1
            assert frames[0]["event"] == {"fill": "draw_fill", "shape": "draw_shape", "clear": "clear_canvas"}[stroke["kind"]]
        points = 0
        for frame in frames:
            raw = frame["frame"]
            if frame["shape"] == "int":
                assert isinstance(raw, int)
                packet = decode_live_drawing(raw)
            else:
                data = base64.b64decode(raw)
                # The client chose the shape by the same threshold the server documents.
                assert (frame["shape"] == "base64") == (len(data) <= MAX_BASE64_FRAME_BYTES)
                packet = decode_live_drawing(data)
            assert packet.event == frame["event"]
            if "points" in frame:
                assert len(packet.payload["points"]) == frame["points"]
                points += frame["points"]
        assert stroke["points"] == points
        total += len(frames)
        assert [f["atMs"] for f in frames] == sorted(f["atMs"] for f in frames)
    assert trace["frames"] == total
