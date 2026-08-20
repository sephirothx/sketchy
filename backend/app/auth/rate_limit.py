"""In-memory per-client rate limiting for the authentication endpoints."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from starlette.requests import Request


class RateLimiter:
    """Fixed-capacity sliding window, keyed by client.

    Deliberately process-local and non-persistent: the server is a single
    process today, and the point is to blunt online password guessing and
    username enumeration, not to survive restarts. A shared store only becomes
    necessary alongside multi-replica deployment.
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


def client_key(request: Request) -> str:
    """Identify the caller by their connection, never by a request header.

    Reading ``X-Forwarded-For`` here would defeat the limiter entirely: the
    header is attacker-controlled, so a password-guesser could simply send a
    different value with every attempt and never fill a bucket.

    Behind a proxy, run uvicorn with ``--proxy-headers`` and
    ``--forwarded-allow-ips`` naming that proxy. Uvicorn then validates the
    header against the trusted hop and rewrites ``request.client`` itself, so
    the real address arrives here having actually been vouched for.
    """
    client = request.client
    return client.host if client else "unknown"
