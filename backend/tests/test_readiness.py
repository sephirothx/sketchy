"""`/api/ready` tests the dependencies it needs, not only its own state.

Readiness used to report the shutdown coordinator's in-memory state and
nothing else, so an instance whose database had gone away answered exactly
like a healthy one - a load balancer kept sending it players, and an automated
rollback had nothing to detect.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, readiness_probe, shutdown_coordinator
from app.services.readiness import LoopHealth, ReadinessProbe


pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _a_ready_process():
    """A started process with no supervised loops and a working database."""
    state = shutdown_coordinator._state
    shutdown_coordinator._state = "ready"
    readiness_probe.release()
    readiness_probe._cached_database = None
    yield
    shutdown_coordinator._state = state
    readiness_probe.release()
    readiness_probe._cached_database = None


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _a_finished_task() -> asyncio.Task[None]:
    async def done() -> None:
        return None

    return asyncio.get_event_loop().create_task(done())


class _FailingSessionFactory:
    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise self.error


class _CountingSessionFactory:
    """A session whose `SELECT 1` succeeds, counting how often it is asked."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_) -> bool:
        return False

    async def execute(self, _statement):
        return None


class _HangingSessionFactory(_CountingSessionFactory):
    async def execute(self, _statement):
        await asyncio.sleep(3600)


# --- the endpoint -----------------------------------------------------------


async def test_a_healthy_process_is_ready():
    async with await _client() as client:
        response = await client.get("/api/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_a_database_that_cannot_be_reached_is_not_ready(monkeypatch):
    monkeypatch.setattr(
        readiness_probe, "session_factory", _FailingSessionFactory(OSError("gone"))
    )
    async with await _client() as client:
        response = await client.get("/api/ready")
    assert response.status_code == 503
    assert "database unavailable" in response.json()["detail"]["reason"]


async def test_a_database_that_will_not_answer_in_time_is_not_ready(monkeypatch):
    """A stalled dependency must fail the probe rather than hold it open."""
    monkeypatch.setattr(readiness_probe, "session_factory", _HangingSessionFactory())
    monkeypatch.setattr(readiness_probe, "timeout_seconds", 0.05)
    async with await _client() as client:
        response = await client.get("/api/ready")
    assert response.status_code == 503
    assert "did not answer within" in response.json()["detail"]["reason"]


async def test_a_background_loop_that_stopped_is_not_ready():
    """`run_*_loop` never returns, so a finished task means it is gone."""
    task = _a_finished_task()
    await task
    readiness_probe.supervise("retention_sweep", task, LoopHealth("retention_sweep"))
    async with await _client() as client:
        response = await client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["detail"]["reason"] == (
        "background loop stopped: retention_sweep"
    )


async def test_a_loop_that_only_errors_stays_in_rotation():
    """Otherwise a failing email sweep pulls a playable game server offline."""
    health = LoopHealth("mail_delivery")
    for _ in range(20):
        health.record_failure()
    running = asyncio.get_event_loop().create_task(asyncio.sleep(3600))
    readiness_probe.supervise("mail_delivery", running, health)
    try:
        async with await _client() as client:
            ready = await client.get("/api/ready")
            reported = await client.get("/api/health")
    finally:
        # Awaited, not merely cancelled: a task still pending when the test
        # returns leaks into event-loop teardown and warns from somewhere else.
        running.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await running

    assert ready.status_code == 200
    loop = reported.json()["loops"]["mail_delivery"]
    assert loop["running"] is True
    assert loop["consecutive_failures"] == 20


async def test_a_drain_answers_before_any_dependency_is_asked(monkeypatch):
    """R-SHUT-01: readiness flips to 503 at drain start, whatever else is wrong."""
    probing = _FailingSessionFactory(OSError("gone"))
    monkeypatch.setattr(readiness_probe, "session_factory", probing)
    shutdown_coordinator._state = "draining"
    async with await _client() as client:
        response = await client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["detail"]["reason"] == "draining"
    assert probing.calls == 0


async def test_a_drain_that_begins_mid_probe_still_answers_first(monkeypatch):
    """R-SHUT-01 is an ordering guarantee, and the probe yields for up to 1 s.

    An answer computed before the drain must not be delivered after it.
    """

    class _DrainsWhileAnswering(_CountingSessionFactory):
        async def execute(self, _statement):
            shutdown_coordinator._state = "draining"
            return None

    monkeypatch.setattr(readiness_probe, "session_factory", _DrainsWhileAnswering())
    async with await _client() as client:
        response = await client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["detail"]["reason"] == "draining"


async def test_a_loop_that_stops_mid_probe_is_caught_on_the_way_out(monkeypatch):
    """The probe is a scheduling point, so the loops can change under it too."""
    stopping = asyncio.get_event_loop().create_task(asyncio.sleep(3600))
    readiness_probe.supervise("mail_delivery", stopping, LoopHealth("mail_delivery"))

    class _StopsALoopWhileAnswering(_CountingSessionFactory):
        async def execute(self, _statement):
            stopping.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stopping

    monkeypatch.setattr(readiness_probe, "session_factory", _StopsALoopWhileAnswering())
    async with await _client() as client:
        response = await client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["detail"]["reason"] == (
        "background loop stopped: mail_delivery"
    )


async def test_liveness_never_fails_on_a_dependency(monkeypatch):
    """A restart cannot fix a database outage, so liveness must not ask for one."""
    monkeypatch.setattr(
        readiness_probe, "session_factory", _FailingSessionFactory(OSError("gone"))
    )
    async with await _client() as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# --- the probe itself -------------------------------------------------------


async def test_the_database_check_is_cached_between_probes():
    """A load balancer polling every second must not become the load."""
    factory = _CountingSessionFactory()
    now = [1000.0]
    probe = ReadinessProbe(factory, cache_seconds=5.0, clock=lambda: now[0])

    assert await probe.check_database() == (True, None)
    assert await probe.check_database() == (True, None)
    assert factory.calls == 1

    now[0] += 5.0
    assert await probe.check_database() == (True, None)
    assert factory.calls == 2


async def test_concurrent_probes_share_one_round_trip():
    """The cache absorbs a poll only if a miss does not let the whole poll in.

    Without a lock, every probe arriving between expiry and the first result
    stored sees a stale entry and opens its own session - so the load the
    cache exists to prevent arrives in full the instant it expires.
    """
    released = asyncio.Event()

    class _WaitsToBeReleased(_CountingSessionFactory):
        async def execute(self, _statement):
            await released.wait()

    factory = _WaitsToBeReleased()
    probe = ReadinessProbe(factory, cache_seconds=5.0, clock=lambda: 1000.0)

    probes = [
        asyncio.get_event_loop().create_task(probe.check_database())
        for _ in range(8)
    ]
    for _ in range(20):
        await asyncio.sleep(0)
    released.set()

    assert all(result == (True, None) for result in await asyncio.gather(*probes))
    assert factory.calls == 1


async def test_a_failed_database_check_is_cached_too():
    """A dependency already in trouble must not be retried once per probe."""
    factory = _FailingSessionFactory(OSError("gone"))
    now = [1000.0]
    probe = ReadinessProbe(factory, cache_seconds=5.0, clock=lambda: now[0])

    ready, reason = await probe.check_database()
    assert ready is False and "database unavailable" in reason
    assert (await probe.check_database())[0] is False
    assert factory.calls == 1


async def test_a_recorded_success_clears_the_failure_streak():
    health = LoopHealth("retention_sweep")
    health.record_failure()
    health.record_failure()
    assert health.consecutive_failures == 2

    health.record_success()
    assert health.consecutive_failures == 0
    # The total is kept: the streak says "right now", the total says "at all".
    assert health.total_failures == 2
    assert health.snapshot()["seconds_since_success"] is not None


# --- the loops report what they swallow ------------------------------------


async def _one_iteration(coroutine) -> None:
    """Let a for-ever loop run until it reaches its first sleep, then stop."""
    task = asyncio.get_event_loop().create_task(coroutine)
    for _ in range(50):
        await asyncio.sleep(0)
        if task.done():
            break
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.mark.parametrize(
    ("module_name", "worker", "runner", "value"),
    [
        (
            "app.auth.retention",
            "purge_stale_anonymous_accounts",
            "run_retention_loop",
            SimpleNamespace(total=0, unused_accounts=0, player_accounts=0),
        ),
        (
            "app.services.mail_delivery",
            "deliver_pending",
            "run_delivery_loop",
            SimpleNamespace(attempted=0, sent=0, deferred=0, failed=0),
        ),
        ("app.services.runtime_metrics", "flush_events", "run_metrics_loop", None),
    ],
)
async def test_every_loop_records_the_sweep_it_just_did(
    monkeypatch, module_name, worker, runner, value
):
    module = importlib.import_module(module_name)
    health = LoopHealth(worker)

    async def succeed(*_args, **_kwargs):
        return value

    monkeypatch.setattr(module, worker, succeed)
    # The retention loop performs three sweeps per iteration; the parametrized
    # worker is the one under test, and its siblings are stubbed so this stays
    # a test about health recording rather than about a database.
    async def swept_nothing(*_args, **_kwargs):
        return 0

    for sibling in ("purge_expired_auth_sessions", "purge_expired_data_exports"):
        if hasattr(module, sibling):
            monkeypatch.setattr(module, sibling, swept_nothing)
    await _one_iteration(
        getattr(module, runner)(None, interval_seconds=1, health=health)
    )
    assert health.consecutive_failures == 0
    assert health.last_success is not None


@pytest.mark.parametrize(
    ("module_name", "worker", "runner"),
    [
        ("app.auth.retention", "purge_stale_anonymous_accounts", "run_retention_loop"),
        ("app.services.mail_delivery", "deliver_pending", "run_delivery_loop"),
        ("app.services.runtime_metrics", "flush_events", "run_metrics_loop"),
    ],
)
async def test_a_sweep_that_raises_is_counted_rather_than_only_logged(
    monkeypatch, module_name, worker, runner
):
    """The loops survive every failure, which is also what hides them."""
    module = importlib.import_module(module_name)
    health = LoopHealth(worker)

    async def fail(*_args, **_kwargs):
        raise RuntimeError("the sweep broke")

    monkeypatch.setattr(module, worker, fail)
    await _one_iteration(
        getattr(module, runner)(None, interval_seconds=1, health=health)
    )
    assert health.consecutive_failures == 1
    assert health.total_failures == 1
    assert health.last_success is None


async def test_a_purge_failure_does_not_also_report_the_flush_as_a_success(monkeypatch):
    """`last_success` is what an alert trusts, so it must not pass a failure.

    The metrics loop purges on some iterations and not others. Recording the
    success right after the flush marked those iterations successful before
    the purge had a chance to fail, so one iteration reported both.
    """
    metrics = importlib.import_module("app.services.runtime_metrics")
    health = LoopHealth("runtime_metrics")

    async def flushed(*_args, **_kwargs):
        return None

    async def purge_fails(*_args, **_kwargs):
        raise RuntimeError("the purge broke")

    monkeypatch.setattr(metrics, "flush_events", flushed)
    monkeypatch.setattr(metrics, "purge_expired_events", purge_fails)
    # An interval this long makes the first iteration a purge iteration.
    await _one_iteration(
        metrics.run_metrics_loop(None, interval_seconds=3600, health=health)
    )

    assert health.last_success is None
    assert health.consecutive_failures == 1


async def test_the_last_probe_result_is_readable_without_probing_again():
    """The operations page reads what the load balancer last found, however
    old, and must never become a second prober."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = [1000.0]
    probe = ReadinessProbe(factory, cache_seconds=5.0, clock=lambda: now[0])
    try:
        assert probe.last_database_result() is None
        assert await probe.check_database() == (True, None)
        now[0] += 42.0
        assert probe.last_database_result() == {
            "ok": True,
            "reason": None,
            "checkedAgoSeconds": 42.0,
        }
    finally:
        await engine.dispose()
