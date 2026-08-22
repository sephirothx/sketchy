"""Session cookie plumbing for HTTP requests and Socket.IO handshakes."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.auth.sessions import COOKIE_NAME, SESSION_TTL, resolve_session

COOKIE_MAX_AGE = int(SESSION_TTL.total_seconds())


def is_secure_request(request: Request) -> bool:
    """Whether the browser reached us over HTTPS.

    A tunnel or reverse proxy terminates TLS and forwards plain HTTP, so the
    request scheme alone would under-report and the forwarded header is the
    only signal that the user's connection was encrypted.
    """
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if forwarded_proto:
        return forwarded_proto.split(",")[0].strip().lower() == "https"
    return request.url.scheme == "https"


def set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    """Attach the session token as an HttpOnly cookie.

    HttpOnly keeps the token out of JavaScript entirely. SameSite=Lax is
    sufficient against cross-site POSTs because the frontend is served from the
    same origin as the API, which also means no CSRF token is required.
    """
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        httponly=True,
        samesite="lax",
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
        auth_session = await resolve_session(self._session_factory, raw_token)
        request.state.auth_session = auth_session
        request.state.session_id = auth_session.id if auth_session else None
        request.state.user_id = auth_session.user_id if auth_session else None
        return await call_next(request)
