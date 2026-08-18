"""Authentication middleware for session cookies and guest provisioning."""
from __future__ import annotations

import logging
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.auth.jwt import JWT_COOKIE_NAME, JWT_EXPIRY_DAYS, create_token, decode_token
from app.repositories.interfaces import UserRepository

logger = logging.getLogger(__name__)

COOKIE_MAX_AGE = JWT_EXPIRY_DAYS * 24 * 60 * 60
PROVISION_PATH = "/api/auth/me"


def set_auth_cookie(response: Response, token: str, *, secure: bool = False) -> None:
    """Attach the JWT session cookie with HttpOnly defaults."""
    response.set_cookie(
        key=JWT_COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
        secure=secure,
    )


def clear_auth_cookie(response: Response) -> None:
    """Clear the JWT session cookie."""
    response.delete_cookie(
        key=JWT_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
    )


def cookie_should_be_secure(request: Request) -> bool:
    return request.url.scheme == "https"


class AuthMiddleware(BaseHTTPMiddleware):
    """Attach the current user from the session cookie; provision guests on GET /api/auth/me."""

    def __init__(
        self,
        app,
        user_repo: UserRepository,
        jwt_secret_getter: Callable[[], str],
    ) -> None:
        super().__init__(app)
        self.user_repo = user_repo
        self.jwt_secret_getter = jwt_secret_getter

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        jwt_secret = self.jwt_secret_getter()
        token = request.cookies.get(JWT_COOKIE_NAME)
        user_id: str | None = None

        if token and jwt_secret:
            user_id = decode_token(token, jwt_secret)

        user = None
        if user_id:
            try:
                user = await self.user_repo.get_by_id(user_id)
            except Exception:
                logger.exception("Error looking up user '%s' in AuthMiddleware", user_id)

        if user is not None:
            request.state.user = user
            request.state.user_id = user.id
            return await call_next(request)

        request.state.user = None
        request.state.user_id = None

        should_provision = (
            request.method == "GET"
            and request.url.path.rstrip("/") == PROVISION_PATH.rstrip("/")
            and bool(jwt_secret)
        )
        if not should_provision:
            return await call_next(request)

        try:
            guest_user = await self.user_repo.create_anonymous(display_name="Guest")
            new_token = create_token(guest_user.id, jwt_secret)
            request.state.user = guest_user
            request.state.user_id = guest_user.id
            response = await call_next(request)
            set_auth_cookie(response, new_token, secure=cookie_should_be_secure(request))
            return response
        except Exception:
            logger.exception("Failed to auto-provision anonymous user in AuthMiddleware")
            request.state.user = None
            request.state.user_id = None
            return await call_next(request)
