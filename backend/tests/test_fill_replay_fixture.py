"""The fill-heavy history the browser benchmarks and thumbnail tests replay is
one the server really accepts (#1282).

`fixtures/fill_replay_100.json` is what a drawer gets onto the canvas by
filling the centre of an empty canvas a hundred times, alternating colours:
every fill repaints all 480,000 pixels, and the whole turn fits the replay
budget exactly. Regenerated here through the session every stroke goes
through, so the fixture cannot drift into a history no room would hold.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from app.canvas_history import canvas_history_hash, decode_binary_canvas_history
from app.canvas_session import MAX_TURN_REPLAY_WORK, REPLAY_WORK_BY_EVENT, CanvasSession

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "fill_replay_100.json"


def _fill(session: CanvasSession, index: int) -> bool:
    color = "#000000" if index % 2 == 0 else "#ff0000"
    return session.record_stroke("draw_fill", {"x": 0.5, "y": 0.5, "color": color})


def test_the_fill_heavy_fixture_is_a_history_the_server_accepts_whole():
    fixture = json.loads(FIXTURE.read_text())
    session = CanvasSession()
    for index in range(fixture["actions"]):
        assert _fill(session, index), f"fill {index} refused"
    # At the budget exactly: one more is refused, so this is the most fills
    # a turn can replay.
    assert session.replay_work == fixture["replayWork"] == MAX_TURN_REPLAY_WORK
    assert fixture["actions"] * REPLAY_WORK_BY_EVENT["draw_fill"] == MAX_TURN_REPLAY_WORK
    assert not _fill(session, fixture["actions"])

    payload = session.sync_payload()
    assert base64.b64encode(payload).decode("ascii") == fixture["base64"]
    assert canvas_history_hash(decode_binary_canvas_history(payload)) == fixture["historyHash"]
