"""The export worker: the table is the queue, one build at a time (R-PRIV-03)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

import app.auth.account_data as account_data_module
import app.services.data_export_worker as worker_module
from app.auth.account_data import create_data_export
from app.db.models import DataExport
from app.domain_values import DataExportStatus
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.data_export_worker import (
    DEFAULT_INTERVAL_SECONDS,
    DataExportWorker,
    stop_export_worker,
    sweep_interval_seconds,
)
from app.services.readiness import LoopHealth
from tests.dbfixtures import create_test_db

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "export-worker-test-secret")
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    yield factory, users
    await engine.dispose()


async def status_of(factory, job_id) -> DataExport:
    async with factory() as session:
        stored = await session.get(DataExport, job_id)
        assert stored is not None
        return stored


async def wait_until(predicate, *, within: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + within
    while True:
        if await predicate():
            return
        assert asyncio.get_running_loop().time() < deadline, "condition never held"
        await asyncio.sleep(0.01)


def ready(factory, job_id):
    async def check() -> bool:
        return (await status_of(factory, job_id)).status == DataExportStatus.READY.value

    return check


async def test_a_woken_worker_builds_the_pending_job(env):
    """A request writes the row and says "now"; the build happens on the
    loop, and readiness sees a loop that is running and succeeding."""
    factory, users = env
    player = await users.create_anonymous("Woken")
    job = await create_data_export(factory, user_id=player.id)
    health = LoopHealth("data_exports")
    worker = DataExportWorker(factory, interval_seconds=3600)
    task = worker.start(health=health)
    try:
        await wait_until(ready(factory, job.id))
        assert health.snapshot()["consecutive_failures"] == 0
        assert health.snapshot()["seconds_since_success"] is not None

        # Idle now: a second wake with nothing due is a cheap sweep, not a
        # rebuild - the ready row stays ready.
        before = (await status_of(factory, job.id)).completed_at
        worker.wake()
        await asyncio.sleep(0.05)
        assert (await status_of(factory, job.id)).completed_at == before
    finally:
        await stop_export_worker(task)
    assert task.cancelled()


async def test_a_wake_during_the_sweep_is_not_lost_until_the_next_interval(env, monkeypatch):
    """The wake is cleared before a sweep, not after: a row written in the
    moment between the sweep's query and its return is built next, rather
    than waiting out the whole interval."""
    factory, users = env
    player = await users.create_anonymous("JustMissed")
    worker = DataExportWorker(factory, interval_seconds=3600)
    original = worker_module.process_pending_data_exports
    created: list[DataExport] = []

    async def sweep_then_request(session_factory, **kwargs):
        completed = await original(session_factory, **kwargs)
        if not created:
            # After the query saw nothing, before the loop goes back to sleep.
            created.append(await create_data_export(factory, user_id=player.id))
            worker.wake()
        return completed

    monkeypatch.setattr(worker_module, "process_pending_data_exports", sweep_then_request)
    task = worker.start()
    try:
        await wait_until(lambda: asyncio.sleep(0, result=bool(created)))
        await wait_until(ready(factory, created[0].id), within=2.0)
    finally:
        await stop_export_worker(task)


async def test_the_sweep_reclaims_a_job_a_crashed_process_left_behind(env):
    """Nobody wakes the loop for a row the previous process was building
    when it died; the interval sweep finds it once it is stale."""
    factory, users = env
    player = await users.create_anonymous("Orphaned")
    now = datetime.now(timezone.utc)
    job = await create_data_export(factory, user_id=player.id, now=now)
    async with factory() as session:
        async with session.begin():
            stored = await session.get(DataExport, job.id)
            stored.status = DataExportStatus.PROCESSING.value
            stored.started_at = now - timedelta(minutes=16)

    worker = DataExportWorker(factory, interval_seconds=0.05)
    task = worker.start()
    try:
        await wait_until(ready(factory, job.id))
    finally:
        await stop_export_worker(task)


async def test_a_failing_sweep_is_counted_and_the_loop_carries_on(env, monkeypatch):
    factory, users = env
    player = await users.create_anonymous("Persistent")
    job = await create_data_export(factory, user_id=player.id)
    original = worker_module.process_pending_data_exports
    failures = {"left": 2}

    async def flaky(session_factory, **kwargs):
        if failures["left"]:
            failures["left"] -= 1
            raise RuntimeError("database went away")
        return await original(session_factory, **kwargs)

    monkeypatch.setattr(worker_module, "process_pending_data_exports", flaky)
    health = LoopHealth("data_exports")
    worker = DataExportWorker(factory, interval_seconds=0.02)
    task = worker.start(health=health)
    try:
        await wait_until(ready(factory, job.id))
        snapshot = health.snapshot()
        assert snapshot["total_failures"] == 2
        assert snapshot["consecutive_failures"] == 0
        assert not task.done()
    finally:
        await stop_export_worker(task)


async def test_a_planned_shutdown_hands_the_job_back(env):
    """Cancelled mid-build, the worker returns the row to `pending` so the
    next process builds it at once rather than after the stale window."""
    factory, users = env
    player = await users.create_anonymous("Interrupted")
    job = await create_data_export(factory, user_id=player.id)
    building = asyncio.Event()
    original = account_data_module._write_export_artifact

    async def never_finishes(session, writer, **kwargs):
        building.set()
        await asyncio.sleep(3600)

    account_data_module._write_export_artifact = never_finishes
    worker = DataExportWorker(factory, interval_seconds=3600)
    task = worker.start()
    try:
        worker.wake()
        await building.wait()
        assert (await status_of(factory, job.id)).status == DataExportStatus.PROCESSING.value
    finally:
        await stop_export_worker(task)
        account_data_module._write_export_artifact = original

    stored = await status_of(factory, job.id)
    assert stored.status == DataExportStatus.PENDING.value
    assert stored.started_at is None
    assert stored.failure_code is None

    # And the next worker finishes it without waiting for anything.
    task = DataExportWorker(factory, interval_seconds=3600).start()
    try:
        await wait_until(ready(factory, job.id))
    finally:
        await stop_export_worker(task)


async def test_two_jobs_never_build_at_once(env):
    """The whole point of the loop: two accounts asking together cost the
    process one build's memory, then the other's."""
    factory, users = env
    players = [await users.create_anonymous(f"Player{index}") for index in range(3)]
    jobs = [await create_data_export(factory, user_id=player.id) for player in players]
    original = account_data_module._write_export_artifact
    in_flight = {"now": 0, "peak": 0}

    async def observed(session, writer, **kwargs):
        in_flight["now"] += 1
        in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
        try:
            await asyncio.sleep(0.02)
            await original(session, writer, **kwargs)
        finally:
            in_flight["now"] -= 1

    account_data_module._write_export_artifact = observed
    worker = DataExportWorker(factory, interval_seconds=3600)
    task = worker.start()
    try:
        for _ in jobs:
            worker.wake()
        for job in jobs:
            await wait_until(ready(factory, job.id))
    finally:
        account_data_module._write_export_artifact = original
        await stop_export_worker(task)
    assert in_flight["peak"] == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", DEFAULT_INTERVAL_SECONDS), ("abc", DEFAULT_INTERVAL_SECONDS),
     ("0", DEFAULT_INTERVAL_SECONDS), ("-1", DEFAULT_INTERVAL_SECONDS), ("5", 5.0)],
)
async def test_the_sweep_interval_is_read_from_the_environment(raw, expected):
    assert sweep_interval_seconds({"EXPORT_SWEEP_SECONDS": raw}) == expected
