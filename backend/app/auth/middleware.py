"""Session cookie plumbing for HTTP requests and Socket.IO handshakes."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.auth.bans import suspension_payload
from app.auth.sessions import COOKIE_NAME, SESSION_TTL, resolve_session_status

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


def set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    """Attach the session token as an HttpOnly cookie.

    HttpOnly keeps the token out of JavaScript entirely. SameSite=Strict keeps
    it off every cross-site request, navigations included; together with the
    origin check on unsafe requests and socket handshakes (#465,
    `app/origin_policy.py`) that is the CSRF policy, and no token is needed.
    A link into Sketchy from elsewhere loads the page without the cookie, and
    the page's own same-origin fetches carry it from then on.
    """
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        httponly=True,
        samesite="strict",
        secure=secure,
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

    async def dispatch(self, request: Request, call_next):
        raw_token = request.cookies.get(COOKIE_NAME, "")
        request.state.session_token = raw_token
        resolution = await resolve_session_status(self._session_factory, raw_token)
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
