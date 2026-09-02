"""Count, time and name every HTTP request, by the route it matched.

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

It is also where a request gets its identity. An `X-Request-ID` the caller
supplied is accepted if it is a UUID and minted otherwise, set as the
correlation context for everything underneath, echoed on the response so a
client can quote it, and written into the one access line this middleware
logs per request - which is what replaces uvicorn's access log.
"""
from __future__ import annotations

import asyncio
import logging
from time import perf_counter

from app import correlation
from app.services.telemetry import (
    HTTP_OUTCOME_ABORTED,
    PROBE_ROUTES,
    STATIC_ROUTE,
    UNROUTED_ROUTE,
    Telemetry,
    telemetry as default_telemetry,
)


STATIC_PREFIX = "/assets/"
RESPONSE_HEADER = b"x-request-id"

access_log = logging.getLogger("sketchy.http")


def route_label(scope) -> str:
    """The matched route's template, or one of two fixed labels for everything else."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    raw = scope.get("path", "")
    return STATIC_ROUTE if raw.startswith(STATIC_PREFIX) or raw == "/" else UNROUTED_ROUTE


def _supplied_request_id(scope) -> str | None:
    for name, value in scope.get("headers") or ():
        if name.lower() == correlation.REQUEST_ID_HEADER.encode():
            return correlation.accepted_request_id(value)
    return None


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
        request_id = _supplied_request_id(scope) or correlation.new_request_id()
        token = correlation.request_id.set(request_id)
        store.in_flight += 1

        async def send_wrapper(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                # Echoed so a client or a proxy can quote the id our logs use.
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != RESPONSE_HEADER
                ]
                headers.append((RESPONSE_HEADER, request_id.encode("ascii")))
                message = {**message, "headers": headers}
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
            elapsed = perf_counter() - started
            method = scope.get("method", "GET")
            route = route_label(scope)
            store.http_request(method, route, status or HTTP_OUTCOME_ABORTED, elapsed)
            _log_access(method, route, scope.get("path", ""), status, elapsed, request_id)
            correlation.request_id.reset(token)


def _log_access(
    method: str, route: str, path: str, status: int | str, elapsed: float, request_id: str
) -> None:
    """One line per request, at a level that keeps the probes out of the way.

    A load balancer asking `/api/ready` every second and a browser fetching
    forty static files per page load would otherwise be most of the log;
    they are written at DEBUG, everything else at INFO.
    """
    quiet = route in PROBE_ROUTES or route == STATIC_ROUTE
    access_log.log(
        logging.DEBUG if quiet else logging.INFO,
        "%s %s -> %s in %.1fms",
        method,
        route,
        status or HTTP_OUTCOME_ABORTED,
        elapsed * 1000.0,
        extra={
            "request_id": request_id,
            "fields": {
                "method": method,
                "route": route,
                "path": path,
                "status": status or HTTP_OUTCOME_ABORTED,
                "ms": round(elapsed * 1000.0, 1),
            },
        },
    )
