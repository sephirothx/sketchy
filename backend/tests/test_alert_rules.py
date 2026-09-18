"""The alert rules name only series the server actually exposes.

A rule that watches `sketchy_loop_lag_seconds` after the metric was renamed
to `sketchy_event_loop_lag_seconds` never fires, and nobody finds out until
the night it should have. So every metric name in every expression is
checked here against the exposition the server would produce, and against
the recording rules and the probe's textfile, which are the only other
sources a rule may draw on.
"""
from __future__ import annotations

from pathlib import Path
import re

import pytest
import yaml

from app.api.operations import (
    _drawing_store_lines,
    _loop_lines,
    _prometheus_lines,
    _queue_lines,
    _retention_lines,
)
from app.services.drawing_storage import DrawingStoreSize
from app.probe import PROBE_METRIC_NAMES
from app.services.queue_depths import HandoffDepth, QueueDepth, QueueSnapshot
from app.services.telemetry import PoolGauges, Telemetry, gauge_lines


RULES = Path(__file__).resolve().parents[2] / "ops" / "prometheus" / "rules"
RECORDING = RULES / "sketchy-recording.yml"
ALERTS = RULES / "sketchy-alerts.yml"
POSTGRES = RULES / "sketchy-postgres.yml"
SCRAPE = RULES.parent / "scrape-example.yml"
RULE_FILES = (RECORDING, ALERTS, POSTGRES)

METRIC = re.compile(r"\bsketchy(?::[a-z0-9_]+(?::[a-z0-9_]+)*|_[a-z0-9_]+)")
EXTERNAL_METRIC = re.compile(r"(?<![:\w])(?:pg|node)_[a-z0-9_]+")

# The series the rules may read from exporters that are not this server. The
# names cannot be checked against an exposition here, so they are listed once,
# with the collector that produces each (postgres_exporter 0.17; node_exporter's
# filesystem collector). A collector that is off by default must be switched on
# in the scrape example, which the last test below checks.
EXTERNAL_SERIES: dict[str, str | None] = {
    "pg_up": None,
    "pg_settings_max_connections": None,
    "pg_stat_activity_count": None,
    "pg_stat_activity_max_tx_duration": None,
    "pg_database_size_bytes": None,
    "pg_stat_database_blks_hit": None,
    "pg_stat_database_blks_read": None,
    "pg_stat_user_tables_n_dead_tup": None,
    "pg_stat_user_tables_n_live_tup": None,
    "pg_stat_user_tables_last_autovacuum": None,
    "pg_database_wraparound_age_datfrozenxid_seconds": "database_wraparound",
    "pg_stat_checkpointer_num_requested_total": "stat_checkpointer",
    "pg_stat_checkpointer_num_timed_total": "stat_checkpointer",
    "node_filesystem_avail_bytes": None,
    "node_filesystem_size_bytes": None,
}


def exposed_names() -> set[str]:
    """Every family the scrape can carry, with the suffixes a histogram adds."""
    store = Telemetry()
    store.sources.sockets_connected = lambda: 1
    store.sources.pool = lambda: PoolGauges(5, 1, 4, 0, 10)
    store.http_request("GET", "/api/rooms", 200, 0.01)
    store.socket_event("draw", "ok", 0.001)
    store.socket_connection("accepted")
    store.note_socket_bytes_in(10)
    store.note_socket_bytes_out(10)
    store.socket_command_payload("draw", 10)
    store.socket_emit_payload("draw", 10)
    store.record_loop_lag(0.001)
    store.db_query(0.001, failed=True)
    store.history_write_abandoned("game", "timeout")
    store.sample_process()
    lines = [
        *_prometheus_lines(),
        *store.prometheus_lines(),
        *_loop_lines(
            {"mail_delivery": {"running": True, "consecutive_failures": 0, "total_failures": 0, "seconds_since_success": 1.0}}
        ),
        # Non-empty queues, so the oldest-age gauges - omitted when empty - appear.
        *_queue_lines(QueueSnapshot(QueueDepth(1, 5.0), QueueDepth(1, 5.0), HandoffDepth(1, 5.0, 0))),
        # A store with something in it, so both size gauges appear.
        *_drawing_store_lines(DrawingStoreSize(4096, 1)),
        # One table's worth of retention compliance, with every optional
        # field present, so each family in it is checked against the rules.
        *_retention_lines(
            {
                "room_messages": {
                    "rows": 3,
                    "batches": 1,
                    "seconds": 0.2,
                    "exhausted": False,
                    "failed": False,
                    "oldest_overdue_seconds": 0.0,
                    "backlog": 0,
                    "sla_seconds": 21600.0,
                    "removed_total": 3,
                    "failures_total": 0,
                }
            }
        ),
        *gauge_lines("sketchy_db_ready", "x", 1),
    ]
    names: set[str] = set()
    for line in lines:
        if line.startswith("# TYPE "):
            _, _, name, kind = line.split(" ", 3)
            names.add(name)
            if kind == "histogram":
                names.update({f"{name}_bucket", f"{name}_sum", f"{name}_count"})
    names.update(PROBE_METRIC_NAMES)
    # Prometheus' own series about the scrape target.
    names.add("up")
    return names


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def rule_names(document: dict) -> list[str]:
    return [rule["record"] for group in document["groups"] for rule in group["rules"] if "record" in rule]


def expressions(document: dict) -> list[tuple[str, str]]:
    return [
        (rule.get("alert") or rule.get("record"), rule["expr"])
        for group in document["groups"]
        for rule in group["rules"]
    ]


def all_rules() -> list[dict]:
    return [rule for path in RULE_FILES for group in load(path)["groups"] for rule in group["rules"]]


@pytest.mark.parametrize("path", RULE_FILES, ids=lambda p: p.name)
def test_the_rule_files_are_well_formed(path):
    document = load(path)
    assert document["groups"], path
    for group in document["groups"]:
        assert group["name"]
        for rule in group["rules"]:
            assert ("alert" in rule) != ("record" in rule), rule
            assert rule["expr"].strip()
            if "alert" in rule:
                assert rule["labels"]["severity"] in {"page", "warn"}, rule["alert"]
                assert rule["annotations"]["summary"]
                assert rule["annotations"]["runbook"].startswith(("README.md#", "docs/database.md#"))


def test_every_series_a_rule_names_is_one_the_server_exposes():
    known = exposed_names() | {name for path in RULE_FILES for name in rule_names(load(path))}
    unknown: dict[str, set[str]] = {}
    for path in RULE_FILES:
        for name, expr in expressions(load(path)):
            missing = {metric for metric in METRIC.findall(expr) if metric not in known}
            missing |= {metric for metric in EXTERNAL_METRIC.findall(expr) if metric not in EXTERNAL_SERIES}
            if missing:
                unknown[name] = missing
    assert unknown == {}, unknown


def test_every_recording_rule_is_used_by_an_alert():
    """A ratio nobody watches is a rule nobody maintains."""
    recorded = {name for path in RULE_FILES for name in rule_names(load(path))}
    used = {metric for rule in all_rules() if "alert" in rule for metric in METRIC.findall(rule["expr"])}
    assert recorded <= used, recorded - used


def test_the_slo_document_names_every_alert():
    """The objectives and the rules must not drift apart."""
    slo = (RULES.parents[2] / "docs" / "slo.md").read_text(encoding="utf-8")
    alerts = {rule["alert"] for rule in all_rules() if "alert" in rule}
    missing = {alert for alert in alerts if f"`{alert}`" not in slo}
    assert missing == set(), missing


def test_the_scrape_example_loads_every_rule_file_and_enables_every_collector_used():
    """A rule file Prometheus never loads, or a series whose collector is off, is silence."""
    scrape = SCRAPE.read_text(encoding="utf-8")
    config = yaml.safe_load(scrape)
    assert sorted(config["rule_files"]) == sorted(f"rules/{path.name}" for path in RULE_FILES)
    jobs = {job["job_name"] for job in config["scrape_configs"]}
    used = {metric for rule in all_rules() for metric in EXTERNAL_METRIC.findall(rule["expr"])}
    for metric in used:
        collector = EXTERNAL_SERIES[metric]
        if collector is not None:
            assert f"--collector.{collector}" in scrape, metric
    for job in re.findall(r'job="([a-z-]+)"', " ".join(rule["expr"] for rule in all_rules())):
        assert job in jobs, job
