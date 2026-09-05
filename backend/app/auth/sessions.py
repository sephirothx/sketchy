"""Opaque, hashed, server-side account session lifecycle."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from http.cookies import SimpleCookie
import secrets
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AuthSession, UserBan, generate_uuid


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


@dataclass(frozen=True)
class SessionResolution:
    session: SessionData | None
    banned_user_id: str | None = None


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
    return (
        await resolve_session_status(session_factory, token, now=now)
    ).session


async def resolve_session_status(
    session_factory: async_sessionmaker[AsyncSession],
    token: str | None,
    *,
    now: datetime | None = None,
) -> SessionResolution:
    """Resolve a token and retain the reason an active ban rejected it.

    Revoked ban-time tokens must remain recognizable until the ban expires;
    otherwise the next request would look like a cookieless visitor and could
    provision a replacement guest account. The raw token still never leaves
    this boundary or enters storage.
    """
    if not token:
        return SessionResolution(session=None)
    checked_at = now or datetime.now(timezone.utc)
    digest = hash_session_token(token)
    async with session_factory() as database:
        async with database.begin():
            active_ban_created_at = (
                select(UserBan.created_at)
                .where(
                    UserBan.user_id == AuthSession.user_id,
                    UserBan.is_active.is_(True),
                    or_(
                        UserBan.expires_at.is_(None),
                        UserBan.expires_at > checked_at,
                    ),
                )
                .order_by(UserBan.created_at.desc())
                .limit(1)
                .correlate(AuthSession)
                .scalar_subquery()
            )
            result = (
                await database.execute(
                    select(
                        AuthSession,
                        active_ban_created_at.label("banned_at"),
                    ).where(AuthSession.token_hash == digest)
                )
            ).one_or_none()
            if result is None:
                return SessionResolution(session=None)
            record, banned_at = result
            if banned_at is not None:
                # A token that was valid when the ban landed remains usable
                # only for the narrow export/delete escape hatch selected by
                # HTTP middleware. A token revoked before the ban cannot be
                # resurrected as a privacy credential.
                was_active_when_banned = (
                    record.expires_at > banned_at
                    and (
                        record.revoked_at is None
                        or record.revoked_at >= banned_at
                    )
                )
                return SessionResolution(
                    session=(
                        _session_data(record) if was_active_when_banned else None
                    ),
                    banned_user_id=str(record.user_id),
                )
            if record.revoked_at is not None or record.expires_at <= checked_at:
                return SessionResolution(session=None)
            if checked_at - record.last_used_at >= LAST_USED_WRITE_INTERVAL:
                record.last_used_at = checked_at
        return SessionResolution(session=_session_data(record))


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


async def revoke_sessions(
    database: AsyncSession,
    *,
    user_id: str | UUID,
    now: datetime | None = None,
) -> int:
    """Revoke every live session of an account inside the caller's transaction.

    A password reset or change wants this to commit with the new credential,
    or not at all: a crash between the two would leave a committed password
    and every old device still signed in (#607), which is the one outcome
    R-AUTH-10 exists to rule out.
    """
    result = await database.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == UUID(str(user_id)),
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now or datetime.now(timezone.utc))
    )
    return int(result.rowcount or 0)


async def revoke_all_sessions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    now: datetime | None = None,
) -> int:
    """`revoke_sessions` in a transaction of its own, for callers that have none."""
    async with session_factory() as database:
        async with database.begin():
            return await revoke_sessions(database, user_id=user_id, now=now)


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
