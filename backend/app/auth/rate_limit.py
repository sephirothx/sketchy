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
    """Identify the caller, preferring the proxy-reported address.

    Deployments put this behind a tunnel or reverse proxy, where every
    connection arrives from the proxy itself - without reading the forwarded
    header the whole internet would share one bucket.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    client = request.client
    return client.host if client else "unknown"
