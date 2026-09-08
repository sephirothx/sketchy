"""Session cookie plumbing for HTTP requests and Socket.IO handshakes."""
from __future__ import annotations

import hashlib
import hmac

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

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


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """Resolve the caller's user id from the session cookie.

    Only ever reads. Guest accounts are provisioned exclusively by
    ``GET /api/auth/me`` so that ordinary traffic - health checks, the lobby
    room-list poll - cannot create rows.
    """

    def __init__(self, app, session_factory: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(app)
        self._session_factory = session_factory
        # The deployment's HMAC key, read once and then held. Without the
        # cache this would be a database round trip per request purely to
        # hash an address that is only ever compared with another hash.
        self._ip_secret: str | None = None

    async def _caller_ip_hash(self, request: Request) -> str | None:
        """Who is calling, as a digest. Never the address itself (R-PRIV-09)."""
        try:
            self._ip_secret = await get_ip_hash_secret(
                self._session_factory, cached=self._ip_secret
            )
        except Exception:
            # A signal, not a gate. If the key cannot be established the
            # request still proceeds; the anomaly is simply not recorded.
            return None
        return hmac.new(
            self._ip_secret.encode("utf-8"),
            client_key(request).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def dispatch(self, request: Request, call_next):
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
            # The drawing the suspension notice is about: the refusal below
            # names it, and this is the one path that can hand it over.
            or request.url.path == "/api/suspension/drawing"
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
        auth_session = resolution.session
        request.state.auth_session = auth_session
        request.state.session_id = auth_session.id if auth_session else None
        request.state.user_id = auth_session.user_id if auth_session else None
        request.state.banned_user_id = resolution.banned_user_id
        return await call_next(request)
