"""Process signals: how this worker is coping, as opposed to what it has done.

`runtime_metrics` records domain observations - a join, a finished game, a
timer that fired late - and writes them down, because they are facts about
the service's history. None of them says whether the server is *keeping up*.
An operator paged at three in the morning needs to tell a traffic spike from
a database stall from a starved event loop from a leak, and before this module
every one of those looked the same: players complaining.

So this records the RED signals (rate, errors, duration) for every HTTP
request and every client command, the USE signals (utilisation, saturation,
errors) for the event loop, the process, and the connection pool, and the
depth of the two durable queues. Nothing here is persisted. It is process
memory that vanishes on restart, which is correct for the same reason the live
room count vanishes: a latency histogram is not a historical fact, and
Prometheus is the place to keep one.

Hand-rolled rather than `prometheus_client`, because the in-app operations
page is the first consumer and it needs "the last five minutes", which a
cumulative histogram cannot answer. Every family therefore keeps two things:
the cumulative counts a scraper expects, and a ring of per-minute buckets from
which a windowed percentile, a rate, and a sparkline can be read. One store,
two views, so the page and the scrape cannot disagree.

Cardinality is bounded by construction: routes are templates, not paths;
statuses are classes, not codes; command names come from the registration
table; and any labelled family that somehow grows past `MAX_SERIES` folds
further label values into `other` rather than growing without limit.
"""
from __future__ import annotations

import asyncio
import bisect
import contextlib
import logging
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.readiness import LoopHealth

try:  # pragma: no cover - the supported platforms all have it
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

# Bucket upper bounds in seconds; `+Inf` is implicit. Dense where the SLOs will
# sit: a REST call is expected in tens of milliseconds, a command handler and a
# query in single-digit milliseconds, and loop lag ideally under one.
HTTP_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
FAST_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)
DB_BUCKETS = (0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)

RING_MINUTES = 60
WINDOW_MINUTES = 5
MAX_SERIES = 256
OTHER_LABEL = "other"

# Probes are counted, so a scraper that stops scraping shows up, but they are
# not timed: a load balancer asking every second would otherwise dominate the
# latency distribution of a service whose real work is elsewhere.
PROBE_ROUTES = frozenset({"/api/health", "/api/ready", "/metrics"})
STATIC_ROUTE = "static"
UNROUTED_ROUTE = "unrouted"

HTTP_OUTCOME_ABORTED = "aborted"
SOCKET_OUTCOMES = ("ok", "refused", "error", "throttled")
CONNECTION_OUTCOMES = ("accepted", "refused", "full")

DEFAULT_SAMPLE_INTERVAL_SECONDS = 1.0
# Resident size and disk are read once a minute: they move slowly, and the
# ring they feed has one slot per minute anyway.
SLOW_SAMPLE_EVERY_TICKS = 60
CPU_SMOOTHING = 0.2

_ESCAPES = str.maketrans({"\\": "\\\\", '"': '\\"', "\n": "\\n"})


def _escape(value: str) -> str:
    return value.translate(_ESCAPES)


def _labels(names: Sequence[str], values: Sequence[str]) -> str:
    if not names:
        return ""
    inner = ",".join(
        f'{name}="{_escape(str(value))}"' for name, value in zip(names, values, strict=True)
    )
    return "{" + inner + "}"


def _format(value: float | int) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if value != value:  # NaN
        return "NaN"
    return repr(float(value))


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _ms(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds * 1000.0, 1)


# --- rings -------------------------------------------------------------------


class MinuteRing:
    """A fixed number of one-minute slots, keyed by wall-clock minute.

    Each slot remembers which minute it holds. A write into a slot whose
    minute has passed resets it first, so a quiet hour cannot resurrect what
    happened sixty minutes ago, and a read reports `None` for a minute that
    was never written rather than the stale payload the slot still holds.
    """

    def __init__(self, make: Callable[[], object], *, minutes: int = RING_MINUTES) -> None:
        if minutes < 1:
            raise ValueError("a ring needs at least one minute")
        self._make = make
        self._minutes = minutes
        self._stamps: list[int | None] = [None] * minutes
        self._slots: list[object] = [None] * minutes

    @property
    def minutes(self) -> int:
        return self._minutes

    def slot(self, now: float):
        """The payload for the minute containing `now`, created if absent."""
        stamp = int(now // 60)
        index = stamp % self._minutes
        if self._stamps[index] != stamp:
            self._stamps[index] = stamp
            self._slots[index] = self._make()
        return self._slots[index]

    def points(self, now: float, *, minutes: int | None = None) -> list:
        """Oldest first, one entry per minute, `None` where nothing was written."""
        count = self._minutes if minutes is None else min(minutes, self._minutes)
        current = int(now // 60)
        result = []
        for offset in range(count - 1, -1, -1):
            stamp = current - offset
            index = stamp % self._minutes
            result.append(self._slots[index] if self._stamps[index] == stamp else None)
        return result

    def window(self, now: float, minutes: int = WINDOW_MINUTES) -> list:
        """The written payloads of the trailing `minutes`, oldest first."""
        return [payload for payload in self.points(now, minutes=minutes) if payload is not None]


class CountRing:
    """Per-minute integer counters, several per slot (requests, errors, ...)."""

    def __init__(self, fields: int = 1, *, minutes: int = RING_MINUTES) -> None:
        self._fields = fields
        self._ring = MinuteRing(lambda: [0] * fields, minutes=minutes)

    def bump(self, now: float, *, field: int = 0, by: int = 1) -> None:
        self._ring.slot(now)[field] += by

    def window_total(self, now: float, *, field: int = 0, minutes: int = WINDOW_MINUTES) -> int:
        return sum(payload[field] for payload in self._ring.window(now, minutes))

    def points(self, now: float, *, field: int = 0) -> list[int | None]:
        return [None if payload is None else payload[field] for payload in self._ring.points(now)]


class SampleRing:
    """Per-minute `(count, sum, max)` of a sampled value, for gauges on a timer."""

    def __init__(self, *, minutes: int = RING_MINUTES) -> None:
        self._ring = MinuteRing(lambda: [0, 0.0, 0.0], minutes=minutes)

    def add(self, now: float, value: float) -> None:
        payload = self._ring.slot(now)
        payload[0] += 1
        payload[1] += value
        if payload[0] == 1 or value > payload[2]:
            payload[2] = value

    def points_max(self, now: float) -> list[float | None]:
        return [None if payload is None else payload[2] for payload in self._ring.points(now)]

    def points_mean(self, now: float) -> list[float | None]:
        return [
            None if payload is None or payload[0] == 0 else payload[1] / payload[0]
            for payload in self._ring.points(now)
        ]


# --- families ----------------------------------------------------------------


class LabelledCounter:
    """A monotonic counter per label tuple, bounded in how many tuples it keeps."""

    def __init__(self, name: str, help: str, label_names: Sequence[str] = ()) -> None:
        self.name = name
        self.help = help
        self.label_names = tuple(label_names)
        self._values: dict[tuple[str, ...], int] = {}
        self.overflowed = 0

    def _key(self, labels: Sequence[str]) -> tuple[str, ...]:
        key = tuple(str(label) for label in labels)
        if len(key) != len(self.label_names):
            raise ValueError(f"{self.name} takes {len(self.label_names)} labels, got {len(key)}")
        if key not in self._values and len(self._values) >= MAX_SERIES:
            self.overflowed += 1
            return (OTHER_LABEL,) * len(self.label_names)
        return key

    def inc(self, labels: Sequence[str] = (), by: int = 1) -> None:
        key = self._key(labels)
        self._values[key] = self._values.get(key, 0) + by

    def get(self, labels: Sequence[str] = ()) -> int:
        return self._values.get(tuple(str(label) for label in labels), 0)

    def total(self) -> int:
        return sum(self._values.values())

    def items(self) -> list[tuple[tuple[str, ...], int]]:
        return sorted(self._values.items())

    def lines(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        if not self.label_names:
            lines.append(f"{self.name} {self._values.get((), 0)}")
            return lines
        for key, value in self.items():
            lines.append(f"{self.name}{_labels(self.label_names, key)} {value}")
        return lines


@dataclass
class _HistogramSeries:
    counts: list[int]
    total: float = 0.0
    n: int = 0


def quantile(q: float, buckets: Sequence[float], vector: Sequence[int]) -> float | None:
    """Prometheus' `histogram_quantile`, over one non-cumulative bucket vector.

    Linear interpolation inside the bucket the rank falls in; the last bucket
    (`+Inf`) answers with its lower bound, since nothing more is known. `None`
    when there are no observations at all.
    """
    total = sum(vector)
    if total <= 0:
        return None
    rank = q * total
    cumulative = 0
    for index, count in enumerate(vector):
        previous = cumulative
        cumulative += count
        if cumulative < rank or count == 0:
            continue
        if index >= len(buckets):
            return float(buckets[-1])
        lower = 0.0 if index == 0 else float(buckets[index - 1])
        upper = float(buckets[index])
        return lower + (upper - lower) * ((rank - previous) / count)
    return float(buckets[-1])


class Histogram:
    """Cumulative buckets per label tuple, plus one per-minute ring for the family.

    The ring is not per label on purpose: the page wants "how slow are
    commands right now", not sixty minutes of history for each of thirty
    commands, and one ring is what keeps this whole module under a hundred
    kilobytes.
    """

    def __init__(
        self,
        name: str,
        help: str,
        buckets: Sequence[float],
        label_names: Sequence[str] = (),
        *,
        minutes: int = RING_MINUTES,
    ) -> None:
        if list(buckets) != sorted(buckets) or len(set(buckets)) != len(buckets):
            raise ValueError("buckets must be strictly increasing")
        self.name = name
        self.help = help
        self.buckets = tuple(float(bound) for bound in buckets)
        self.label_names = tuple(label_names)
        self._series: dict[tuple[str, ...], _HistogramSeries] = {}
        self._ring = MinuteRing(lambda: [0] * (len(self.buckets) + 1), minutes=minutes)
        self.overflowed = 0

    def _series_for(self, labels: Sequence[str]) -> _HistogramSeries:
        key = tuple(str(label) for label in labels)
        if len(key) != len(self.label_names):
            raise ValueError(f"{self.name} takes {len(self.label_names)} labels, got {len(key)}")
        series = self._series.get(key)
        if series is None:
            if len(self._series) >= MAX_SERIES:
                self.overflowed += 1
                key = (OTHER_LABEL,) * len(self.label_names)
                series = self._series.get(key)
            if series is None:
                series = _HistogramSeries(counts=[0] * (len(self.buckets) + 1))
                self._series[key] = series
        return series

    def observe(self, seconds: float, labels: Sequence[str] = (), *, now: float) -> None:
        if seconds < 0:
            seconds = 0.0
        index = bisect.bisect_left(self.buckets, seconds)
        series = self._series_for(labels)
        series.counts[index] += 1
        series.total += seconds
        series.n += 1
        self._ring.slot(now)[index] += 1

    def count(self) -> int:
        return sum(series.n for series in self._series.values())

    def window_vector(self, now: float, minutes: int = WINDOW_MINUTES) -> list[int]:
        vector = [0] * (len(self.buckets) + 1)
        for payload in self._ring.window(now, minutes):
            for index, count in enumerate(payload):
                vector[index] += count
        return vector

    def windowed(self, now: float, minutes: int = WINDOW_MINUTES) -> dict[str, float | int | None]:
        vector = self.window_vector(now, minutes)
        return {
            "count": sum(vector),
            "p50": quantile(0.5, self.buckets, vector),
            "p95": quantile(0.95, self.buckets, vector),
            "p99": quantile(0.99, self.buckets, vector),
        }

    def per_minute_quantile(self, now: float, q: float = 0.95) -> list[float | None]:
        return [
            None if payload is None else quantile(q, self.buckets, payload)
            for payload in self._ring.points(now)
        ]

    def lines(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        for key, series in sorted(self._series.items()):
            cumulative = 0
            for bound, count in zip(self.buckets, series.counts, strict=False):
                cumulative += count
                labels = _labels((*self.label_names, "le"), (*key, _format(bound)))
                lines.append(f"{self.name}_bucket{labels} {cumulative}")
            labels = _labels((*self.label_names, "le"), (*key, "+Inf"))
            lines.append(f"{self.name}_bucket{labels} {series.n}")
            lines.append(f"{self.name}_sum{_labels(self.label_names, key)} {_format(series.total)}")
            lines.append(f"{self.name}_count{_labels(self.label_names, key)} {series.n}")
        return lines


def gauge_lines(name: str, help: str, value: float | int | None) -> list[str]:
    if value is None:
        return []
    return [f"# HELP {name} {help}", f"# TYPE {name} gauge", f"{name} {_format(value)}"]


def labelled_gauge_lines(
    name: str, help: str, label_names: Sequence[str], rows: Iterable[tuple[Sequence[str], float | int]]
) -> list[str]:
    body = [f"{name}{_labels(label_names, key)} {_format(value)}" for key, value in rows]
    if not body:
        return []
    return [f"# HELP {name} {help}", f"# TYPE {name} gauge", *body]


# --- process -----------------------------------------------------------------


@dataclass
class PoolGauges:
    size: int
    checked_out: int
    checked_in: int
    overflow: int
    capacity: int

    def as_json(self) -> dict[str, int]:
        return {
            "size": self.size,
            "checkedOut": self.checked_out,
            "checkedIn": self.checked_in,
            "overflow": self.overflow,
            "capacity": self.capacity,
        }


@dataclass
class Sources:
    """Live numbers owned elsewhere, read at snapshot time rather than copied.

    The socket ledger and the pool already know their own counts exactly;
    a second counter kept here would be one more thing able to drift.
    """

    sockets_connected: Callable[[], int] | None = None
    pool: Callable[[], PoolGauges | None] | None = None


def _cpu_seconds() -> float | None:
    if resource is None:  # pragma: no cover
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


def _resident_bytes() -> tuple[int | None, bool]:
    """Current resident size where the platform will say, else the peak, flagged."""
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/self/statm", encoding="ascii") as statm:
                pages = int(statm.read().split()[1])
            return pages * os.sysconf("SC_PAGE_SIZE"), False
        except (OSError, ValueError, IndexError):  # pragma: no cover
            pass
    if resource is None:  # pragma: no cover
        return None, False
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports kilobytes, macOS bytes; only the fallback path reaches
    # here on Linux, so the unit is whatever the platform documents.
    return (peak * 1024 if sys.platform.startswith("linux") else peak), True


@dataclass
class ProcessState:
    started_wall: float
    started_mono: float
    data_path: str = field(default_factory=os.getcwd)
    cpu_percent: float | None = None
    rss_bytes: int | None = None
    rss_is_peak: bool = False
    disk_free: int | None = None
    disk_total: int | None = None
    ticks: int = 0
    _last_cpu: tuple[float, float] | None = None

    def sample(self, telemetry: Telemetry, *, now: float, mono: float) -> None:
        cpu = _cpu_seconds()
        if cpu is not None:
            if self._last_cpu is not None:
                wall_delta = mono - self._last_cpu[0]
                if wall_delta > 0:
                    instant = max(0.0, (cpu - self._last_cpu[1]) / wall_delta) * 100.0
                    self.cpu_percent = (
                        instant
                        if self.cpu_percent is None
                        else self.cpu_percent + CPU_SMOOTHING * (instant - self.cpu_percent)
                    )
            self._last_cpu = (mono, cpu)
        if self.ticks % SLOW_SAMPLE_EVERY_TICKS == 0:
            self.rss_bytes, self.rss_is_peak = _resident_bytes()
            if self.rss_bytes is not None:
                telemetry.rss_samples.add(now, float(self.rss_bytes))
            try:
                usage = shutil.disk_usage(self.data_path)
            except OSError:
                self.disk_free = self.disk_total = None
            else:
                self.disk_free, self.disk_total = usage.free, usage.total
        self.ticks += 1


# --- the store ---------------------------------------------------------------


class Telemetry:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        data_path: str | None = None,
    ) -> None:
        self._clock = clock
        self._monotonic = monotonic
        self.sources = Sources()
        self.process = ProcessState(
            started_wall=clock(),
            started_mono=monotonic(),
            data_path=data_path or os.getcwd(),
        )
        self.in_flight = 0

        self.http_requests = LabelledCounter(
            "sketchy_http_requests_total",
            "HTTP requests answered, by method, route template and status class.",
            ("method", "route", "status_class"),
        )
        self.http_duration = Histogram(
            "sketchy_http_request_duration_seconds",
            "Wall time of API requests, by route template; probes are not timed.",
            HTTP_BUCKETS,
            ("route",),
        )
        # requests, errors
        self.http_minutes = CountRing(2)

        self.socket_events = LabelledCounter(
            "sketchy_socket_events_total",
            "Client commands handled, by command and outcome.",
            ("event", "outcome"),
        )
        self.socket_duration = Histogram(
            "sketchy_socket_event_duration_seconds",
            "Wall time of a command handler, by command.",
            FAST_BUCKETS,
            ("event",),
        )
        # events, errors, refused, throttled
        self.socket_minutes = CountRing(4)
        self.socket_connections = LabelledCounter(
            "sketchy_socket_connections_total",
            "Socket handshakes, by outcome.",
            ("outcome",),
        )

        self.loop_lag = Histogram(
            "sketchy_event_loop_lag_seconds",
            "How late a one-second timer fired: time the event loop was not free.",
            FAST_BUCKETS,
        )
        self.loop_lag_last: float | None = None
        self.lag_samples = SampleRing()
        self.rss_samples = SampleRing()

        self.db_queries = LabelledCounter(
            "sketchy_db_queries_total", "Statements executed against the database."
        )
        self.db_query_errors = LabelledCounter(
            "sketchy_db_query_errors_total", "Statements the database refused or that failed."
        )
        self.db_duration = Histogram(
            "sketchy_db_query_duration_seconds",
            "Wall time of one statement, including any wait for a connection.",
            DB_BUCKETS,
        )
        # queries, errors
        self.db_minutes = CountRing(2)

        self.history_writes_abandoned = LabelledCounter(
            "sketchy_history_writes_abandoned_total",
            "Finished-game or prompt-usage writes given up on, by kind and reason.",
            ("kind", "reason"),
        )
        self.history_minutes = CountRing(1)

    # --- recording ---------------------------------------------------------

    def now(self) -> float:
        return self._clock()

    def http_request(self, method: str, route: str, status: int | str, seconds: float) -> None:
        now = self._clock()
        status_class = status if isinstance(status, str) else f"{int(status) // 100}xx"
        self.http_requests.inc((method, route, status_class))
        failed = status_class == "5xx"
        self.http_minutes.bump(now)
        if failed:
            self.http_minutes.bump(now, field=1)
        if route.startswith("/api/") and route not in PROBE_ROUTES:
            self.http_duration.observe(seconds, (route,), now=now)

    def socket_event(self, event: str, outcome: str, seconds: float | None) -> None:
        if outcome not in SOCKET_OUTCOMES:
            raise ValueError(f"unknown socket outcome {outcome!r}")
        now = self._clock()
        self.socket_events.inc((event, outcome))
        self.socket_minutes.bump(now)
        if outcome == "error":
            self.socket_minutes.bump(now, field=1)
        elif outcome == "refused":
            self.socket_minutes.bump(now, field=2)
        elif outcome == "throttled":
            self.socket_minutes.bump(now, field=3)
        if seconds is not None:
            self.socket_duration.observe(seconds, (event,), now=now)

    def socket_connection(self, outcome: str) -> None:
        if outcome not in CONNECTION_OUTCOMES:
            raise ValueError(f"unknown connection outcome {outcome!r}")
        self.socket_connections.inc((outcome,))

    def record_loop_lag(self, seconds: float) -> None:
        now = self._clock()
        seconds = max(0.0, seconds)
        self.loop_lag_last = seconds
        self.loop_lag.observe(seconds, now=now)
        self.lag_samples.add(now, seconds)

    def db_query(self, seconds: float, *, failed: bool = False) -> None:
        now = self._clock()
        self.db_queries.inc()
        self.db_minutes.bump(now)
        if failed:
            self.db_query_errors.inc()
            self.db_minutes.bump(now, field=1)
        self.db_duration.observe(seconds, now=now)

    def history_write_abandoned(self, kind: str, reason: str) -> None:
        self.history_writes_abandoned.inc((kind, reason))
        self.history_minutes.bump(self._clock())

    def sample_process(self) -> None:
        self.process.sample(self, now=self._clock(), mono=self._monotonic())

    # --- reading -----------------------------------------------------------

    def uptime_seconds(self) -> float:
        return max(0.0, self._monotonic() - self.process.started_mono)

    def _window_minutes(self, now: float) -> float:
        """Minutes the window actually covers: a young process is not a quiet one."""
        elapsed = max(0.0, now - self.process.started_wall) / 60.0
        return max(1.0, min(float(WINDOW_MINUTES), elapsed + 1.0 / 60.0))

    def _pool(self) -> PoolGauges | None:
        if self.sources.pool is None:
            return None
        try:
            return self.sources.pool()
        except Exception:  # pragma: no cover - a broken source must not break the page
            logger.exception("reading pool gauges failed")
            return None

    def _sockets(self) -> int | None:
        if self.sources.sockets_connected is None:
            return None
        return int(self.sources.sockets_connected())

    def snapshot(self, now: float | None = None) -> dict[str, object]:
        now = self._clock() if now is None else now
        minutes = self._window_minutes(now)

        http_count = self.http_minutes.window_total(now)
        http_errors = self.http_minutes.window_total(now, field=1)
        http_latency = self.http_duration.windowed(now)

        socket_count = self.socket_minutes.window_total(now)
        socket_errors = self.socket_minutes.window_total(now, field=1)
        socket_refused = self.socket_minutes.window_total(now, field=2)
        socket_throttled = self.socket_minutes.window_total(now, field=3)
        socket_latency = self.socket_duration.windowed(now)

        db_count = self.db_minutes.window_total(now)
        db_latency = self.db_duration.windowed(now)
        lag = self.loop_lag.windowed(now)
        pool = self._pool()
        process = self.process

        def rate(part: int, whole: int) -> float:
            return 0.0 if whole == 0 else round(part / whole, 4)

        return {
            "windowMinutes": WINDOW_MINUTES,
            "http": {
                "perMinute": round(http_count / minutes, 1),
                "errorRate": rate(http_errors, http_count),
                "p50Ms": _ms(http_latency["p50"]),
                "p95Ms": _ms(http_latency["p95"]),
                "p99Ms": _ms(http_latency["p99"]),
                "inFlight": self.in_flight,
                "total": self.http_requests.total(),
            },
            "socket": {
                "perMinute": round(socket_count / minutes, 1),
                "errorRate": rate(socket_errors, socket_count),
                "refusedRate": rate(socket_refused, socket_count),
                "throttledPerMinute": round(socket_throttled / minutes, 1),
                "p95Ms": _ms(socket_latency["p95"]),
                "connected": self._sockets(),
                "total": self.socket_events.total(),
            },
            "process": {
                "loopLagMs": _ms(self.loop_lag_last),
                "loopLagP95Ms": _ms(lag["p95"]),
                "cpuPercent": _round(process.cpu_percent, 1),
                "rssBytes": process.rss_bytes,
                "rssIsPeak": process.rss_is_peak,
                "uptimeSeconds": round(self.uptime_seconds(), 1),
                "startedAt": datetime.fromtimestamp(process.started_wall, timezone.utc).isoformat(),
                "diskFreeBytes": process.disk_free,
                "diskTotalBytes": process.disk_total,
                "diskPath": process.data_path,
            },
            "database": {
                "pool": None if pool is None else pool.as_json(),
                "queriesPerMinute": round(db_count / minutes, 1),
                "queryP95Ms": _ms(db_latency["p95"]),
                "queryErrors": self.db_query_errors.total(),
                "historyWritesAbandoned": {
                    "total": self.history_writes_abandoned.total(),
                    "lastHour": self.history_minutes.window_total(now, minutes=RING_MINUTES),
                    "byReason": {
                        reason: sum(
                            count
                            for (_, why), count in self.history_writes_abandoned.items()
                            if why == reason
                        )
                        for reason in ("timeout", "error")
                    },
                },
            },
            "series": {
                "httpPerMinute": self.http_minutes.points(now),
                "socketPerMinute": self.socket_minutes.points(now),
                "httpP95Ms": [_ms(value) for value in self.http_duration.per_minute_quantile(now)],
                "socketP95Ms": [
                    _ms(value) for value in self.socket_duration.per_minute_quantile(now)
                ],
                "loopLagMaxMs": [_ms(value) for value in self.lag_samples.points_max(now)],
                "rssBytes": [
                    None if value is None else int(value)
                    for value in self.rss_samples.points_max(now)
                ],
            },
        }

    def prometheus_lines(self) -> list[str]:
        process = self.process
        pool = self._pool()
        lines: list[str] = []
        lines += self.http_requests.lines()
        lines += self.http_duration.lines()
        lines += gauge_lines(
            "sketchy_http_requests_in_flight", "HTTP requests being answered right now.", self.in_flight
        )
        lines += self.socket_events.lines()
        lines += self.socket_duration.lines()
        lines += self.socket_connections.lines()
        lines += gauge_lines(
            "sketchy_sockets_connected", "Sockets currently open on this worker.", self._sockets()
        )
        lines += self.loop_lag.lines()
        lines += gauge_lines(
            "sketchy_event_loop_lag_last_seconds",
            "Lag measured by the most recent sample.",
            self.loop_lag_last,
        )
        lines += self.db_queries.lines()
        lines += self.db_query_errors.lines()
        lines += self.db_duration.lines()
        if pool is not None:
            lines += gauge_lines("sketchy_db_pool_size", "Connections the pool keeps open.", pool.size)
            lines += gauge_lines(
                "sketchy_db_pool_checked_out", "Connections currently in use.", pool.checked_out
            )
            lines += gauge_lines(
                "sketchy_db_pool_checked_in", "Connections idle in the pool.", pool.checked_in
            )
            lines += gauge_lines(
                "sketchy_db_pool_overflow", "Connections open beyond the pool size.", pool.overflow
            )
            lines += gauge_lines(
                "sketchy_db_pool_capacity", "Most connections the pool will ever open.", pool.capacity
            )
        lines += self.history_writes_abandoned.lines()
        cpu = _cpu_seconds()
        if cpu is not None:
            lines += [
                "# HELP sketchy_process_cpu_seconds_total CPU time this process has used.",
                "# TYPE sketchy_process_cpu_seconds_total counter",
                f"sketchy_process_cpu_seconds_total {_format(cpu)}",
            ]
        lines += gauge_lines(
            "sketchy_process_resident_memory_bytes",
            "Resident set size (the peak, where the platform reports only that).",
            process.rss_bytes,
        )
        lines += gauge_lines(
            "sketchy_process_start_time_seconds",
            "Unix time the process started.",
            process.started_wall,
        )
        lines += gauge_lines(
            "sketchy_process_uptime_seconds", "Seconds since the process started.", self.uptime_seconds()
        )
        lines += gauge_lines(
            "sketchy_data_disk_free_bytes", "Free space on the data volume.", process.disk_free
        )
        lines += gauge_lines(
            "sketchy_data_disk_total_bytes", "Size of the data volume.", process.disk_total
        )
        return lines


# One store per process, like `runtime_metrics.metrics`: one worker owns every
# request and command, so there is nothing to aggregate across.
telemetry = Telemetry()


# --- the sampler -------------------------------------------------------------


async def run_lag_sampler(
    store: Telemetry = telemetry,
    *,
    interval_seconds: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
    health: LoopHealth | None = None,
) -> None:
    """Measure how late a timer fires, for ever.

    The loop asks to be woken in `interval_seconds` and notes how much later
    than that it actually was. Everything that blocked the loop meanwhile - a
    synchronous write, a large JSON dump, a garbage-collection pause - shows
    up as that lateness, which is what makes it the one number that separates
    "the server is busy" from "the server is stuck".
    """
    while True:
        due = store._monotonic() + interval_seconds
        await asyncio.sleep(interval_seconds)
        try:
            store.record_loop_lag(store._monotonic() - due)
            store.sample_process()
            if health is not None:
                health.record_success()
        except asyncio.CancelledError:
            raise
        except Exception:
            if health is not None:
                health.record_failure()
            logger.exception("telemetry sample failed")


def start_lag_sampler(
    store: Telemetry = telemetry,
    *,
    interval_seconds: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
    health: LoopHealth | None = None,
) -> asyncio.Task[None]:
    # The first sample is taken now, so the page does not show an empty
    # process card for the first minute of a fresh process.
    store.sample_process()
    return asyncio.create_task(
        run_lag_sampler(store, interval_seconds=interval_seconds, health=health),
        name="telemetry-sampler",
    )


async def stop_lag_sampler(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
