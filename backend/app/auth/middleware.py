"""Session cookie plumbing for HTTP requests and Socket.IO handshakes."""
from __future__ import annotations

import asyncio
import hashlib
import hmac

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth.bans import suspension_payload
from app.auth.rate_limit import client_key, get_ip_hash_secret
from app.auth.sessions import (
    SESSION_TTL,
    cookie_name,
    device_label_from_user_agent,
    resolve_session_status,
)
from app.deployment import is_production

COOKIE_MAX_AGE = int(SESSION_TTL.total_seconds())


def is_secure_request(request: Request) -> bool:
    """Whether the browser reached us over HTTPS.

    A tunnel or reverse proxy terminates TLS and forwards plain HTTP, so the
    request's own scheme would under-report - but the forwarded header is
    read only for a proxy the deployment trusts: uvicorn rewrites the scope's
    scheme from `X-Forwarded-Proto` when the peer is in `FORWARDED_ALLOW_IPS`
    (R-PLAT-10), and anyone else's header is ignored. Reading the raw header
    here used to let any client claim HTTPS and steer the cookie's `Secure`
    flag (#465).
    """
    return request.scope.get("scheme") in ("https", "wss")


def cookie_is_secure(secure: bool) -> bool:
    """`Secure` as the cookie will carry it: what the request established,
    or unconditionally in production (#467).

    Production is HTTPS by construction - startup refuses any other
    `PUBLIC_BASE_URL`, and a plain request is redirected before it reaches
    a route - so a production request that still looks plain is one behind
    a proxy the deployment did not name in `FORWARDED_ALLOW_IPS`. Issuing a
    year-long cookie without `Secure` there would be the one outcome worse
    than the redirect loop that misconfiguration otherwise produces: a
    cookie the browser would send over plain HTTP if it were ever asked to.
    The `__Host-` name makes the same demand from the other side.
    """
    return secure or is_production()


def set_session_cookie(
    response: Response,
    token: str,
    *,
    secure: bool,
    max_age: int | None = None,
) -> None:
    """Attach the session token as an HttpOnly cookie.

    HttpOnly keeps the token out of JavaScript entirely. SameSite=Strict keeps
    it off every cross-site request, navigations included; together with the
    origin check on unsafe requests and socket handshakes (#465,
    `app/origin_policy.py`) that is the CSRF policy, and no token is needed.
    A link into Sketchy from elsewhere loads the page without the cookie, and
    the page's own same-origin fetches carry it from then on. `Path=/` and no
    `Domain` are what the production `__Host-` name requires.
    """
    response.set_cookie(
        cookie_name(),
        token,
        # The cookie is told the session's own life, not a fixed year: a staff
        # session lasts a week (#468), and a cookie outliving the record it
        # names is a browser sending a credential the server will only reject.
        max_age=max_age if max_age is not None else COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=cookie_is_secure(secure),
        path="/",
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        cookie_name(),
        httponly=True,
        samesite="strict",
        secure=cookie_is_secure(secure),
        path="/",
    )


#: Where a session means anything. Everything else this app answers - the
#: application shell, its assets, `/metrics` with its bearer token - is the
#: same for every caller.
SESSION_PATH_PREFIX = "/api/"


class SessionAuthMiddleware:
    """Resolve the caller's user id from the session cookie.

    Only ever reads. Guest accounts are provisioned exclusively by
    ``GET /api/auth/me`` so that ordinary traffic - health checks, the lobby
    room-list poll - cannot create rows.

    Only for `/api/` (#974). The cookie is `Path=/`, so the browser sends it
    with the shell, the bundle, every font and icon: a cold page load resolved
    the session a dozen times for files that are the same for everybody. Any
    other path gets the state of a caller with no session, without asking.

    Plain ASGI rather than `BaseHTTPMiddleware` (#974), which runs the rest of
    the app in a task of its own behind a memory stream: ~80 µs of event-loop
    time on every request, measured through this app, on the loop every room
    shares.
    """

    def __init__(self, app: ASGIApp, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.app = app
        self._session_factory = session_factory
        # The deployment's HMAC key, read once and then held. Without the
        # cache this would be a database round trip per request purely to
        # hash an address that is only ever compared with another hash.
        self._ip_secret: str | None = None
        # And read once *in total*, not once per request in flight. A cold
        # server has no key row yet, and this runs on every `/api/` request: the
        # first page load is a dozen of them at once, each finding nothing
        # cached, each trying to insert the same row, each losing on the
        # unique key and retrying. That pile-up lands precisely when the first
        # page is loading, which is where it was seen (#468). One caller
        # establishes it; the rest wait on the lock and find it done.
        self._ip_secret_lock = asyncio.Lock()

    async def _caller_ip_hash(self, request: Request) -> str | None:
        """Who is calling, as a digest. Never the address itself (R-PRIV-09)."""
        secret = self._ip_secret
        if secret is None:
            async with self._ip_secret_lock:
                # Checked again inside the lock: whoever held it before this
                # caller has almost certainly just established it.
                if self._ip_secret is None:
                    try:
                        self._ip_secret = await get_ip_hash_secret(
                            self._session_factory
                        )
                    except Exception:
                        # A signal, not a gate. If the key cannot be
                        # established the request still proceeds; the anomaly
                        # is simply not recorded.
                        return None
                secret = self._ip_secret
        return hmac.new(
            secret.encode("utf-8"),
            client_key(request).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Read off the scope rather than built into a `Request` first: the
        # gate runs on every request including static files, and parsing a URL
        # to answer it costs more than the answer (#974 review).
        if not scope["path"].startswith(SESSION_PATH_PREFIX):
            _set_state(Request(scope), token="", ip_hash=None, session=None, banned_user_id=None)
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        refusal = await self._resolve(request)
        if refusal is not None:
            await refusal(scope, receive, send)
            return
        await self.app(scope, receive, send)

    async def _resolve(self, request: Request) -> Response | None:
        """Fill the request's session state; a refusal to send instead, if any."""
        raw_token = request.cookies.get(cookie_name(), "")
        request.state.session_token = raw_token
        # Computed once here and left on the request, for every route that
        # wants it. Issuing a cookie needs the caller's address digest too,
        # and reaching for it separately meant a database round trip per
        # sign-in and per guest provisioned - which on SQLite is a write
        # transaction taken on the one path an unauthenticated flood already
        # hits hardest. The secret is cached on this middleware, so having it
        # here costs an HMAC.
        request.state.client_ip_hash = await self._caller_ip_hash(request)
        resolution = await resolve_session_status(
            self._session_factory,
            raw_token,
            ip_hash=request.state.client_ip_hash if raw_token else None,
            device_label=device_label_from_user_agent(
                request.headers.get("user-agent")
            ),
        )
        privacy_escape_hatch = (
            request.url.path.startswith("/api/auth/data-exports")
            or request.url.path == "/api/auth/account"
            or request.url.path == "/api/auth/logout"
            # The drawings the suspension notice is about: the refusal below
            # names them, and this is the one path that can hand them over.
            # One per report the decision covered (#620), so the path names
            # which; the route checks it against that decision group.
            or request.url.path.startswith("/api/suspension/drawings/")
        )
        if (
            resolution.banned_user_id is not None
            and request.url.path.startswith("/api/")
            and request.url.path != "/api/health"
            and not privacy_escape_hatch
        ):
            # Say why, and until when. A player told only that they are
            # suspended has been told the one thing they already worked out
            # from being unable to do anything. The extra lookup happens on
            # this path alone, which a suspended account reaches and nobody
            # else does.
            return JSONResponse(
                await suspension_payload(
                    self._session_factory, resolution.banned_user_id
                ),
                status_code=403,
            )
        _set_state(
            request,
            token=raw_token,
            ip_hash=request.state.client_ip_hash,
            session=resolution.session,
            banned_user_id=resolution.banned_user_id,
        )
        return None


def _set_state(request: Request, *, token: str, ip_hash: str | None, session, banned_user_id) -> None:
    """What every route reads off the request about its caller."""
    request.state.session_token = token
    request.state.client_ip_hash = ip_hash
    request.state.auth_session = session
    request.state.session_id = session.id if session else None
    request.state.user_id = session.user_id if session else None
    request.state.banned_user_id = banned_user_id
