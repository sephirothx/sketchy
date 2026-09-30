"""The release load gate's arithmetic (#461): what it reads off `/metrics`
and how it turns samples into the numbers it judges. The run itself is not a
test (R-ENG-11); its bookkeeping is."""
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from benchmarks.load import (  # noqa: E402
    DEFAULT_FLOORS,
    DEFAULT_THRESHOLDS,
    FAULT_NOTICE_REASONS,
    FINISH_GAMES_FLOORS,
    FINISH_GAMES_THRESHOLDS,
    Harness,
    database_engine,
    draw_identity,
    histogram_quantile,
    histogram_upper_bound,
    judge,
    parse_metrics,
    percentile,
)

METRICS = """
# HELP sketchy_event_loop_lag_seconds lag
sketchy_event_loop_lag_seconds_bucket{le="0.005"} 90
sketchy_event_loop_lag_seconds_bucket{le="0.025"} 98
sketchy_event_loop_lag_seconds_bucket{le="0.05"} 99
sketchy_event_loop_lag_seconds_bucket{le="0.25"} 100
sketchy_event_loop_lag_seconds_bucket{le="+Inf"} 100
sketchy_event_loop_lag_seconds_count 100
sketchy_event_loop_lag_last_seconds 0.002
sketchy_process_resident_memory_bytes 167000000
sketchy_sockets_connected 420
sketchy_socket_bytes_out_total 65000000
sketchy_socket_bytes_in_total 1200000
sketchy_ws_wire_bytes_out_total 6500000
sketchy_ws_wire_bytes_in_total 900000
sketchy_socket_bytes_out_by_event_total{event="room_state"} 40000000
sketchy_socket_bytes_out_by_event_total{event="<ack>"} 25000000
sketchy_socket_packets_rejected_total{reason="flood"} 2
sketchy_canvas_recovery_notices_total{reason="deferred"} 7
sketchy_canvas_recovery_notices_total{reason="stale_generation"} 1
sketchy_db_query_duration_seconds_bucket{le="0.005"} 50
sketchy_db_query_duration_seconds_bucket{le="0.05"} 100
sketchy_db_query_duration_seconds_bucket{le="+Inf"} 100
sketchy_draw_frames_total{kind="start",shape="base64",result="accepted"} 40
sketchy_draw_frames_total{kind="points",shape="binary",result="accepted"} 300
sketchy_draw_frames_total{kind="start",shape="base64",result="invalid"} 9
sketchy_history_write_seconds_count 12
sketchy_history_writes_abandoned_total{kind="game",reason="gone"} 1
"""


def test_the_metrics_the_gate_reads_are_parsed_by_name_with_or_without_labels():
    values = parse_metrics(METRICS)
    assert values["rss_bytes"] == 167_000_000
    assert values["sockets"] == 420
    assert values["bytes_out"] == 65_000_000
    assert values["bytes_in"] == 1_200_000
    assert values["wire_out"] == 6_500_000 and values["wire_in"] == 900_000
    assert values["rejected"] == 2
    assert values["out:room_state"] == 40_000_000 and values["out:<ack>"] == 25_000_000
    assert values["notice:deferred"] == 7 and values["notice:stale_generation"] == 1
    # Quantiles are the bucket bound the count crosses: an upper bound.
    assert values["lag_p99_ms"] == 50.0
    assert values["lag_max_ms"] == 250.0
    assert values["db_p99_ms"] == 50.0


def test_histogram_quantiles_are_bucket_upper_bounds_and_empty_histograms_are_zero():
    buckets = [(0.005, 90.0), (0.025, 98.0), (float("inf"), 100.0)]
    assert histogram_quantile(buckets, 0.5) == 0.005
    assert histogram_quantile(buckets, 0.99) == 0.025, "the +Inf bucket answers with the last finite bound"
    assert histogram_upper_bound(buckets) == 0.025
    assert histogram_quantile([], 0.99) == 0.0
    assert histogram_quantile([(0.005, 0.0), (float("inf"), 0.0)], 0.99) == 0.0


def test_percentiles_and_the_notice_reasons_that_count_as_faults():
    assert percentile([], 0.95) == 0.0
    assert percentile([5.0, 1.0, 3.0], 0.5) == 3.0
    assert percentile(list(range(1, 101)), 0.95) == 95
    assert "deferred" not in FAULT_NOTICE_REASONS, "a deferred snapshot is the bound working, not a fault"
    assert "dropped_frame" in FAULT_NOTICE_REASONS
    assert DEFAULT_THRESHOLDS["faultNotices"] == 0 and DEFAULT_THRESHOLDS["packetsRejected"] == 0


def test_the_delta_replay_reads_captured_packets_and_builds_the_patch_the_issue_describes():
    """#493: the capture holds Socket.IO packets as the client's handler sees
    them, without the Engine.IO byte; the patch is the top-level keys that
    moved, with a version, and a key that vanished is sent as null."""
    from benchmarks.room_state_deltas import changed_keys, event_name, room_state_of

    assert event_name('2["room_state",{"id":"r"}]') == "room_state"
    assert event_name('31[{"ok":true}]') == "<ack>"
    assert event_name('51-["draw",{"_placeholder":true,"num":0}]') == "draw"
    assert event_name('0{"sid":"x"}') == "<connect>"
    assert room_state_of('2["room_state",{"id":"r","players":[]}]') == {"id": "r", "players": []}
    assert room_state_of('2["chat_message",{"text":"hi"}]') is None
    assert changed_keys({"a": 1, "b": 2, "gone": 3}, {"a": 1, "b": 3}) == {"stateVersion": 1, "b": 3, "gone": None}


def test_the_decision_families_are_differenced_over_the_run():
    """#882: counters by full label set, histograms to bucket-bound quantiles."""
    from benchmarks.load import decisions

    before = parse_metrics(
        'sketchy_socket_refusals_total{event="draw",code="too_fast"} 2\n'
        'sketchy_draw_frame_width_keyframes_bucket{le="0.0"} 1\n'
        'sketchy_draw_frame_width_keyframes_bucket{le="+Inf"} 1\n'
    )
    after = parse_metrics(
        'sketchy_socket_refusals_total{event="draw",code="too_fast"} 7\n'
        'sketchy_canvas_tail_claims_total{result="hit"} 4\n'
        'sketchy_draw_frame_width_keyframes_bucket{le="0.0"} 7\n'
        'sketchy_draw_frame_width_keyframes_bucket{le="2.0"} 9\n'
        'sketchy_draw_frame_width_keyframes_bucket{le="+Inf"} 11\n'
        "sketchy_lobby_watchers 20\n"
    )
    result = decisions(before, after)
    assert result["counts"]["sketchy_socket_refusals_total"] == [({"event": "draw", "code": "too_fast"}, 5.0)]
    assert result["counts"]["sketchy_canvas_tail_claims_total"] == [({"result": "hit"}, 4.0)]
    keyframes = result["quantiles"]["sketchy_draw_frame_width_keyframes"]
    assert keyframes["count"] == 10 and keyframes["atZero"] == 6
    assert after["lobby_watchers"] == 20


def test_accepted_frames_and_written_histories_are_read_off_the_metrics():
    values = parse_metrics(METRICS)
    assert values["draw_accepted"] == 340  # the refused start is not drawing
    assert values["history_writes"] == 12
    assert values["history_abandoned"] == 1


def test_a_run_that_drew_nothing_fails_instead_of_reading_zero_latency():
    """From #1102 to #1249 every stroke opener was refused for its missing
    nonce, no viewer received a frame, and the empty fan-out percentile read
    0.0 - a pass."""
    measured = {key: 0 for key in DEFAULT_THRESHOLDS}
    measured.update(drawFramesAccepted=0, drawFanoutSamples=0, drawFanoutP95Ms=0.0)
    assert sorted(judge(measured, DEFAULT_THRESHOLDS, DEFAULT_FLOORS)) == ["drawFanoutSamples", "drawFramesAccepted"]
    measured.update(drawFramesAccepted=22_000, drawFanoutSamples=150_000)
    assert judge(measured, DEFAULT_THRESHOLDS, DEFAULT_FLOORS) == []
    # A floor the run never measured is short of it, not waived.
    del measured["drawFanoutSamples"]
    assert judge(measured, DEFAULT_THRESHOLDS, DEFAULT_FLOORS) == ["drawFanoutSamples"]


def test_a_finish_games_run_fails_when_a_room_finished_nothing_or_no_history_landed():
    thresholds = {**DEFAULT_THRESHOLDS, **FINISH_GAMES_THRESHOLDS}
    floors = {**DEFAULT_FLOORS, **FINISH_GAMES_FLOORS}
    measured = {key: 0 for key in thresholds} | {"drawFramesAccepted": 1, "drawFanoutSamples": 1}
    measured.update(roomsWithoutAFinishedGame=0, historyGamesWritten=50)
    assert judge(measured, thresholds, floors) == []
    measured.update(roomsWithoutAFinishedGame=3, historyGamesWritten=0)
    assert sorted(judge(measured, thresholds, floors)) == ["historyGamesWritten", "roomsWithoutAFinishedGame"]


def test_a_stroke_carries_the_nonce_the_server_requires():
    from app.handlers.payloads import parse_draw_payload
    from app.live_drawing import encode_live_drawing

    opener = encode_live_drawing("draw_start", {"x": 0.1, "y": 0.1, "color": "#000000", "width": 4})
    payload = parse_draw_payload(opener, draw_identity(1, 1))
    assert payload.action_identity == (1, 1)
    assert 1 <= payload.action_nonce <= 2**31 - 1


def test_the_record_names_the_database_the_server_ran_on():
    assert database_engine("postgresql+asyncpg://sketchy@127.0.0.1/gate") == "PostgreSQL"
    assert database_engine("sqlite+aiosqlite:///tmp/gate.db") == "SQLite"
    assert database_engine("") == "unknown"


def _gate_args(**overrides):
    from argparse import Namespace

    values = dict(
        base_url="http://127.0.0.1:1", no_deflate=False, capture_seat=None, rooms=1, seats=2,
        lobby_watchers=0, duration=1.0, reconnect_share=0.0, finish_games=False, shared_address=False,
    )
    values.update(overrides)
    return Namespace(**values)


def test_a_run_that_measured_nothing_is_reported_as_breaching():
    """Judged where the run is, not only in `judge`: a report built from a
    run with no drawing and no fan-out names both floors."""
    harness = Harness(_gate_args())
    report = harness.report(parse_metrics(METRICS), [], parse_metrics(METRICS), 0.0, 0.0)
    assert {"drawFanoutSamples", "drawFramesAccepted"} <= set(report["breaches"])
    assert report["passed"] is False


def test_throttled_guesses_breach_unless_every_seat_is_meant_to_share_an_address():
    harness = Harness(_gate_args())
    harness.samples.guesses_throttled = 3
    assert "guessesThrottled" in harness.report({}, [], {}, 0.0, 0.0)["breaches"]
    shared = Harness(_gate_args(shared_address=True))
    shared.samples.guesses_throttled = 3
    assert "guessesThrottled" not in shared.report({}, [], {}, 0.0, 0.0)["breaches"]


def test_a_finish_games_run_counts_an_ended_game_without_a_history_as_a_breach():
    harness = Harness(_gate_args(finish_games=True))
    harness.samples.games_ended = 3
    before = parse_metrics("sketchy_history_write_seconds_count 10\n")
    after = parse_metrics("sketchy_history_write_seconds_count 12\n")
    report = harness.report(before, [], after, 0.0, 0.0)
    assert report["measured"]["historyGamesUnwritten"] == 1
    assert "historyGamesUnwritten" in report["breaches"]
