"""Browser hardening headers, and the rule that production is HTTPS only (#467).

Two pure ASGI middlewares wrap the outermost application - the Socket.IO
mount included, so a polling response and a static file are held to the
same rules as a REST one.

**Every response carries the browser headers**, in every environment. A
Content-Security-Policy that only production sends is one the E2E suite
never exercises, and the day it blocks a stylesheet is the day of the deploy.
So the policy is the same everywhere and the built page is tested under it;
what differs by environment is only what depends on TLS.

The policy itself follows from what the page is: one same-origin bundle. The
inline script in `index.html` (the pre-paint theme read) is admitted by hash,
computed from the built file at startup, so a change to it is picked up by a
rebuild rather than by anyone remembering to. Images may be `data:` and
`blob:` because Vite inlines small assets and the picture and screenshot
dialogs preview an object URL, and fonts may be `data:` because the built
stylesheet carries the two typefaces inline; nothing else leaves `'self'`. A WebSocket is
named explicitly beside `'self'` in `connect-src` because a browser predating
CSP Level 3 does not read `'self'` as covering `wss:`.

**Production refuses to speak plain HTTP** except to the process-local probes
(`/api/health`, `/api/ready`, `/metrics`), which an orchestrator reaches
directly. Everything else arriving without TLS is sent to the canonical
origin in `PUBLIC_BASE_URL` with a 308, and a plain WebSocket handshake is
closed. The scheme judged is the one uvicorn established (R-PLAT-10): behind
a TLS-terminating proxy that is not named in `FORWARDED_ALLOW_IPS`, every
request looks plain and the redirect loops - loudly, on the first page load,
rather than issuing a session cookie a plain hop could read. `Strict-Transport-
Security` rides every production response for the same reason: a browser
that has seen it once never tries plain HTTP again.
"""
from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlsplit

# Paths a deployment's own machinery reaches over plain HTTP on the process's
# port: a container health check, a readiness probe, a metrics scrape. None
# is a page, none carries the session cookie, and each has its own guard.
HTTPS_EXEMPT_PATHS = frozenset({"/api/health", "/api/ready", "/metrics"})

# A year, the floor for preload eligibility and long enough that a browser
# which saw one production response keeps the rule across a deploy gap.
HSTS_MAX_AGE_SECONDS = 31536000

_INLINE_SCRIPT = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.DOTALL | re.IGNORECASE)
_SRC_ATTRIBUTE = re.compile(r"\bsrc\s*=", re.IGNORECASE)
# What may be reflected into a CSP source from a Host header: a name, an
# address (bracketed for IPv6), a port. Anything else is left out rather
# than written into a header.
_HOST_SHAPE = re.compile(r"^[A-Za-z0-9.\-\[\]:]+$")


def inline_script_hashes(index_html: Path) -> tuple[str, ...]:
    """The CSP hash source of every inline `<script>` in the built shell.

    A browser hashes the script element's text exactly as it appears between
    the tags, so no whitespace is normalized here. A missing shell (a checkout
    without a build, the dev server serving the page instead) has no inline
    script to admit.
    """
    try:
        text = index_html.read_text(encoding="utf-8")
    except OSError:
        return ()
    hashes = []
    for match in _INLINE_SCRIPT.finditer(text):
        if _SRC_ATTRIBUTE.search(match.group("attrs")):
            continue
        digest = hashlib.sha256(match.group("body").encode("utf-8")).digest()
        hashes.append(f"'sha256-{base64.b64encode(digest).decode('ascii')}'")
    return tuple(hashes)


@dataclass(frozen=True)
class HeaderPolicy:
    """What this deployment sends, decided once at startup."""

    script_hashes: tuple[str, ...] = ()
    # Only on a deployment that is HTTPS by construction (production). A
    # browser remembers HSTS for the host, so a development server that sent
    # it would make http://localhost unreachable for a year.
    strict_transport_security: bool = False
    # A frontend on another origin (ALLOWED_ORIGINS) loads this server's
    # images as no-cors subresources, which a same-origin resource policy
    # would refuse. Nobody else has a reason to embed them.
    cross_origin_resources: bool = False

    def content_security_policy(self, *, host: str | None) -> str:
        scripts = " ".join(("'self'", *self.script_hashes))
        sockets = ""
        if host and _HOST_SHAPE.match(host):
            sockets = f" wss://{host} ws://{host}"
        return "; ".join(
            (
                "default-src 'self'",
                f"script-src {scripts}",
                "style-src 'self'",
                "img-src 'self' data: blob:",
                "font-src 'self' data:",
                f"connect-src 'self'{sockets}",
                "manifest-src 'self'",
                "media-src 'self'",
                "worker-src 'self'",
                "object-src 'none'",
                "base-uri 'none'",
                "form-action 'self'",
                "frame-ancestors 'none'",
                "frame-src 'none'",
            )
        )

    def headers(self, *, host: str | None) -> list[tuple[bytes, bytes]]:
        pairs = [
            (b"content-security-policy", self.content_security_policy(host=host).encode("ascii")),
            (b"x-content-type-options", b"nosniff"),
            # Belt to frame-ancestors' braces, for a browser old enough to
            # read only this one.
            (b"x-frame-options", b"DENY"),
            # A referrer never leaves the site: a room code in a URL is an
            # invitation, and a link out of a room should not carry it.
            # Same-origin requests keep theirs, which the origin policy's
            # Referer fallback relies on.
            (b"referrer-policy", b"same-origin"),
            (
                b"permissions-policy",
                b"accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
                b"magnetometer=(), microphone=(), payment=(), usb=()",
            ),
            (b"cross-origin-opener-policy", b"same-origin"),
            (
                b"cross-origin-resource-policy",
                b"cross-origin" if self.cross_origin_resources else b"same-origin",
            ),
        ]
        if self.strict_transport_security:
            pairs.append(
                (
                    b"strict-transport-security",
                    f"max-age={HSTS_MAX_AGE_SECONDS}; includeSubDomains".encode("ascii"),
                )
            )
        return pairs


def _header(scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


class SecurityHeadersMiddleware:
    """Add the browser headers to every HTTP response that lacks them.

    A header the application already set wins, so a route that needs a
    different policy for one response can say so; none does today.
    """

    def __init__(self, app, *, policy: HeaderPolicy) -> None:
        self.app = app
        self.policy = policy

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        host = _header(scope, b"host")

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                headers.extend(pair for pair in self.policy.headers(host=host) if pair[0] not in present)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


@dataclass(frozen=True)
class HttpsOnly:
    """The production rule: plain HTTP is answered with the way to HTTPS."""

    enabled: bool
    public_origin: str
    exempt_paths: frozenset[str] = field(default_factory=lambda: HTTPS_EXEMPT_PATHS)

    def applies(self, scope) -> bool:
        if not self.enabled or scope["type"] not in ("http", "websocket"):
            return False
        if scope.get("scheme", "http") in ("https", "wss"):
            return False
        return scope.get("path", "/") not in self.exempt_paths

    def location(self, scope) -> str:
        # The raw path is still percent-encoded, which is what a Location
        # header wants; the decoded one is quoted back only in its absence.
        raw_path = scope.get("raw_path")
        path = raw_path.decode("latin-1") if raw_path else quote(scope.get("path", "/"))
        target = self.public_origin + path
        query = scope.get("query_string", b"")
        if query:
            target += "?" + query.decode("latin-1")
        return target


class HttpsOnlyMiddleware:
    """Refuse to serve a page, an API call or a socket over plain HTTP.

    A request is redirected with **308**, which keeps its method: a browser
    that reaches the plain port with a POST resends it over TLS rather than
    turning it into a GET. A plain WebSocket handshake is closed before it is
    accepted, which uvicorn reports as 403.
    """

    def __init__(self, app, *, rule: HttpsOnly) -> None:
        self.app = app
        self.rule = rule

    async def __call__(self, scope, receive, send) -> None:
        if not self.rule.applies(scope):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close"})
            return
        location = self.rule.location(scope).encode("ascii", "strict")
        await send(
            {
                "type": "http.response.start",
                "status": 308,
                "headers": [(b"location", location), (b"content-length", b"0")],
            }
        )
        await send({"type": "http.response.body", "body": b""})


def public_origin(public_base_url: str) -> str:
    """`scheme://host[:port]` of the canonical public URL, for a redirect."""
    parts = urlsplit(public_base_url)
    return f"{parts.scheme}://{parts.netloc}"
