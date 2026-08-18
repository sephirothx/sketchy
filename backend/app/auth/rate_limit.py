"""In-memory per-client rate limiting for the authentication endpoints."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.requests import Request


class RateLimiter:
    """Fixed-capacity sliding window, keyed by client.

    Deliberately process-local and non-persistent: the server is a single
    process today, and the point is to blunt online password guessing and
    username enumeration, not to survive restarts. A shared store only becomes
    necessary alongside multi-replica deployment.
    """

    def __init__(self, limit: int, window_seconds: float) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> bool:
        """Record an attempt, returning False once the window is saturated."""
        now = time.monotonic()
        hits = self._hits[key]
        cutoff = now - self._window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

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
