"""Signing key management and JWT encode/decode for session cookies."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AppConfig

ALGORITHM = "HS256"
SECRET_CONFIG_KEY = "jwt_secret"
COOKIE_NAME = "sketchy_session"

# A guest's identity - and therefore their stats - lives entirely in this token,
# so it has to outlast a casual break from the game. The cookie is refreshed
# whenever the client checks in, so an active player never reaches the deadline.
TOKEN_TTL = timedelta(days=365)
# Re-issue once past the halfway mark rather than on every request, so a busy
# session is not constantly minting tokens.
REFRESH_AFTER = TOKEN_TTL / 2

_cached_secret: str | None = None


def reset_secret_cache() -> None:
    """Drop the process-wide secret cache (tests use this between databases)."""
    global _cached_secret
    _cached_secret = None


async def get_or_create_secret(
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    """Return the signing key, generating and storing one on first use.

    ``JWT_SECRET`` wins when set, which is what multi-replica deployments need:
    every process must sign with the same key, and the key must survive the
    database being rebuilt. Otherwise the key is generated once and kept in
    ``app_config`` so a default single-node install needs no configuration.
    """
    global _cached_secret
    if _cached_secret:
        return _cached_secret

    from_env = os.environ.get("JWT_SECRET", "").strip()
    if from_env:
        _cached_secret = from_env
        return _cached_secret

    async with session_factory() as session:
        async with session.begin():
            stmt = select(AppConfig).where(AppConfig.key == SECRET_CONFIG_KEY)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                # Two workers can reach this concurrently on first boot. The
                # primary key makes the loser's insert fail rather than letting
                # it overwrite the winner's key and invalidate live sessions.
                row = AppConfig(key=SECRET_CONFIG_KEY, value=secrets.token_urlsafe(64))
                session.add(row)
                try:
                    await session.flush()
                except Exception:
                    await session.rollback()
                    async with session.begin():
                        retry = select(AppConfig).where(
                            AppConfig.key == SECRET_CONFIG_KEY
                        )
                        row = (await session.execute(retry)).scalar_one()
            value = row.value

    _cached_secret = value
    return value


def create_token(user_id: str, secret: str) -> str:
    """Mint a session token carrying nothing but the user id and its lifetime.

    Deliberately no username or is_anonymous claim: a guest who registers or a
    player who logs in must take effect immediately, and that only holds if
    every read of those fields goes to the database rather than the token.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + TOKEN_TTL).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> str | None:
    """Return the user id from a valid token, or ``None`` if it is unusable."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) and subject else None


def should_refresh(token: str, secret: str) -> bool:
    """True when a still-valid token is old enough to be worth re-issuing."""
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        return False
    issued_at = payload.get("iat")
    if not isinstance(issued_at, (int, float)):
        return True
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(issued_at, timezone.utc)
    return age >= REFRESH_AFTER
