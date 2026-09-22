"""Argon2 runs on a pool of its own, a few at a time (#975)."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.auth import password


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
    monkeypatch.setenv("PASSWORD_HASH_WORKERS", "3")
    hasher = CountingHasher()
    monkeypatch.setattr(password, "_hasher", hasher)
    monkeypatch.setattr(password, "_executor", None)
    yield hasher
    if password._executor is not None:
        password._executor.shutdown(wait=True)
    password._executor = None


async def test_a_burst_of_logins_runs_at_most_the_cap_at_once(capped):
    """Login peeks its limiters before verifying, so a burst reaches argon2
    whole; in the shared 40-thread pool 200 of them at once held the loop at
    a p99 lag of 59 ms and took ~760 MiB."""
    results = await asyncio.gather(
        *(password.verify_password("hashed:secret", "secret") for _ in range(30)),
        *(password.hash_password(f"pw-{index}") for index in range(10)),
    )
    assert capped.calls == 40
    assert capped.most == 3
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
