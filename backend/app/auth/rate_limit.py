"""Local low-risk and persistent security-sensitive request rate limits."""
from __future__ import annotations

import time
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import secrets
from collections import defaultdict, deque
from collections.abc import Callable

from starlette.requests import Request
from sqlalchemy import delete, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AppConfig, AuthRateLimitBucket


IP_HASH_CONFIG_KEY = "ip_hash_secret"
PERSISTENT_CLEANUP_INTERVAL = 1000


async def get_ip_hash_secret(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    cached: str | None = None,
) -> str:
    """Return the deployment-wide HMAC key without ever exposing it to clients."""
    configured = os.environ.get("IP_HASH_SECRET", "").strip()
    if configured:
        return configured
    if cached:
        return cached

    for _ in range(5):
        candidate = secrets.token_urlsafe(32)
        try:
            async with session_factory() as session:
                async with session.begin():
                    config = await session.get(AppConfig, IP_HASH_CONFIG_KEY)
                    if config is not None:
                        return config.value
                    session.add(AppConfig(key=IP_HASH_CONFIG_KEY, value=candidate))
                    await session.flush()
                    return candidate
        except IntegrityError:
            await asyncio.sleep(0)
    raise RuntimeError("Could not establish the IP hashing secret")


async def keyed_client_hash(
    session_factory: async_sessionmaker[AsyncSession], key: str
) -> str:
    """Hash a client address for audit correlation without storing the address."""
    secret = await get_ip_hash_secret(session_factory)
    return hmac.new(
        secret.encode("utf-8"),
        key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class RateLimiter:
    """Fixed-capacity sliding window, keyed by client.

    Deliberately process-local for low-risk profile/statistics endpoints. Auth
    attempts use ``PersistentRateLimiter`` below.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._swept_at = clock()

    def check(self, key: str) -> bool:
        """Record an attempt, returning False once the window is saturated."""
        now = self._clock()
        cutoff = now - self._window
        self._drop_expired_buckets(now, cutoff)
        hits = self._hits[key]
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    def refund(self, key: str) -> None:
        """Give back the most recent attempt, for one that bought nothing.

        A limit on an action that can still fail after the window is charged
        would otherwise spend somebody's allowance on work that never
        happened - and, worse, change the reason they are given for the
        failure. Only the newest hit is dropped, so a refund cannot return
        more than the attempt it is undoing.
        """
        hits = self._hits.get(key)
        if hits:
            hits.pop()

    def _drop_expired_buckets(self, now: float, cutoff: float) -> None:
        """Forget clients whose newest attempt has aged out of the window.

        `check` inserts a bucket for every distinct key it is asked about, and
        expiring timestamps inside a bucket never empties the map itself - so
        without this the map grows for the life of the process, one permanent
        entry per address ever seen. That is a slow leak in a process which
        also holds every live game in memory.

        Only buckets that could no longer refuse anything are dropped, so this
        can never let a client off its limit early: a bucket whose newest hit
        has expired behaves exactly like the empty one that replaces it.

        Deliberately not a size cap. Evicting the oldest bucket to stay under
        a ceiling would let a client escape its own limit by flooding the map
        with other keys, which is precisely the traffic the limiter exists to
        blunt. Sweeping on age bounds the map by how many distinct clients
        actually appear in a window, and refuses nobody who is still inside one.
        """
        if now - self._swept_at < self._window:
            return
        self._swept_at = now
        # Rebuilt rather than deleted from: a dict never shrinks its own table,
        # so deleting in place would leave the spike's footprint behind long
        # after the clients that caused it had gone.
        self._hits = defaultdict(
            deque,
            {
                key: hits for key, hits in self._hits.items()
                if hits and hits[-1] > cutoff
            },
        )

    def tracked_keys(self) -> int:
        """How many clients the limiter is currently holding state for."""
        return len(self._hits)

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


async def cleanup_expired_rate_limit_buckets(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    before: datetime | None = None,
    limit: int = 1000,
) -> int:
    """Remove one bounded batch so distinct historic addresses cannot accumulate."""
    if limit < 1:
        return 0
    cutoff = before or datetime.now(timezone.utc)
    async with session_factory() as session:
        async with session.begin():
            keys = (
                await session.execute(
                    select(
                        AuthRateLimitBucket.scope,
                        AuthRateLimitBucket.key_hash,
                    )
                    .where(AuthRateLimitBucket.window_expires_at <= cutoff)
                    .order_by(AuthRateLimitBucket.window_expires_at)
                    .limit(limit)
                )
            ).all()
            if not keys:
                return 0
            await session.execute(
                delete(AuthRateLimitBucket).where(
                    tuple_(
                        AuthRateLimitBucket.scope,
                        AuthRateLimitBucket.key_hash,
                    ).in_(keys)
                )
            )
            return len(keys)


class PersistentRateLimiter:
    """Database-backed fixed window shared by restarts and server replicas."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        scope: str,
        limit: int,
        window_seconds: float,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        if not scope or len(scope) > 32:
            raise ValueError("rate-limit scope must be 1-32 characters")
        self._session_factory = session_factory
        self._scope = scope
        self._limit = limit
        self._window = timedelta(seconds=window_seconds)
        self._clock = clock
        self._secret: str | None = None
        self._checks = 0

    async def _hash_secret(self) -> str:
        self._secret = await get_ip_hash_secret(
            self._session_factory, cached=self._secret
        )
        return self._secret

    async def check(self, key: str) -> bool:
        """Record one attempt without ever storing the raw client address."""
        secret = await self._hash_secret()
        key_hash = hmac.new(
            secret.encode("utf-8"),
            key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        for _ in range(3):
            checked_at = self._clock()
            try:
                async with self._session_factory() as session:
                    async with session.begin():
                        bucket = await session.scalar(
                            select(AuthRateLimitBucket)
                            .where(
                                AuthRateLimitBucket.scope == self._scope,
                                AuthRateLimitBucket.key_hash == key_hash,
                            )
                            .with_for_update()
                        )
                        if bucket is None:
                            session.add(
                                AuthRateLimitBucket(
                                    scope=self._scope,
                                    key_hash=key_hash,
                                    attempt_count=1,
                                    window_started_at=checked_at,
                                    window_expires_at=checked_at + self._window,
                                    updated_at=checked_at,
                                )
                            )
                            await session.flush()
                            allowed = True
                        elif bucket.window_expires_at <= checked_at:
                            bucket.attempt_count = 1
                            bucket.window_started_at = checked_at
                            bucket.window_expires_at = checked_at + self._window
                            bucket.updated_at = checked_at
                            allowed = True
                        elif bucket.attempt_count >= self._limit:
                            allowed = False
                        else:
                            bucket.attempt_count += 1
                            bucket.updated_at = checked_at
                            allowed = True
                break
            except IntegrityError:
                await asyncio.sleep(0)
        else:
            # If replicas cannot agree on the bucket, fail closed.
            return False

        self._checks += 1
        if self._checks % PERSISTENT_CLEANUP_INTERVAL == 0:
            await cleanup_expired_rate_limit_buckets(self._session_factory)
        return allowed


    async def refund(self, key: str) -> None:
        """Give back an attempt that did not buy the thing it paid for.

        A limit on an action that can still fail after the bucket is charged
        would otherwise spend somebody's allowance on work that never
        happened. Only ever called by the code that took the attempt, and
        only when it knows the action did not occur; an expired or missing
        bucket is nothing to give back to.
        """
        secret = await self._hash_secret()
        key_hash = hmac.new(
            secret.encode("utf-8"),
            key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        refunded_at = self._clock()
        async with self._session_factory() as session:
            async with session.begin():
                bucket = await session.scalar(
                    select(AuthRateLimitBucket)
                    .where(
                        AuthRateLimitBucket.scope == self._scope,
                        AuthRateLimitBucket.key_hash == key_hash,
                    )
                    .with_for_update()
                )
                if bucket is None or bucket.window_expires_at <= refunded_at:
                    return
                bucket.attempt_count = max(0, bucket.attempt_count - 1)
                bucket.updated_at = refunded_at


def client_key(request: Request) -> str:
    """Identify the caller by their connection, never by a request header.

    Reading ``X-Forwarded-For`` here would defeat the limiter entirely: the
    header is attacker-controlled, so a password-guesser could simply send a
    different value with every attempt and never fill a bucket.

    Behind a proxy, run the production server with ``PROXY_HEADERS=1`` and
    ``FORWARDED_ALLOW_IPS`` naming that proxy. Uvicorn then validates the header
    against the trusted hop and rewrites ``request.client`` itself, so the real
    address arrives here having actually been vouched for.
    """
    client = request.client
    return client.host if client else "unknown"
