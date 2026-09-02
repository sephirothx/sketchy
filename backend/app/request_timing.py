"""Count and time every HTTP request, by the route it matched.

Nothing measured the REST surface before: a slow endpoint or a burst of 500s
was visible only to the player it happened to. This wraps the whole
application so that the number recorded is the wall time a client actually
waited - including the session lookup, the size guard, and compression -
rather than the handler's view of itself.

Pure ASGI, like `RequestSizeLimitMiddleware` and for the same reason:
`BaseHTTPMiddleware` buffers bodies and breaks streaming, and a timer must
not change what it times.

The label is the route *template* (`/api/rooms/{room_id}`), never the path,
so the number of series cannot grow with the number of rooms. FastAPI writes
the matched route into the scope during routing, which is why the label is
read after the application returns and not before.
"""
from __future__ import annotations

import asyncio
from time import perf_counter

from app.services.telemetry import (
    HTTP_OUTCOME_ABORTED,
    STATIC_ROUTE,
    UNROUTED_ROUTE,
    Telemetry,
    telemetry as default_telemetry,
)


STATIC_PREFIX = "/assets/"


def route_label(scope) -> str:
    """The matched route's template, or one of two fixed labels for everything else."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    raw = scope.get("path", "")
    return STATIC_ROUTE if raw.startswith(STATIC_PREFIX) or raw == "/" else UNROUTED_ROUTE


class RequestTimingMiddleware:
    def __init__(self, app, *, telemetry: Telemetry | None = None) -> None:
        self.app = app
        self._telemetry = telemetry if telemetry is not None else default_telemetry

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        store = self._telemetry
        status = 0
        started = perf_counter()
        store.in_flight += 1

        async def send_wrapper(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except asyncio.CancelledError:
            # The client went away, or the server is shutting down: not an
            # error of ours, and not a latency either.
            status = status or HTTP_OUTCOME_ABORTED
            raise
        except Exception:
            # Counted before it propagates: the 500 body is written above
            # this middleware, so this is the last place that sees it.
            status = 500
            raise
        finally:
            store.in_flight -= 1
            store.http_request(
                scope.get("method", "GET"),
                route_label(scope),
                status or HTTP_OUTCOME_ABORTED,
                perf_counter() - started,
            )
