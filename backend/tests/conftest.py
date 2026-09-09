"""Give xdist workers isolated migrated databases before test modules import.

Also carries `--database-backed-only`, which the PostgreSQL job runs the suite
with; see `tests/database_backed.py` for what it selects and why.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from tests.database_backed import is_database_backed, module_name
from tests.parallel_databases import WorkerDatabases


_DATABASES = pytest.StashKey[WorkerDatabases]()


def pytest_configure(config):
    worker_url = getattr(config, "workerinput", {}).get("test_database_url")
    if worker_url:
        # Several tests capture this URL at import, and open additional
        # engines to prove row locking. Changing only dbfixtures is too late.
        os.environ["TEST_DATABASE_URL"] = worker_url


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node):
    template_url = os.environ.get("TEST_DATABASE_URL")
    if not template_url:
        return
    if _DATABASES not in node.config.stash:
        node.config.stash[_DATABASES] = WorkerDatabases(template_url)
    node.workerinput["test_database_url"] = asyncio.run(
        node.config.stash[_DATABASES].create()
    )


def pytest_unconfigure(config):
    if _DATABASES in config.stash:
        asyncio.run(config.stash[_DATABASES].close())


def pytest_addoption(parser):
    parser.addoption(
        "--database-backed-only",
        action="store_true",
        help=(
            "Run only the tests whose modules reach the shared database fixture. "
            "The PostgreSQL job uses it: everything else runs there exactly as it "
            "ran on SQLite."
        ),
    )


def pytest_report_header(config):
    if config.getoption("database_backed_only"):
        return "selecting database-backed modules only"


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    if not config.getoption("database_backed_only"):
        return
    selected, deselected = [], []
    for item in items:
        target = selected if is_database_backed(module_name(item.path)) else deselected
        target.append(item)
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
