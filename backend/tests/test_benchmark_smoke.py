"""Every database benchmark still runs (#895).

The measurements behind the storage decisions are scripts under
`benchmarks/`, run by hand, and a script nobody runs rots quietly:
`history_row_footprint.py` stopped working when #815 removed a keyword it
passed, and `index_plans.py` when #553 added a CHECK its seed did not meet,
and neither was noticed until somebody needed a number. Each one runs here at
its smallest size against this worker's disposable PostgreSQL database, so a
change that breaks one fails CI rather than the next review.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

BENCHMARKS = Path(__file__).resolve().parents[2] / "benchmarks"

# Smallest sizes that still exercise every step. A new benchmark that touches
# the database gets a line here; `test_every_database_benchmark_is_smoked`
# fails until it does.
SMOKE_ARGS: dict[str, tuple[str, ...]] = {
    "catalogue_star_page": ("--lists", "50", "--owners", "5", "--stars", "200", "--samples", "3"),
    "drawing_store_footprint": ("--games", "2"),
    "fk_delete_paths": ("--rows", "200"),
    "guest_name_check": ("--online", "20", "--samples", "3"),
    "history_row_footprint": ("--games", "2"),
    "index_plans": ("--scale", "0.01"),
    "index_write_cost": ("--sessions", "200", "--messages", "500"),
    "reaction_write": ("--reactions", "10", "--samples", "3"),
    "recipient_array_sizes": (),
    "retention_churn": ("--rows", "500", "--row-budget", "100", "--batch", "50", "--insert-batch", "100"),
    "score_ledger_footprint": ("--games", "2"),
    "session_middleware_cost": ("--requests", "20", "--database", "/tmp/sketchy-session-cost-smoke.db"),
    "user_stats": ("--games", "20", "--reads", "2"),
}

DATABASE_USE = re.compile(r"TEST_DATABASE_URL|create_test_db|async_sessionmaker")


def test_every_database_benchmark_is_smoked():
    touching = {
        path.stem
        for path in BENCHMARKS.glob("*.py")
        if DATABASE_USE.search(path.read_text(encoding="utf-8"))
    }
    assert touching == set(SMOKE_ARGS)


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
    reason="the database benchmarks measure PostgreSQL",
)
@pytest.mark.parametrize("name", sorted(SMOKE_ARGS))
def test_the_benchmark_runs_at_smoke_size(name):
    completed = subprocess.run(
        [sys.executable, str(BENCHMARKS / f"{name}.py"), *SMOKE_ARGS[name]],
        cwd=BENCHMARKS.parent / "backend",
        # As the owner where there is one (#896): the benchmarks empty tables
        # with TRUNCATE and refresh statistics with ANALYZE, which are the
        # owner's to do, not the application's.
        env={
            **os.environ,
            "TEST_DATABASE_URL": os.environ.get("TEST_OWNER_DATABASE_URL")
            or os.environ["TEST_DATABASE_URL"],
        },
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
