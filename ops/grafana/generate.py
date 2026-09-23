#!/usr/bin/env python3
"""Sketchy's Grafana dashboards, as code (#968).

The dashboards are this file; `dashboards/*.json` is its output, committed so
Grafana can provision it and a reviewer can see what changed. Editing a
dashboard in Grafana's UI does not survive: they are provisioned read-only,
and the change belongs here. Export-and-commit was the alternative, and every
export churns ids, versions and layout, so a one-line change reviews as a
hundred - the reason the mockup artboards are generated too.

Two things are checked in CI (`backend/tests/test_grafana_dashboards.py`):
that the committed JSON is what this file writes, and that every query names
only series something actually exposes - the reason the alert rules live in
the repository (R-OBS-13) applies to a panel just the same: a metric renamed
under it shows an empty graph, and nobody notices until the day it matters.

Panels read the recording rules wherever an alert already defines the number,
so a graph and the alert beside it cannot disagree about what "p95" means, and
a rate is over the same **5 minutes** they are (`docs/slo.md`, *How to read the
numbers*) - not Grafana's `$__rate_interval`, which at a 15 s scrape is a
minute and left the sparse histograms, a phase timer's lateness above all, in
gaps. A window has to fit inside Grafana's step, which is the range over about
800 points: at 7 d that is 10-15 minutes, and a 5 m window inside it draws a
third of the range and never looks at the rest. So a board that opens on a week
rates over an hour (`SLOW_RATE`), and a board of 5 m rates opens on a day. Per
panel, Grafana's relative time would express this better than per board, and it
is an override rather than a floor: the panel would then ignore the operator
zooming in on the minute an alert fired for. Counts of events are a rolling hour at every step, never "per step":
a step-sized bucket had no points at all on a range shorter than its step,
so every count read "No data" exactly when zoomed in on an incident.

    python3 ops/grafana/generate.py           # write dashboards/*.json
    python3 ops/grafana/generate.py --check   # exit 1 if they are stale
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

OUT = Path(__file__).resolve().parent / "dashboards"
DATASOURCE = {"type": "prometheus", "uid": "${datasource}"}
# The window of every rate, as the recording rules and the alerts use it.
RATE = "5m"
# What a dashboard whose default range is days uses instead: Grafana's step at
# 7 d is 10-15 minutes, and a 5 m window inside a 15 m step samples a third of
# the range - a burst between two steps is simply not drawn (#968).
SLOW_RATE = "1h"
# What the helpers write in place of a window, since a query is built before it
# knows which dashboard holds it; `render` puts that dashboard's window in.
WINDOW = "<window>"
# The databases `ops/prometheus/rules/sketchy-postgres.yml` leaves out, so a
# panel and the alert beside it are counting the same rows.
PG_OWN = 'datname!~"postgres|template0|template1"'
GRID_WIDTH = 24


@dataclass(frozen=True)
class Query:
    expr: str
    legend: str = ""


@dataclass(frozen=True)
class Panel:
    title: str
    queries: tuple[Query, ...]
    description: str = ""
    unit: str = "short"
    kind: str = "timeseries"
    width: int = 12
    height: int = 8
    stack: bool = False
    decimals: int | None = None


@dataclass(frozen=True)
class Row:
    title: str
    panels: tuple[Panel, ...]


@dataclass(frozen=True)
class Dashboard:
    uid: str
    title: str
    description: str
    rows: tuple[Row, ...]
    time_from: str = "now-6h"
    rate: str = RATE
    tags: tuple[str, ...] = field(default=("sketchy",))


# ------------------------------------------------------------------ helpers


def stat(title: str, expr: str, *, unit: str = "short", description: str = "", decimals: int | None = None) -> Panel:
    return Panel(title, (Query(expr),), description, unit, kind="stat", width=6, height=4, decimals=decimals)


def graph(title: str, *queries: Query, **options) -> Panel:
    return Panel(title, tuple(queries), **options)


def quantiles(metric: str, *, by: str = "", qs=(0.5, 0.95, 0.99)) -> tuple[Query, ...]:
    """p50/p95/p99 of a histogram, optionally one line per `by` label."""
    grouping = f"le, {by}" if by else "le"
    suffix = " {{" + by + "}}" if by else ""
    return tuple(
        Query(
            f"histogram_quantile({q}, sum by ({grouping}) (rate({metric}_bucket[{WINDOW}])))",
            f"p{round(q * 100)}{suffix}",
        )
        for q in qs
    )


def per_hour(event: str, legend: str) -> Query:
    """How many of one runtime observation in the hour up to each point (#965):
    the trend the in-app daily chart used to draw, now read from the counter."""
    return Query(f'sum(increase(sketchy_events_total{{event="{event}"}}[1h]))', legend)


def hourly_by(metric: str, labels: str) -> Query:
    """A counter's rolling hour, one line per label combination."""
    legend = " ".join("{{" + label.strip() + "}}" for label in labels.split(","))
    return Query(f"sum by ({labels}) (increase({metric}[1h]))", legend)


def ratio_or_zero(recorded: str, traffic: str) -> Query:
    """A recorded error ratio that reads 0, not "No data", when there is
    traffic and nothing failed. The rule is empty until an error series first
    exists - fine for an alert, misleading on a graph - and multiplying the
    traffic by zero keeps a server that is down from reading as healthy."""
    return Query(f"{recorded} or (sum(rate({traffic}[{WINDOW}])) * 0)")


def mean(metric: str, *, by: str = "") -> Query:
    """The average observation, from a histogram's own sum and count.

    `histogram_quantile` interpolates inside a bucket, and these histograms
    count small integers whose first bucket is `le="1"`: a table that writes
    exactly one row per game has every observation in that bucket, and the
    median comes back as 0.5 rows - half of an answer that is never anything
    but 1. The mean of the same observations is exact for them."""
    grouping = f"sum by ({by})" if by else "sum"
    legend = "{{" + by + "}}" if by else "mean"
    return Query(
        f"{grouping} (rate({metric}_sum[{WINDOW}])) / {grouping} (rate({metric}_count[{WINDOW}]))",
        legend,
    )


def by_label(metric: str, label: str) -> Query:
    return Query(f"sum by ({label}) (rate({metric}[{WINDOW}]))", "{{" + label + "}}")


# --------------------------------------------------------------- dashboards

OVERVIEW = Dashboard(
    uid="sketchy-overview",
    title="Sketchy · Overview",
    description="Is the game being played, and is the one worker keeping up with it.",
    # A day. Its rates are over 5 minutes, and Grafana's step at a week is
    # 10-15 minutes, so a week-wide default would step over the spikes this
    # board exists for. Zooming out to a week is a deliberate act, and the
    # counts stay true when it happens: their window is a rolling hour, wider
    # than the step at any range.
    time_from="now-24h",
    rows=(
        Row("Now", (
            stat("Players online", "sketchy_players_live", description="Seats taken in a room right now."),
            stat("Rooms", "sketchy_rooms_live"),
            stat("Games running", "sketchy_active_games_live"),
            stat("Sockets", "sketchy_sockets_connected", description="Open connections, lobby and waiting rooms included."),
        )),
        Row("Trend", (
            graph(
                "Rooms opened, per hour",
                per_hour("room.created", "rooms opened"),
                description="In the hour up to each point. The Operations page's daily chart, before #965 moved the trend here.",
            ),
            graph(
                "Games ended, per hour",
                per_hour("game.finished", "finished"),
                per_hour("game.abandoned", "abandoned"),
                stack=True,
            ),
            graph(
                "Abandoned share",
                Query(
                    'sum(increase(sketchy_events_total{event="game.abandoned"}[1h]))'
                    ' / clamp_min(sum(increase(sketchy_events_total{event=~"game.finished|game.abandoned"}[1h])), 1)',
                    "abandoned",
                ),
                description="Of the games that ended in the hour, the share that stopped without finishing. Worth more than the count: ten of twelve is a problem, ten of a thousand is a Tuesday.",
                unit="percentunit",
            ),
            graph(
                "Disconnects, per hour",
                per_hour("player.disconnected", "disconnects"),
                per_hour("player.reconnected", "reconnects"),
            ),
        )),
        Row("Keeping up", (
            graph(
                "Phase timer lateness",
                *quantiles("sketchy_phase_timer_lateness_seconds"),
                description="How late a turn's timer fired (#965). The first thing that degrades under load on one worker; `timer.overran` rows record only the ones past 250 ms.",
                unit="s",
            ),
            graph(
                "Event loop lag p95",
                Query("sketchy:loop_lag_p95_seconds:5m", "p95"),
                description="The recording rule SketchyLoopLag alerts on.",
                unit="s",
            ),
            graph(
                "Latency p95",
                Query("sketchy:http_p95_seconds:5m", "HTTP"),
                Query("sketchy:socket_p95_seconds:5m", "commands"),
                unit="s",
            ),
            graph(
                "Error ratio",
                Query(ratio_or_zero("sketchy:http_error_ratio:5m", "sketchy_http_requests_total").expr, "HTTP 5xx"),
                Query(ratio_or_zero("sketchy:socket_error_ratio:5m", "sketchy_socket_events_total").expr, "commands"),
                unit="percentunit",
            ),
            graph("Memory", Query("sketchy_process_resident_memory_bytes", "resident"), unit="bytes"),
            graph("CPU", Query(f"rate(sketchy_process_cpu_seconds_total[{WINDOW}])", "cores"), unit="short", decimals=2),
        )),
    ),
)

CONNECTIONS = Dashboard(
    uid="sketchy-connections",
    title="Sketchy · Connections",
    description="How connections live and die (#881), what only the client can see (#876), and the protocol's open questions (#882).",
    rows=(
        Row("Sockets", (
            graph("Open sockets by transport", Query("sum by (transport) (sketchy_sockets_by_transport)", "{{transport}}"), stack=True),
            graph(
                "Handshakes and upgrades",
                by_label("sketchy_socket_handshake_transport_total", "transport"),
                Query(f"sum(rate(sketchy_socket_upgrades_total[{WINDOW}]))", "upgraded to websocket"),
                description="Per second. A polling share that stays high is a proxy dropping upgrades (SketchyPollingShareHigh).",
                unit="reqps",
            ),
            graph(
                "Disconnects by reason",
                by_label("sketchy_socket_disconnects_total", "reason"),
                unit="reqps", stack=True,
            ),
            graph("Session length", *quantiles("sketchy_socket_session_seconds", qs=(0.5, 0.95)), unit="s"),
            graph(
                "Seat rebind wait",
                *quantiles("sketchy_seat_rebind_seconds", qs=(0.5, 0.95)),
                description="How long a seat stood empty inside its 30 s reconnect grace before its account came back.",
                unit="s",
            ),
            graph("Ping round trip", *quantiles("sketchy_socket_ping_rtt_seconds"), unit="s"),
        )),
        Row("What the client saw (#876)", (
            graph(
                "Client-reported events, per hour",
                hourly_by("sketchy_client_health_events_total", "event"),
                description="Sent only when something happened, so a quiet graph is a healthy one (R-OBS-20).",
                stack=True,
            ),
            graph(
                "Join to drawing",
                *quantiles("sketchy_client_join_to_drawing_seconds", qs=(0.5, 0.95)),
                description="A player entering mid-turn, waiting for the drawing to appear.",
                unit="s",
            ),
            graph(
                "Reports by transport, per hour",
                hourly_by("sketchy_client_health_reports_total", "transport"),
                stack=True,
            ),
        )),
        Row("Protocol (#882)", (
            graph(
                "Refusals by code",
                by_label("sketchy_socket_refusals_total", "code"),
                description="What the command budgets are sized against; too_fast is a throttle.",
                unit="reqps", stack=True,
            ),
            graph(
                "Canvas tail claims, per hour",
                hourly_by("sketchy_canvas_tail_claims_total", "result"),
                description="Whether a reconnect's prefix claim was answered with a tail. open_path is a claim made mid-stroke, by design; hash is client and server disagreeing about the history they share (#963).",
                stack=True,
            ),
            graph("Canvas recovery notices", by_label("sketchy_canvas_recovery_notices_total", "reason"), unit="reqps", stack=True),
            graph(
                "Bytes out",
                Query(f"sum(rate(sketchy_socket_bytes_out_total[{WINDOW}]))", "packets, before compression"),
                Query(f"sum(rate(sketchy_ws_wire_bytes_out_total[{WINDOW}]))", "WebSocket wire, after compression"),
                unit="Bps",
            ),
        )),
    ),
)

DATABASE = Dashboard(
    uid="sketchy-database",
    title="Sketchy · Database",
    description="The pool, the statements, the finished-game handoff, retention and integrity, and PostgreSQL's own view.",
    rows=(
        Row("Pool", (
            graph("Pool in use", Query("sketchy:db_pool_fill_ratio", "in use"), unit="percentunit"),
            graph("Pool wait p95", Query("sketchy:db_pool_wait_p95_seconds:5m", "p95"), unit="s"),
            graph("Pool timeouts", Query(f"sum(rate(sketchy_db_pool_timeouts_total[{WINDOW}]))", "timeouts"), unit="reqps"),
        )),
        Row("Statements", (
            graph(
                "Statement p95 by operation",
                Query(
                    f"histogram_quantile(0.95, sum by (le, operation) (rate(sketchy_db_query_duration_seconds_bucket[{WINDOW}])))",
                    "{{operation}}",
                ),
                unit="s",
            ),
            graph("Statements", Query(f"sum(rate(sketchy_db_queries_total[{WINDOW}]))", "statements"), unit="reqps"),
            graph("Errors by cause", by_label("sketchy_db_query_errors_total", "cause"), unit="reqps", stack=True),
        )),
        Row("Finished games", (
            graph("History write", *quantiles("sketchy_history_write_seconds", qs=(0.5, 0.95)), unit="s"),
            graph(
                "Staged and waiting",
                Query("sketchy_finished_games_pending", "pending"),
                Query("sketchy_finished_games_failed", "given up"),
            ),
            graph(
                "Writes given up on, per hour",
                hourly_by("sketchy_history_writes_abandoned_total", "kind, reason"),
                description="Each is a finished game whose history the server gave up writing (R-OBS-10).",
            ),
        )),
        Row("Retention and integrity", (
            graph(
                "Retention overdue",
                Query("max by (table) (sketchy_retention_overdue_seconds)", "{{table}}"),
                description="Age of the oldest row each sweep should already have removed, against its SLA (SketchyRetentionBehind).",
                unit="s",
            ),
            graph("Retention backlog", Query("max by (table) (sketchy_retention_backlog_rows)", "{{table}}")),
            graph(
                "Integrity mismatches, per hour",
                hourly_by("sketchy_integrity_mismatches_total", "check"),
            ),
        )),
        Row("PostgreSQL", (
            graph(
                "Connections",
                Query("sketchy:pg_connection_ratio", "in use"),
                description="Open connections over max_connections, as SketchyPostgresConnectionsHigh reads it.",
                unit="percentunit",
            ),
            graph(
                "Cache hit ratio",
                Query("sketchy:pg_cache_hit_ratio:1h", "{{datname}}"),
                description="The rule SketchyPostgresCacheMisses reads, per database - computing it here instead would count the template databases and disagree with the page.",
                unit="percentunit",
            ),
            graph(
                "Dead tuples, top 10",
                Query("topk(10, pg_stat_user_tables_n_dead_tup)", "{{relname}}"),
                description="Every table, unlike SketchyPostgresDeadTuples, which watches the six the sweeps write: the point here is to see a table nobody thought to name.",
            ),
            graph(
                "Database size",
                Query(f'sum by (datname) (pg_database_size_bytes{{{PG_OWN}}})', "{{datname}}"),
                description="Ours only: the maintenance and template databases are not what storage_report or the growth rule measure.",
                unit="bytes",
            ),
            graph("Data volume free", Query("sketchy:disk_free_ratio", "free"), unit="percentunit"),
        )),
    ),
)

STORAGE = Dashboard(
    uid="sketchy-storage",
    title="Sketchy · Storage",
    description="What a finished game and a drawing really cost (#895): the numbers every storage decision turns on.",
    time_from="now-7d",
    # Sizes are observed once per finished game or stored drawing, and a week
    # steps in tens of minutes: an hour's window is what keeps them on screen.
    rate=SLOW_RATE,
    rows=(
        Row("Drawings", (
            graph("Drawing store", Query("sketchy_drawing_store_bytes", "bytes"), unit="bytes"),
            graph(
                "Stored drawing size",
                *quantiles("sketchy_drawing_stored_bytes", by="format", qs=(0.5, 0.95)),
                description="As written, by format: SKCD encoded, SKCH verbatim.",
                unit="bytes",
            ),
            graph(
                "Encoding ratio",
                Query(
                    f"sum(rate(sketchy_drawing_stored_bytes_sum[{WINDOW}]))"
                    f" / sum(rate(sketchy_drawing_raw_bytes_sum[{WINDOW}]))",
                    "stored / wire",
                ),
                description="Stored bytes over the wire frame's, whether a second encoding (#899) would earn a permanent decoder. Undivided rather than clamped: a window with no drawing in it is a gap, not perfect compression.",
                unit="percentunit",
            ),
            graph(
                "Actions per drawing",
                mean("sketchy_drawing_actions"),
                description="The mean only: a quantile of these buckets interpolates from the bound below, so a drawing of exactly one action reads as a p95 of 0.95.",
            ),
        )),
        Row("A finished game", (
            graph(
                "Rows per game by table",
                mean("sketchy_history_rows_per_game", by="table"),
                description="Rows one finished game wrote, per table, averaged over the window: the tables that write one row a game read exactly 1, which a bucketed median cannot say.",
            ),
            graph("Handoff envelope", *quantiles("sketchy_handoff_envelope_bytes", qs=(0.5, 0.95)), unit="bytes"),
        )),
        Row("Messages and exports", (
            graph(
                "Lines retained, per hour",
                hourly_by("sketchy_messages_retained_total", "kind, audience"),
                stack=True,
            ),
            graph(
                "Recipients per line",
                mean("sketchy_message_recipients", by="audience"),
                description="How many sockets one retained line went to, by audience, averaged over the window.",
            ),
            graph("Export artifact", *quantiles("sketchy_export_artifact_bytes", qs=(0.5, 0.95)), unit="bytes"),
        )),
    ),
)

DASHBOARDS = (OVERVIEW, CONNECTIONS, DATABASE, STORAGE)


# -------------------------------------------------------------------- render


def _widths(row: Row) -> list[int]:
    """Half the grid each, except that an odd row of graphs goes three to a
    line, so no graph is left alone beside an empty half: five are three
    and two."""
    widths = [panel.width for panel in row.panels]
    if len(row.panels) >= 3 and len(row.panels) % 2 == 1 and all(panel.kind == "timeseries" and panel.width == 12 for panel in row.panels):
        widths = [8] * 3 + [12] * (len(widths) - 3)
    return widths


def _field_config(panel: Panel) -> dict:
    defaults: dict = {"unit": panel.unit}
    if panel.unit == "percentunit":
        # From nothing to all of it: a ratio that is 0 throughout would
        # otherwise auto-scale to an axis of thousands of percent.
        defaults["min"] = 0
    if panel.decimals is not None:
        defaults["decimals"] = panel.decimals
    if panel.kind == "timeseries":
        defaults["custom"] = {
            "drawStyle": "line",
            "fillOpacity": 10,
            "lineWidth": 1,
            "showPoints": "never",
            "spanNulls": False,
            "stacking": {"mode": "normal" if panel.stack else "none", "group": "A"},
        }
        if panel.unit == "percentunit":
            defaults["custom"]["axisSoftMax"] = 1
    return {"defaults": defaults, "overrides": []}


def _options(panel: Panel) -> dict:
    if panel.kind == "stat":
        return {
            "colorMode": "none",
            "graphMode": "area",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "value",
        }
    return {
        "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
        "tooltip": {"mode": "multi", "sort": "desc"},
    }


def render(dashboard: Dashboard) -> dict:
    """The dashboard as Grafana's JSON model, laid out left to right, top to
    bottom, with ids assigned in order - so the output is a function of the
    source and nothing else."""
    panels: list[dict] = []
    next_id = 1
    y = 0
    for row in dashboard.rows:
        panels.append({
            "collapsed": False,
            "gridPos": {"h": 1, "w": GRID_WIDTH, "x": 0, "y": y},
            "id": next_id,
            "panels": [],
            "title": row.title,
            "type": "row",
        })
        next_id += 1
        y += 1
        x = 0
        line_height = 0
        for panel, width in zip(row.panels, _widths(row), strict=True):
            if x + width > GRID_WIDTH:
                x = 0
                y += line_height
                line_height = 0
            entry = {
                "datasource": DATASOURCE,
                "description": panel.description,
                "fieldConfig": _field_config(panel),
                "gridPos": {"h": panel.height, "w": width, "x": x, "y": y},
                "id": next_id,
                "options": _options(panel),
                "targets": [
                    {
                        "datasource": DATASOURCE,
                        "expr": query.expr.replace(WINDOW, dashboard.rate),
                        "legendFormat": query.legend,
                        "range": True,
                        "refId": chr(ord("A") + index),
                    }
                    for index, query in enumerate(panel.queries)
                ],
                "title": panel.title,
                "type": panel.kind,
            }
            panels.append(entry)
            next_id += 1
            x += width
            line_height = max(line_height, panel.height)
        y += line_height
    return {
        "annotations": {"list": []},
        "description": dashboard.description,
        "editable": False,
        "graphTooltip": 1,
        "links": [
            {"asDropdown": True, "includeVars": True, "keepTime": True, "tags": ["sketchy"],
             "title": "Sketchy", "type": "dashboards"},
        ],
        "panels": panels,
        "refresh": "1m",
        "schemaVersion": 41,
        "tags": list(dashboard.tags),
        "templating": {
            "list": [
                {
                    "current": {"text": "Prometheus", "value": "prometheus"},
                    "hide": 0,
                    "label": "Data source",
                    "name": "datasource",
                    "query": "prometheus",
                    "refresh": 1,
                    "type": "datasource",
                },
            ],
        },
        "time": {"from": dashboard.time_from, "to": "now"},
        "timezone": "browser",
        "title": dashboard.title,
        "uid": dashboard.uid,
        "version": 1,
    }


def outputs() -> dict[Path, str]:
    """One file per dashboard, named for its uid. Two dashboards sharing a uid
    would write one file and lose the other silently, and Grafana would
    provision whichever it read last, so it stops here instead."""
    written = {
        OUT / f"{dashboard.uid.removeprefix('sketchy-')}.json": json.dumps(render(dashboard), indent=2) + "\n"
        for dashboard in DASHBOARDS
    }
    if len(written) != len(DASHBOARDS):
        raise ValueError(f"two dashboards share a uid: {sorted(d.uid for d in DASHBOARDS)}")
    return written


def expressions() -> list[tuple[str, str, str]]:
    """(dashboard, panel, expr) for every query, for the series check."""
    return [
        (dashboard.uid, panel.title, query.expr.replace(WINDOW, dashboard.rate))
        for dashboard in DASHBOARDS
        for row in dashboard.rows
        for panel in row.panels
        for query in panel.queries
    ]


def stale() -> list[Path]:
    """Committed dashboards that differ from what this file writes, or are
    missing, or have no source here any more."""
    expected = outputs()
    wrong = [path for path, text in expected.items() if not path.exists() or path.read_text() != text]
    orphaned = [path for path in OUT.glob("*.json") if path not in expected]
    return wrong + orphaned


def main(argv: list[str]) -> int:
    if argv not in ([], ["--check"]):
        print(__doc__.rstrip().rsplit("\n\n", 1)[-1], file=sys.stderr)
        return 2
    if argv == ["--check"]:
        problems = stale()
        for path in problems:
            print(f"stale: {path.relative_to(OUT.parent.parent.parent)}", file=sys.stderr)
        if problems:
            print("run: python3 ops/grafana/generate.py", file=sys.stderr)
        return 1 if problems else 0
    OUT.mkdir(parents=True, exist_ok=True)
    written = outputs()
    for path in OUT.glob("*.json"):
        if path not in written:
            path.unlink()
    for path, text in written.items():
        path.write_text(text)
    print(f"wrote {len(written)} dashboards to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
