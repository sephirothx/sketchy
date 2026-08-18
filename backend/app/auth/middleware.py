"""Authentication middleware for automatic guest provisioning and session management."""
from __future__ import annotations

import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.auth.jwt import JWT_COOKIE_NAME, JWT_EXPIRY_DAYS, create_token, decode_token
from app.repositories.interfaces import UserRepository

logger = logging.getLogger(__name__)

COOKIE_MAX_AGE = JWT_EXPIRY_DAYS * 24 * 60 * 60  # in seconds


def set_auth_cookie(response: Response, token: str) -> None:
    """Attach the JWT session cookie with secure HttpOnly defaults."""
    response.set_cookie(
        key=JWT_COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Clear the JWT session cookie."""
    response.delete_cookie(
        key=JWT_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware to authenticate users or auto-provision anonymous guest accounts."""

    def __init__(
        self,
        app,
        user_repo: UserRepository,
        jwt_secret_getter: Callable[[], str],
    ) -> None:
        super().__init__(app)
        self.user_repo = user_repo
        self.jwt_secret_getter = jwt_secret_getter

    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
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

        # If user is valid, attach to request state and proceed
        if user is not None:
            request.state.user = user
            request.state.user_id = user.id
            return await call_next(request)

        # Otherwise, auto-provision an anonymous guest account
        try:
            guest_user = await self.user_repo.create_anonymous(display_name="Guest")
            new_token = create_token(guest_user.id, jwt_secret)
            request.state.user = guest_user
            request.state.user_id = guest_user.id

            response = await call_next(request)
            set_auth_cookie(response, new_token)
            return response
        except Exception:
            logger.exception("Failed to auto-provision anonymous user in AuthMiddleware")
            request.state.user = None
            request.state.user_id = None
            return await call_next(request)
