"""The release load gate's arithmetic (#461): what it reads off `/metrics`
and how it turns samples into the numbers it judges. The run itself is not a
test (R-ENG-11); its bookkeeping is."""
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from benchmarks.load import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    FAULT_NOTICE_REASONS,
    histogram_quantile,
    histogram_upper_bound,
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
sketchy_socket_packets_rejected_total{reason="flood"} 2
sketchy_canvas_recovery_notices_total{reason="deferred"} 7
sketchy_canvas_recovery_notices_total{reason="stale_generation"} 1
sketchy_db_query_duration_seconds_bucket{le="0.005"} 50
sketchy_db_query_duration_seconds_bucket{le="0.05"} 100
sketchy_db_query_duration_seconds_bucket{le="+Inf"} 100
"""


def test_the_metrics_the_gate_reads_are_parsed_by_name_with_or_without_labels():
    values = parse_metrics(METRICS)
    assert values["rss_bytes"] == 167_000_000
    assert values["sockets"] == 420
    assert values["bytes_out"] == 65_000_000
    assert values["bytes_in"] == 1_200_000
    assert values["rejected"] == 2
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
