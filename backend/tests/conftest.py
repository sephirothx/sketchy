"""Give xdist workers isolated migrated databases before test modules import."""
from __future__ import annotations

import asyncio
import os

import pytest

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
