"""Opaque, hashed, server-side account session lifecycle."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from http.cookies import SimpleCookie
import secrets
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AuthSession, generate_uuid


COOKIE_NAME = "sketchy_session"
SESSION_TTL = timedelta(days=365)
ROTATE_AFTER = SESSION_TTL / 2
LAST_USED_WRITE_INTERVAL = timedelta(minutes=5)
TOKEN_BYTES = 32


@dataclass(frozen=True)
class SessionData:
    id: str
    user_id: str
    device_label: str
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class IssuedSession:
    token: str
    session: SessionData


def hash_session_token(token: str) -> str:
    """One-way digest for a high-entropy token; raw tokens never enter storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_token_from_cookie_header(cookie_header: str | None) -> str | None:
    """Extract the opaque token from an HTTP or Socket.IO cookie header."""
    if not cookie_header:
        return None
    jar = SimpleCookie()
    try:
        jar.load(cookie_header)
    except Exception:
        return None
    morsel = jar.get(COOKIE_NAME)
    return morsel.value if morsel and morsel.value else None


def device_label_from_user_agent(user_agent: str | None) -> str:
    """Derive a useful coarse label without storing a detailed fingerprint."""
    value = user_agent or ""
    if "Firefox/" in value:
        browser = "Firefox"
    elif "Edg/" in value:
        browser = "Edge"
    elif "Chrome/" in value or "CriOS/" in value:
        browser = "Chrome"
    elif "Safari/" in value:
        browser = "Safari"
    else:
        browser = "Browser"

    if "Android" in value:
        platform = "Android"
    elif "iPhone" in value or "iPad" in value:
        platform = "iOS"
    elif "Windows" in value:
        platform = "Windows"
    elif "Macintosh" in value:
        platform = "macOS"
    elif "Linux" in value:
        platform = "Linux"
    else:
        platform = "unknown device"
    return f"{browser} on {platform}"


def _session_data(record: AuthSession) -> SessionData:
    return SessionData(
        id=str(record.id),
        user_id=str(record.user_id),
        device_label=record.device_label,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        expires_at=record.expires_at,
    )


async def create_session(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    device_label: str,
    rotated_from_id: str | None = None,
    now: datetime | None = None,
) -> IssuedSession:
    issued_at = now or datetime.now(timezone.utc)
    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    record = AuthSession(
        id=generate_uuid(),
        user_id=UUID(user_id),
        token_hash=hash_session_token(raw_token),
        device_label=device_label[:64],
        rotated_from_id=UUID(rotated_from_id) if rotated_from_id else None,
        created_at=issued_at,
        last_used_at=issued_at,
        expires_at=issued_at + SESSION_TTL,
    )
    async with session_factory() as database:
        async with database.begin():
            database.add(record)
    return IssuedSession(token=raw_token, session=_session_data(record))


async def resolve_session(
    session_factory: async_sessionmaker[AsyncSession],
    token: str | None,
    *,
    now: datetime | None = None,
) -> SessionData | None:
    if not token:
        return None
    checked_at = now or datetime.now(timezone.utc)
    digest = hash_session_token(token)
    async with session_factory() as database:
        async with database.begin():
            record = await database.scalar(
                select(AuthSession).where(AuthSession.token_hash == digest)
            )
            if (
                record is None
                or record.revoked_at is not None
                or record.expires_at <= checked_at
            ):
                return None
            if checked_at - record.last_used_at >= LAST_USED_WRITE_INTERVAL:
                record.last_used_at = checked_at
        return _session_data(record)


def should_rotate(session: SessionData, *, now: datetime | None = None) -> bool:
    checked_at = now or datetime.now(timezone.utc)
    return checked_at - session.created_at >= ROTATE_AFTER


async def rotate_session(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    session_id: str,
    user_id: str,
    device_label: str,
    now: datetime | None = None,
) -> IssuedSession | None:
    rotated_at = now or datetime.now(timezone.utc)
    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    successor = AuthSession(
        id=generate_uuid(),
        user_id=UUID(user_id),
        token_hash=hash_session_token(raw_token),
        device_label=device_label[:64],
        rotated_from_id=UUID(session_id),
        created_at=rotated_at,
        last_used_at=rotated_at,
        expires_at=rotated_at + SESSION_TTL,
    )
    async with session_factory() as database:
        async with database.begin():
            revoked = await database.execute(
                update(AuthSession)
                .where(
                    AuthSession.id == UUID(session_id),
                    AuthSession.user_id == UUID(user_id),
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > rotated_at,
                )
                .values(revoked_at=rotated_at)
            )
            if revoked.rowcount != 1:
                return None
            database.add(successor)
    return IssuedSession(token=raw_token, session=_session_data(successor))


async def revoke_session(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    session_id: str,
    user_id: str,
    now: datetime | None = None,
) -> bool:
    try:
        db_session_id = UUID(session_id)
        db_user_id = UUID(user_id)
    except (ValueError, TypeError, AttributeError):
        return False
    async with session_factory() as database:
        async with database.begin():
            result = await database.execute(
                update(AuthSession)
                .where(
                    AuthSession.id == db_session_id,
                    AuthSession.user_id == db_user_id,
                    AuthSession.revoked_at.is_(None),
                )
                .values(revoked_at=now or datetime.now(timezone.utc))
            )
            return result.rowcount == 1


async def revoke_all_sessions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    now: datetime | None = None,
) -> int:
    async with session_factory() as database:
        async with database.begin():
            result = await database.execute(
                update(AuthSession)
                .where(
                    AuthSession.user_id == UUID(user_id),
                    AuthSession.revoked_at.is_(None),
                )
                .values(revoked_at=now or datetime.now(timezone.utc))
            )
            return int(result.rowcount or 0)


async def list_active_sessions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    now: datetime | None = None,
) -> list[SessionData]:
    checked_at = now or datetime.now(timezone.utc)
    async with session_factory() as database:
        records = (
            await database.scalars(
                select(AuthSession)
                .where(
                    AuthSession.user_id == UUID(user_id),
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > checked_at,
                )
                .order_by(AuthSession.last_used_at.desc())
            )
        ).all()
        return [_session_data(record) for record in records]
