"""A startup that fails reports why it failed, not what never started.

The lifespan starts eight background loops and stops them all in a `finally`.
When startup raises before the loops exist - a refused database revision, a
misconfigured relay - that `finally` still runs, and every handle it names has
to already exist or the shutdown path buries the real cause under an
`UnboundLocalError` from the cleanup. On a short terminal the operator sees
only the second traceback, which describes nothing that went wrong.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import main


class RefusedStartup(Exception):
    """Stands in for anything init_db raises: a revision it does not know."""


def _quiet_shutdown(monkeypatch):
    monkeypatch.setenv("SHUTDOWN_DRAIN_SECONDS", "0")
    monkeypatch.setattr(main, "async_engine", SimpleNamespace(dispose=AsyncMock()))


async def test_startup_failure_propagates_its_own_exception(monkeypatch):
    _quiet_shutdown(monkeypatch)
    monkeypatch.setattr(main, "init_db", AsyncMock(side_effect=RefusedStartup("boom")))

    with pytest.raises(RefusedStartup, match="boom"):
        async with main.lifespan(main.api):
            pytest.fail("startup should not have completed")


async def test_startup_failure_before_any_loop_starts_none_of_them(monkeypatch):
    """Every handle the `finally` stops, proven unreachable by this failure.

    `init_db` runs before the first `start_*` call, so a failure there leaves
    all eight unassigned - which is exactly the shape that used to raise from
    the cleanup. Patching each start to fail loudly states the invariant the
    other test only implies.
    """

    _quiet_shutdown(monkeypatch)
    monkeypatch.setattr(main, "init_db", AsyncMock(side_effect=RefusedStartup("boom")))
    starters = (
        "start_delivery_loop",
        "start_metrics_loop",
        "start_retention_loop",
        "start_presence_loop",
        "start_afk_loop",
        "start_lag_sampler",
    )
    for name in starters:
        monkeypatch.setattr(
            main, name, lambda *a, **k: pytest.fail("a loop started after the failure")
        )

    with pytest.raises(RefusedStartup):
        async with main.lifespan(main.api):
            pytest.fail("startup should not have completed")
