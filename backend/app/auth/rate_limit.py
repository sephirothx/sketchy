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
from sqlalchemy import delete, select, tuple_, update
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

    @property
    def limit(self) -> int:
        """How many attempts one key may spend inside the window."""
        return self._limit

    @limit.setter
    def limit(self, value: int) -> None:
        """Change the ceiling without discarding the windows already open.

        Rebuilding the limiter would be the obvious alternative and is the
        wrong one: it throws away every bucket in flight, so lowering a limit
        would hand the caller who has just spent theirs a fresh allowance -
        which is the opposite of what lowering it is for.
        """
        self._limit = value

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


def bucket_is_full(
    attempt_count: int, window_expires_at: datetime, limit: int, now: datetime
) -> bool:
    """Whether this bucket is refusing, as opposed to merely not matching.

    A spend that misses and a roll that misses do not together prove the
    bucket is full: another caller's roll or refund can land between the two
    statements, leaving a row that has room and matches neither. Presence is
    not a refusal - only a live window at its limit is.
    """
    return window_expires_at > now and attempt_count >= limit


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

    @property
    def limit(self) -> int:
        """How many attempts one key may spend inside the window."""
        return self._limit

    @limit.setter
    def limit(self, value: int) -> None:
        """Change the ceiling. The stored buckets are counted, not capped, so
        a new limit applies to every window already open rather than only to
        the ones opened after it."""
        self._limit = value

    async def _hash_secret(self) -> str:
        self._secret = await get_ip_hash_secret(
            self._session_factory, cached=self._secret
        )
        return self._secret

    async def _key_hash(self, key: str) -> str:
        """The bucket this caller belongs to, never their raw address."""
        secret = await self._hash_secret()
        return hmac.new(
            secret.encode("utf-8"),
            key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def check(self, key: str) -> bool:
        """Record one attempt without ever storing the raw client address.

        No decision is made here. Each statement carries its own condition -
        "spend one if this window is live and has room", "roll it if it has
        expired" - so the ceiling is evaluated by the database, against the
        row as it stands, rather than against a copy this process read a
        moment earlier. Reading first and writing back was safe on PostgreSQL
        because of `SELECT … FOR UPDATE` and safe nowhere else: SQLite ignores
        row locks and is the documented default, so the ceiling every limit
        rests on was soft by however many attempts were in flight together.
        """
        key_hash = await self._key_hash(key)

        for _ in range(3):
            checked_at = self._clock()
            verdict: bool | None = None
            present = False
            async with self._session_factory() as session:
                async with session.begin():
                    # Spend one from a live window that still has room. The
                    # `attempt_count <` is the ceiling, and the database
                    # evaluates it against the row as it stands rather than
                    # against a copy this process read a moment earlier.
                    taken = await session.execute(
                        update(AuthRateLimitBucket)
                        .where(
                            AuthRateLimitBucket.scope == self._scope,
                            AuthRateLimitBucket.key_hash == key_hash,
                            AuthRateLimitBucket.window_expires_at > checked_at,
                            AuthRateLimitBucket.attempt_count < self._limit,
                        )
                        .values(
                            attempt_count=AuthRateLimitBucket.attempt_count + 1,
                            updated_at=checked_at,
                        )
                    )
                    if taken.rowcount:
                        verdict = True
                    else:
                        # Or start a fresh window over one that has expired.
                        rolled = await session.execute(
                            update(AuthRateLimitBucket)
                            .where(
                                AuthRateLimitBucket.scope == self._scope,
                                AuthRateLimitBucket.key_hash == key_hash,
                                AuthRateLimitBucket.window_expires_at <= checked_at,
                            )
                            .values(
                                attempt_count=1,
                                window_started_at=checked_at,
                                window_expires_at=checked_at + self._window,
                                updated_at=checked_at,
                            )
                        )
                        if rolled.rowcount:
                            verdict = True
                        else:
                            # Neither matched. That is not proof the bucket is
                            # full: another caller's roll or refund can land
                            # between the two statements above, leaving a row
                            # with room that matched neither of them. Read what
                            # it actually says.
                            state = (
                                await session.execute(
                                    select(
                                        AuthRateLimitBucket.attempt_count,
                                        AuthRateLimitBucket.window_expires_at,
                                    ).where(
                                        AuthRateLimitBucket.scope == self._scope,
                                        AuthRateLimitBucket.key_hash == key_hash,
                                    )
                                )
                            ).first()
                            present = state is not None
                            if state is not None and bucket_is_full(
                                state.attempt_count,
                                state.window_expires_at,
                                self._limit,
                                checked_at,
                            ):
                                verdict = False
            # Deliberately outside the transaction above: `_finish` may sweep
            # expired buckets, and doing that on a second connection while
            # this one still holds the row would be two writers reaching for
            # the same table - a lock fight on SQLite and a deadlock waiting
            # to happen on PostgreSQL.
            if verdict is not None:
                return await self._finish(verdict)
            if present:
                # The row moved underneath this attempt - rolled or refunded
                # between the two statements - so it has room that neither
                # matched. Go round and spend from it rather than refusing
                # somebody a slot that exists.
                continue

            try:
                async with self._session_factory() as session:
                    async with session.begin():
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
                return await self._finish(True)
            except IntegrityError:
                # Somebody opened the window between the read and the insert.
                # Go round: the first statement will find it and either spend
                # from it or refuse.
                await asyncio.sleep(0)

        # If callers cannot agree on the bucket, fail closed.
        return False

    async def _finish(self, allowed: bool) -> bool:
        """Count the check and occasionally take out the expired buckets."""
        self._checks += 1
        if self._checks % PERSISTENT_CLEANUP_INTERVAL == 0:
            await cleanup_expired_rate_limit_buckets(self._session_factory)
        return allowed

    async def refund(self, key: str) -> None:
        """Give back an attempt that did not buy the thing it paid for.

        A limit on an action that can still fail after the bucket is charged
        would otherwise spend somebody's allowance on work that never
        happened. The condition travels with the statement, for the same
        reason it does in `check`: two refunds in flight together must not
        take the count below what was actually spent, and they would if this
        read the count and wrote back a decision made from it. An expired or missing bucket is nothing to give back
        to.
        """
        key_hash = await self._key_hash(key)
        refunded_at = self._clock()
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(AuthRateLimitBucket)
                    .where(
                        AuthRateLimitBucket.scope == self._scope,
                        AuthRateLimitBucket.key_hash == key_hash,
                        AuthRateLimitBucket.window_expires_at > refunded_at,
                        AuthRateLimitBucket.attempt_count > 0,
                    )
                    .values(
                        attempt_count=AuthRateLimitBucket.attempt_count - 1,
                        updated_at=refunded_at,
                    )
                )


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
