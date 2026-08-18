"""JWT creation, decoding, and persistent secret management."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import secrets
from typing import Any

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AppConfig

logger = logging.getLogger(__name__)

JWT_SECRET_CONFIG_KEY = "jwt_secret"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 30
JWT_COOKIE_NAME = "sketchy_session"

_cached_jwt_secret: str | None = None


async def get_or_create_secret(session_factory: async_sessionmaker[AsyncSession]) -> str:
    """Retrieve or generate and persist the application JWT signing secret."""
    global _cached_jwt_secret
    if _cached_jwt_secret is not None:
        return _cached_jwt_secret

    async with session_factory() as session:
        stmt = select(AppConfig).where(AppConfig.key == JWT_SECRET_CONFIG_KEY)
        result = await session.execute(stmt)
        config = result.scalar_one_or_none()

        if config is not None:
            _cached_jwt_secret = config.value
            return _cached_jwt_secret

        new_secret = secrets.token_hex(32)
        session.add(AppConfig(key=JWT_SECRET_CONFIG_KEY, value=new_secret))
        await session.commit()

        _cached_jwt_secret = new_secret
        logger.info("Generated and stored new application JWT secret")
        return _cached_jwt_secret


def set_cached_secret(secret: str) -> None:
    """Explicitly set the in-memory JWT secret (useful for testing)."""
    global _cached_jwt_secret
    _cached_jwt_secret = secret


def create_token(
    user_id: str,
    secret: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT for a given user ID."""
    now = datetime.now(timezone.utc)
    delta = expires_delta if expires_delta is not None else timedelta(days=JWT_EXPIRY_DAYS)
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + delta).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_token(token: str, secret: str) -> str | None:
    """Decode and validate a JWT, returning the user ID (sub) or None if invalid/expired."""
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
        return str(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    except Exception:
        logger.exception("Unexpected error decoding JWT token")
        return None
