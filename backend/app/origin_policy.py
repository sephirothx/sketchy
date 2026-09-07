"""Which origins may act as a signed-in browser (#465).

A browser attaches the session cookie to any request its rules allow, and
the rules allow more than this server ever meant: a page on any other
origin could open a WebSocket here carrying the victim's cookie and play as
them (WebSockets are not subject to CORS at all), and a form on any other
site could POST here with it. `SameSite=Lax` stops the second for
top-level navigations only. So the server decides for itself, once, what
origins are its own, and holds every socket handshake and every unsafe
request to that.

**The serving origin is always allowed**: the frontend is served by this
process, so a browser's `Origin` normally equals the scheme and host the
request arrived at. Behind a reverse proxy the scheme is what the proxy
saw, which uvicorn rewrites into the request only for a peer named in
`FORWARDED_ALLOW_IPS` (R-PLAT-10); the raw `X-Forwarded-Proto` header is
never read here, because anyone can send one. A frontend hosted elsewhere
is named in `ALLOWED_ORIGINS`, a comma-separated list of origins.

**A request with no `Origin` is not a browser's cross-site request.** Every
browser sends `Origin` on a WebSocket handshake and on every unsafe method,
same-origin included; what omits it is a non-browser client - curl, the
synthetic probe, the load harness - which cannot carry a victim's cookie
without the victim's help. Such a request is judged by `Referer` if there is
one, and admitted if there is neither. Safe methods are never judged: a
GET carries no state change, and the cookie's `SameSite=Strict` (§ cookie)
keeps it off cross-site navigations anyway.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

ALLOWED_ORIGINS_VARIABLE = "ALLOWED_ORIGINS"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def configured_origins(environment: dict[str, str] | None = None) -> frozenset[str]:
    """The extra origins named in `ALLOWED_ORIGINS`, normalized."""
    raw = (environment if environment is not None else os.environ).get(ALLOWED_ORIGINS_VARIABLE, "")
    origins = set()
    for entry in raw.split(","):
        origin = normalize_origin(entry)
        if origin:
            origins.add(origin)
    return frozenset(origins)


def normalize_origin(value: str | None) -> str | None:
    """`scheme://host[:port]`, lower-cased, or None for anything that is not one."""
    if not value:
        return None
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https", "ws", "wss"} or not parts.netloc:
        return None
    scheme = {"ws": "http", "wss": "https"}.get(parts.scheme, parts.scheme)
    return f"{scheme}://{parts.netloc.lower()}"


def serving_origin(scheme: str, host: str | None) -> str | None:
    """The origin a request arrived at, as the browser would name it."""
    if not host:
        return None
    return normalize_origin(f"{scheme}://{host}")


def origin_allowed(origin: str | None, *, scheme: str, host: str | None, extra: frozenset[str]) -> bool:
    """Whether a browser at `origin` may act here: the serving origin, or a
    configured one. A malformed origin is nobody's."""
    candidate = normalize_origin(origin)
    if candidate is None:
        return False
    own = serving_origin(scheme, host)
    return candidate == own or candidate in extra


def request_origin_allowed(
    *, method: str, origin: str | None, referer: str | None, scheme: str, host: str | None, extra: frozenset[str]
) -> bool:
    """The rule for one HTTP request: unsafe methods must come from an
    allowed origin when they say where they come from."""
    if method.upper() not in UNSAFE_METHODS:
        return True
    claimed = origin if origin else referer
    if not claimed or claimed.strip().lower() == "null":
        # No browser omits Origin on an unsafe request; `null` is a
        # sandboxed or opaque one, which is not this server's page either
        # way. An absent header is a non-browser client.
        return claimed is None or claimed == ""
    return origin_allowed(claimed, scheme=scheme, host=host, extra=extra)


class OriginPolicyMiddleware:
    """Refuse an unsafe HTTP request from an origin that is not this server's.

    Pure ASGI, ahead of the session lookup, so a foreign page's request is
    answered before its cookie is even resolved.
    """

    def __init__(self, app, *, extra: frozenset[str] | None = None) -> None:
        self.app = app
        self.extra = extra if extra is not None else configured_origins()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {name.decode("latin-1").lower(): value.decode("latin-1") for name, value in scope.get("headers", [])}
        allowed = request_origin_allowed(
            method=scope.get("method", "GET"),
            origin=headers.get("origin"),
            referer=headers.get("referer"),
            scheme=scope.get("scheme", "http"),
            host=headers.get("host"),
            extra=self.extra,
        )
        if allowed:
            await self.app(scope, receive, send)
            return
        body = b'{"detail":"This request did not come from Sketchy."}'
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})


def socket_origins(extra: frozenset[str] | None = None):
    """The callable Engine.IO consults for a handshake's `Origin`: called
    with the header's value and the request environ, it answers whether
    that origin may connect, and Engine.IO refuses the handshake with 400
    when it may not. Engine.IO consults it only when the header is present:
    a handshake with no `Origin` is a non-browser client, as above."""
    allowed_extra = extra if extra is not None else configured_origins()

    def allowed(origin, environ=None) -> bool:
        environ = environ or {}
        scheme = environ.get("wsgi.url_scheme", "http")
        host = environ.get("HTTP_HOST")
        if origin_allowed(origin, scheme=scheme, host=host, extra=allowed_extra):
            return True
        # Behind a proxy the deployment did not name in FORWARDED_ALLOW_IPS
        # the scope's scheme stays plain while the browser's Origin says
        # https; the host is still this server's, and that is what decides.
        return scheme == "http" and origin_allowed(origin, scheme="https", host=host, extra=allowed_extra)

    return allowed
