"""The tracked PostgreSQL server configuration says what it sets and why (#889).

`ops/postgres/check-config.sh` proves the files against a real server; this
test keeps the cheap part in CI: every setting carries its reason, and the
settings other parts of the repository depend on are still there. The alert
rules read pg_stat_statements, the runbook reads the slow-statement log by
application name, and checksums cannot be switched on after initdb.
"""
from __future__ import annotations

from pathlib import Path
import re

OPS = Path(__file__).resolve().parents[2] / "ops" / "postgres"
SETTING = re.compile(r"^([a-z_.]+)\s*=\s*(.+?)\s*$")


def settings() -> dict[str, str]:
    found: dict[str, str] = {}
    for line in (OPS / "sketchy.conf").read_text(encoding="utf-8").splitlines():
        match = SETTING.match(line)
        if match:
            name, value = match.groups()
            assert name not in found, f"{name} is set twice"
            found[name] = value.strip("'")
    return found


def test_every_setting_states_its_reason():
    """A value with no reason is one nobody can safely change."""
    lines = (OPS / "sketchy.conf").read_text(encoding="utf-8").splitlines()
    unexplained = []
    for index, line in enumerate(lines):
        if SETTING.match(line):
            previous = index - 1
            while previous >= 0 and SETTING.match(lines[previous]):
                previous -= 1
            if previous < 0 or not lines[previous].startswith("#"):
                unexplained.append(line)
    assert unexplained == []


def test_the_settings_the_rest_of_the_repository_relies_on_are_present():
    found = settings()
    assert found["shared_preload_libraries"] == "pg_stat_statements"
    assert found["pg_stat_statements.track"] == "top"
    assert found["pg_stat_statements.track_planning"] == "off"
    for name in ("track_io_timing", "track_wal_io_timing", "log_lock_waits", "log_checkpoints"):
        assert found[name] == "on", name
    assert found["log_min_duration_statement"] == "250ms"
    assert found["log_autovacuum_min_duration"] == "0"
    assert found["log_temp_files"] == "0"
    # The runbook finds a slow statement's role by the application_name.
    assert "%a" in found["log_line_prefix"]
    assert found["wal_compression"] == "lz4"
    assert found["default_toast_compression"] == "lz4"


def test_max_connections_leaves_room_for_the_web_pool():
    from app.db import get_engine_pool_options

    pool = get_engine_pool_options("postgresql+asyncpg://u:p@h/db")
    web = pool["pool_size"] + pool["max_overflow"]
    # web + migration + maintenance + exporter + two psql + superuser reserve (3)
    assert int(settings()["max_connections"]) >= web + 1 + 1 + 1 + 2 + 3


def test_the_cluster_is_created_with_checksums():
    flags = [
        line for line in (OPS / "initdb.args").read_text(encoding="utf-8").splitlines() if not line.startswith("#")
    ]
    assert "--data-checksums" in " ".join(flags).split()


def test_the_extension_and_the_monitor_role_are_created_idempotently():
    script = (OPS / "init.sql").read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS pg_stat_statements" in script
    assert "GRANT pg_monitor TO sketchy_monitor" in script
    # No secret is tracked: the password is set by hand, never in the file.
    assert not re.search(r"PASSWORD\s+'", script, re.IGNORECASE)
