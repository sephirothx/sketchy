"""The process signals: what is counted, how it is bucketed, and what it costs."""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from app.services.readiness import LoopHealth
from app.services.telemetry import (
    FAST_BUCKETS,
    HTTP_BUCKETS,
    MAX_SERIES,
    OTHER_LABEL,
    RING_MINUTES,
    WINDOW_MINUTES,
    CountRing,
    Histogram,
    LabelledCounter,
    MinuteRing,
    PoolGauges,
    SampleRing,
    Telemetry,
    quantile,
    run_lag_sampler,
)


class Clock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.wall = start
        self.mono = 50.0

    def advance(self, seconds: float) -> None:
        self.wall += seconds
        self.mono += seconds


def store(clock: Clock | None = None) -> tuple[Telemetry, Clock]:
    clock = clock or Clock()
    return Telemetry(clock=lambda: clock.wall, monotonic=lambda: clock.mono), clock


# --- rings -------------------------------------------------------------------


def test_a_ring_slot_is_reset_when_its_minute_has_passed():
    ring = MinuteRing(lambda: [0], minutes=3)
    ring.slot(0.0)[0] = 7
    # Three minutes later the same index comes round again; the old value
    # must not be read as this minute's.
    assert ring.points(180.0) == [None, None, None]
    assert ring.slot(180.0) == [0]


def test_points_are_oldest_first_with_gaps_where_nothing_was_written():
    ring = CountRing(minutes=4)
    ring.bump(0.0)
    ring.bump(120.0, by=3)
    assert ring.points(180.0) == [1, None, 3, None]
    assert ring.window_total(180.0, minutes=4) == 4
    assert ring.window_total(180.0, minutes=2) == 3


def test_a_sample_ring_keeps_the_max_and_the_mean_of_each_minute():
    ring = SampleRing(minutes=2)
    ring.add(0.0, 1.0)
    ring.add(1.0, 3.0)
    assert ring.points_max(0.0) == [None, 3.0]
    assert ring.points_mean(0.0) == [None, 2.0]


# --- counters and histograms ---------------------------------------------------


def test_a_labelled_counter_folds_the_long_tail_into_other():
    counter = LabelledCounter("x_total", "x", ("route",))
    for index in range(MAX_SERIES):
        counter.inc((f"/r/{index}",))
    counter.inc(("/one/too/many",))
    counter.inc(("/and/another",))
    assert counter.get(("/one/too/many",)) == 0
    assert counter.get((OTHER_LABEL,)) == 2
    assert counter.overflowed == 2
    assert counter.total() == MAX_SERIES + 2


def test_counter_exposition_escapes_label_values():
    counter = LabelledCounter("x_total", "x", ("route",))
    counter.inc(('a"b\\c\nd',))
    assert 'x_total{route="a\\"b\\\\c\\nd"} 1' in counter.lines()


def test_a_histogram_places_a_sample_in_the_first_bucket_that_holds_it():
    histogram = Histogram("h", "h", HTTP_BUCKETS)
    histogram.observe(0.005, now=0.0)  # exactly on a bound belongs to that bound
    histogram.observe(0.0051, now=0.0)
    histogram.observe(99.0, now=0.0)  # past every bound: +Inf
    lines = histogram.lines()
    assert 'h_bucket{le="0.005"} 1' in lines
    assert 'h_bucket{le="0.01"} 2' in lines
    assert 'h_bucket{le="10.0"} 2' in lines
    assert 'h_bucket{le="+Inf"} 3' in lines
    assert "h_count 3" in lines
    assert lines[0] == "# HELP h h"
    assert lines[1] == "# TYPE h histogram"
    assert lines.count("# TYPE h histogram") == 1


def test_a_histogram_refuses_unsorted_buckets():
    with pytest.raises(ValueError):
        Histogram("h", "h", (0.5, 0.1))


def test_quantiles_interpolate_inside_the_bucket_the_rank_falls_in():
    buckets = (0.1, 0.2, 0.3)
    # 100 samples, all between 0.1 and 0.2: p50 is halfway through that bucket.
    assert quantile(0.5, buckets, [0, 100, 0, 0]) == pytest.approx(0.15)
    # Everything past the last bound: the last bound is all that is known.
    assert quantile(0.99, buckets, [0, 0, 0, 10]) == 0.3
    assert quantile(0.5, buckets, [0, 0, 0, 0]) is None


def test_windowed_quantiles_only_see_the_trailing_window():
    _, clock = store()
    histogram = Histogram("h", "h", FAST_BUCKETS)
    histogram.observe(2.0, now=clock.wall)  # slow, but an hour ago
    clock.advance(60 * (WINDOW_MINUTES + 1))
    for _ in range(10):
        histogram.observe(0.001, now=clock.wall)
    windowed = histogram.windowed(clock.wall)
    assert windowed["count"] == 10
    assert windowed["p95"] <= FAST_BUCKETS[0]
    # The cumulative exposition still carries the slow one.
    assert "h_count 11" in histogram.lines()


# --- the store ---------------------------------------------------------------


def test_probes_and_static_files_are_counted_but_not_timed():
    telemetry, _ = store()
    telemetry.http_request("GET", "/api/health", 200, 0.5)
    telemetry.http_request("GET", "static", 200, 0.5)
    telemetry.http_request("GET", "/api/rooms", 200, 0.02)
    assert telemetry.http_requests.total() == 3
    assert telemetry.http_duration.count() == 1


def test_only_server_errors_count_against_the_http_error_rate():
    telemetry, _ = store()
    telemetry.http_request("GET", "/api/x", 404, 0.01)
    telemetry.http_request("GET", "/api/x", 500, 0.01)
    telemetry.http_request("GET", "/api/x", "aborted", 0.01)
    snapshot = telemetry.snapshot()
    assert snapshot["http"]["errorRate"] == pytest.approx(1 / 3, abs=1e-4)
    assert telemetry.http_requests.get(("GET", "/api/x", "aborted")) == 1


def test_socket_outcomes_are_a_closed_set():
    telemetry, _ = store()
    telemetry.socket_event("draw", "ok", 0.001)
    telemetry.socket_event("guess", "refused", 0.001)
    telemetry.socket_event("guess", "error", 0.001)
    telemetry.socket_event("draw", "throttled", None)
    with pytest.raises(ValueError):
        telemetry.socket_event("draw", "meh", 0.001)
    socket = telemetry.snapshot()["socket"]
    assert socket["total"] == 4
    assert socket["errorRate"] == 0.25
    assert socket["refusedRate"] == 0.25
    # Throttled commands ran no handler, so they are not in the latency.
    assert telemetry.socket_duration.count() == 3


def test_a_young_process_reports_a_rate_over_the_time_it_has_actually_lived():
    telemetry, clock = store()
    clock.advance(30)
    for _ in range(10):
        telemetry.http_request("GET", "/api/x", 200, 0.01)
    # Ten requests in half a minute is not two a minute over five.
    assert telemetry.snapshot()["http"]["perMinute"] == 10.0
    clock.advance(60 * 10)
    for _ in range(10):
        telemetry.http_request("GET", "/api/x", 200, 0.01)
    assert telemetry.snapshot()["http"]["perMinute"] == pytest.approx(10 / WINDOW_MINUTES)


def test_the_snapshot_is_json_and_stays_small_with_every_ring_full():
    telemetry, clock = store()
    telemetry.sources.sockets_connected = lambda: 17
    telemetry.sources.pool = lambda: PoolGauges(5, 1, 4, 0, 10)
    for _ in range(RING_MINUTES + 5):
        for _ in range(3):
            telemetry.http_request("GET", "/api/rooms/{room_id}", 200, 0.02)
            telemetry.socket_event("draw", "ok", 0.002)
            telemetry.db_query(0.001)
        telemetry.record_loop_lag(0.003)
        telemetry.rss_samples.add(clock.wall, 150_000_000.0)
        clock.advance(60)
    snapshot = telemetry.snapshot()
    body = json.dumps(snapshot)
    assert len(body) < 8_000, len(body)
    series = snapshot["series"]
    assert set(series) == {
        "httpPerMinute",
        "socketPerMinute",
        "httpP95Ms",
        "socketP95Ms",
        "loopLagMaxMs",
        "socketBytesInPerMinute",
        "socketBytesOutPerMinute",
        "rssBytes",
    }
    assert all(len(points) == RING_MINUTES for points in series.values())
    assert series["httpPerMinute"][-2] == 3
    assert snapshot["socket"]["connected"] == 17
    assert snapshot["database"]["pool"]["capacity"] == 10


def test_history_write_losses_are_counted_by_reason_and_over_the_last_hour():
    telemetry, clock = store()
    telemetry.history_write_abandoned("game", "timeout")
    clock.advance(60 * 90)
    telemetry.history_write_abandoned("prompt_usage", "error")
    losses = telemetry.snapshot()["database"]["historyWritesAbandoned"]
    assert losses == {
        "total": 2,
        "lastHour": 1,
        "byReason": {"timeout": 1, "error": 1},
    }
    assert (
        'sketchy_history_writes_abandoned_total{kind="game",reason="timeout"} 1'
        in telemetry.prometheus_lines()
    )


def test_exposition_declares_each_family_once_and_omits_what_it_cannot_measure():
    telemetry, _ = store()
    telemetry.http_request("GET", "/api/x", 200, 0.01)
    lines = telemetry.prometheus_lines()
    types = [line for line in lines if line.startswith("# TYPE")]
    assert len(types) == len(set(types))
    # No pool source, so no pool family - rather than a family of zeros that
    # a dashboard would read as an idle pool.
    assert not any(line.startswith("sketchy_db_pool_") for line in lines)
    assert any(line.startswith("sketchy_process_uptime_seconds ") for line in lines)


def test_the_process_sampler_reads_cpu_and_memory():
    telemetry, clock = store()
    telemetry.sample_process()
    busy = time.perf_counter()
    while time.perf_counter() - busy < 0.02:
        pass
    clock.advance(1.0)
    telemetry.sample_process()
    process = telemetry.snapshot()["process"]
    assert process["cpuPercent"] is not None and process["cpuPercent"] > 0
    assert isinstance(process["rssBytes"], int) and process["rssBytes"] > 0
    assert process["diskTotalBytes"] is None or process["diskTotalBytes"] > 0


@pytest.mark.asyncio
async def test_the_sampler_measures_a_blocked_loop():
    telemetry = Telemetry()
    health = LoopHealth("loop_lag")
    task = asyncio.create_task(
        run_lag_sampler(telemetry, interval_seconds=0.01, health=health)
    )
    try:
        await asyncio.sleep(0.03)
        time.sleep(0.08)  # noqa: ASYNC251 - blocking the loop is the point
        await asyncio.sleep(0.03)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert telemetry.loop_lag.count() >= 2
    assert health.consecutive_failures == 0
    assert health.last_success is not None
    assert max(
        value for value in telemetry.lag_samples.points_max(time.time()) if value is not None
    ) >= 0.05


# --- bytes over the socket -------------------------------------------------------


def test_payload_size_is_bytes_as_they_are_and_json_for_the_rest():
    from app.services.telemetry import payload_bytes

    assert payload_bytes(b"\x00" * 300) == 300
    assert payload_bytes("héllo") == 6
    assert payload_bytes({"text": "cat"}) == len(b'{"text":"cat"}')
    assert payload_bytes(None) == 0
    assert payload_bytes(b"ab", {"a": 1}) == 2 + len(b'{"a":1}')
    assert payload_bytes(object()) > 0


def test_socket_bytes_are_rated_per_minute_and_sized_per_event():
    telemetry, clock = store()
    # Half a minute in: the rate is over the one minute the process has lived.
    clock.advance(30)
    telemetry.note_socket_bytes_in(3000)
    telemetry.note_socket_bytes_out(9000)
    for size in (100, 100, 100, 5000):
        telemetry.socket_command_payload("draw", size)
    telemetry.socket_command_payload("guess", 30)
    telemetry.socket_emit_payload("room_state", 20_000)

    socket = telemetry.snapshot()["socket"]
    assert socket["bytesInPerMinute"] == 3000
    assert socket["bytesOutPerMinute"] == 9000
    assert socket["bytesInTotal"] == 3000 and socket["bytesOutTotal"] == 9000
    # Largest total first, with the distribution of each.
    assert [row["event"] for row in socket["commandSizes"]] == ["draw", "guess"]
    draw = socket["commandSizes"][0]
    assert draw["count"] == 4 and draw["bytesTotal"] == 5300
    assert draw["p50"] <= 256 and draw["p99"] >= 4096
    assert socket["emitSizes"][0]["event"] == "room_state"
    series = telemetry.snapshot()["series"]
    assert series["socketBytesInPerMinute"][-1] == 3000
    assert series["socketBytesOutPerMinute"][-1] == 9000

    lines = telemetry.prometheus_lines()
    assert "sketchy_socket_bytes_in_total 3000" in lines
    assert "sketchy_socket_bytes_out_total 9000" in lines
    assert 'sketchy_socket_command_bytes_bucket{event="draw",le="256.0"} 3' in lines
    assert 'sketchy_socket_emit_bytes_count{event="room_state"} 1' in lines


def test_the_size_table_is_bounded():
    from app.services.telemetry import TOP_SIZES

    telemetry, _ = store()
    for index in range(TOP_SIZES + 5):
        telemetry.socket_command_payload(f"cmd{index}", 10 + index)
    rows = telemetry.snapshot()["socket"]["commandSizes"]
    assert len(rows) == TOP_SIZES
    assert rows[0]["event"] == f"cmd{TOP_SIZES + 4}"
