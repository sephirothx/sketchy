"""Argon2 runs on a pool of its own, a few at a time (#975)."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.auth import password
from app.refusals import ErrorCode


class CountingHasher:
    """Stands in for argon2: slow enough to overlap, and counts the overlap."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.running = 0
        self.most = 0
        self.calls = 0

    def _work(self) -> None:
        with self._lock:
            self.running += 1
            self.calls += 1
            self.most = max(self.most, self.running)
        time.sleep(0.02)
        with self._lock:
            self.running -= 1

    def hash(self, value: str) -> str:
        self._work()
        return f"hashed:{value}"

    def verify(self, encoded: str, value: str) -> bool:
        self._work()
        return encoded == f"hashed:{value}"


@pytest.fixture
def capped(monkeypatch):
    """A fresh pool at a known cap, torn down after the test."""
    monkeypatch.setenv("PASSWORD_HASH_WORKERS", "5")  # no default produces 5
    hasher = CountingHasher()
    monkeypatch.setattr(password, "_hasher", hasher)
    monkeypatch.setattr(password, "_executor", None)
    outstanding = password._outstanding
    yield hasher
    if password._executor is not None:
        password._executor.shutdown(wait=True)
    password._executor = None
    # The count belongs to the process, not to this pool: a test that leaves
    # it high lowers the refusal floor for every test after it in this worker.
    assert password._outstanding == outstanding, "a slot was left taken"


async def test_a_burst_of_logins_runs_at_most_the_cap_at_once(capped, monkeypatch):
    """Login peeks its limiters before verifying, so a burst reaches argon2
    whole; in the shared 40-thread pool 200 of them at once held the loop at
    a p99 lag of ~30 ms and took ~600 MiB above idle."""
    monkeypatch.setattr(password, "QUEUED_PER_WORKER", 100)
    results = await asyncio.gather(
        *(password.verify_password("hashed:secret", "secret") for _ in range(30)),
        *(password.hash_password(f"pw-{index}") for index in range(10)),
    )
    assert capped.calls == 40
    assert capped.most == 5
    assert results[:30] == [True] * 30


def test_the_cap_is_validated(monkeypatch):
    monkeypatch.delenv("PASSWORD_HASH_WORKERS", raising=False)
    assert password.password_hash_workers() == password.PASSWORD_HASH_WORKERS_DEFAULT
    assert 1 <= password.PASSWORD_HASH_WORKERS_DEFAULT <= 4
    monkeypatch.setenv("PASSWORD_HASH_WORKERS", "2")
    assert password.password_hash_workers() == 2
    for bad in ("0", "33", "four"):
        monkeypatch.setenv("PASSWORD_HASH_WORKERS", bad)
        with pytest.raises(ValueError, match="PASSWORD_HASH_WORKERS"):
            password.password_hash_workers()


async def test_real_argon2_still_round_trips():
    encoded = await password.hash_password("correct horse battery staple")
    assert await password.verify_password(encoded, "correct horse battery staple")
    assert not await password.verify_password(encoded, "wrong horse battery staple")
    assert not await password.password_needs_rehash(encoded)


async def test_past_the_queue_depth_a_hash_is_refused_not_queued(capped, monkeypatch):
    """Login charges a failure only after verifying, so a burst of unknown
    usernames reaches argon2 whole; queued without a bound, every real login
    behind it waited the whole burst out (#975 review)."""
    monkeypatch.setattr(password, "QUEUED_PER_WORKER", 2)  # 5 workers x 2 = 10
    results = await asyncio.gather(
        *(password.verify_password("hashed:x", "x") for _ in range(14)),
        return_exceptions=True,
    )
    refused = [result for result in results if isinstance(result, password.PasswordHashingBusy)]
    assert len(refused) == 4 and capped.calls == 10
    assert refused[0].status_code == 503 and refused[0].headers["Retry-After"] == "1"
    # And in the body, which is what the client reads: a refusal with no
    # `retryAfterMs` is one the frontend cannot act on (#975 sixth review).
    assert refused[0].body()["retryAfterMs"] == 1000
    assert refused[0].code == ErrorCode.SERVER_BUSY, "a server-state refusal, not the caller's fault"
    # A refusal costs no slot: the counter is back where it started.
    assert password._outstanding == 0
    # And the pool takes work again once the backlog has gone.
    assert await password.verify_password("hashed:x", "x") is True


async def test_the_rehash_check_does_not_queue_behind_the_burst(capped, monkeypatch):
    """It only parses the parameters out of the encoded hash."""
    async def no_pool(*_args):
        raise AssertionError("the rehash check went to the hashing pool")

    monkeypatch.setattr(password, "_off_loop", no_pool)
    capped.check_needs_rehash = lambda value: True
    assert await password.password_needs_rehash("$argon2id$v=19$m=8,t=1,p=1$c2FsdA$aGFzaA") is True


async def test_a_cancelled_caller_does_not_hand_its_slot_to_somebody_else(capped, monkeypatch):
    """The work stays queued when the caller stops waiting, so the slot must
    stay taken until the job itself ends (#975 review)."""
    monkeypatch.setattr(password, "QUEUED_PER_WORKER", 1)  # 5 workers x 1 = 5
    waiting = [
        asyncio.create_task(password.verify_password("hashed:x", "x")) for _ in range(5)
    ]
    await asyncio.sleep(0.01)
    for task in waiting:
        task.cancel()
    await asyncio.gather(*waiting, return_exceptions=True)
    # The threads are still working through those five; a sixth is refused.
    with pytest.raises(password.PasswordHashingBusy):
        await password.verify_password("hashed:x", "x")
    # Once they finish, the slots come back.
    for _ in range(200):
        if password._outstanding == 0:
            break
        await asyncio.sleep(0.01)
    assert password._outstanding == 0
    assert await password.verify_password("hashed:x", "x") is True


def test_the_shipped_bound_is_the_documented_one():
    """Every test that exercises the cap overrides these, so the values the
    server actually ships are asserted here (#975 third review)."""
    assert password.QUEUED_PER_WORKER == 16
    assert password.RETRY_AFTER_SECONDS == 1
    assert 1 <= password.PASSWORD_HASH_WORKERS_DEFAULT <= 4


def test_a_slot_comes_back_when_the_loop_stops_under_the_hash():
    """The release used to be posted to the loop. A loop that is *stopped* -
    the shape a shutdown and a pytest teardown both produce - still accepts
    the callback and never runs it, so the slot was gone for the life of the
    process and the refusal floor crept down (#975 fifth review).

    Driven through `_off_loop` itself, with the job still running when the
    loop stops: that is the only arrangement where the two implementations
    differ.
    """
    import asyncio
    import threading
    import time

    from app.auth import password as password_module

    async def slow_job():
        return await password_module._off_loop(time.sleep, 0.5)

    loop = asyncio.new_event_loop()
    runner = threading.Thread(target=loop.run_forever, daemon=True)
    runner.start()
    try:
        before = password_module._outstanding
        asyncio.run_coroutine_threadsafe(slow_job(), loop)
        time.sleep(0.1)  # the job is on a worker thread, its slot taken
        assert password_module._outstanding == before + 1

        loop.call_soon_threadsafe(loop.stop)
        runner.join(timeout=5)
        assert not loop.is_closed() and not loop.is_running()

        for _ in range(100):  # the job ends on its worker thread meanwhile
            if password_module._outstanding == before:
                break
            time.sleep(0.02)

        assert password_module._outstanding == before, "the slot came back"
    finally:
        loop.close()


def test_the_check_and_the_slot_are_taken_under_one_lock(monkeypatch):
    """Two threads write this count - the loop takes a slot, a worker gives it
    back - so reading it and taking it must be one step. Removing the lock
    from the check passed every test, because the race is between threads and
    not between coroutines (#975 sixth review)."""
    import asyncio
    import inspect
    import threading

    class Watching:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self.depth = 0

        def __enter__(self):
            self._lock.acquire()
            self.depth += 1
            return self

        def __exit__(self, *_exc):
            self.depth -= 1
            self._lock.release()

    watching = Watching()
    monkeypatch.setattr(password, "_counter_lock", watching)
    seen: list[int] = []
    real_max_queued = password.max_queued
    monkeypatch.setattr(
        password, "max_queued", lambda: (seen.append(watching.depth), real_max_queued())[1]
    )

    async def one_hash():
        return await password._off_loop(lambda: "done")

    assert asyncio.run(one_hash()) == "done"
    assert seen == [1], "the cap was read with the lock held"
    assert watching.depth == 0, "and given back"
    # Both writes are under it too: the count is written from the loop and
    # from a worker thread, so a read-under-lock with a write outside it is no
    # better than no lock (#975 seventh review).
    lines = inspect.getsource(password._off_loop).splitlines()
    held = next(line for line in lines if "with _counter_lock:" in line)
    takes = next(line for line in lines if "_outstanding += 1" in line)
    indent = len(held) - len(held.lstrip())
    assert len(takes) - len(takes.lstrip()) > indent, "the slot is taken inside the lock"
    assert "with _counter_lock:" in inspect.getsource(password._release)


async def test_a_submit_that_raises_leaves_no_slot_taken(capped, monkeypatch):
    """The slot is taken after the pool has accepted the work: counting first
    and failing to submit would hold a slot for the life of the process, and
    the order was never pinned (#975 sixth review)."""
    class RefusingPool:
        def submit(self, *_args, **_kwargs):
            raise RuntimeError("this pool is shutting down")

    monkeypatch.setattr(password, "_pool", lambda: RefusingPool())
    before = password._outstanding

    with pytest.raises(RuntimeError):
        await password._off_loop(lambda: "never")

    assert password._outstanding == before
