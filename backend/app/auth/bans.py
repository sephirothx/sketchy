"""Shared active-ban queries for HTTP, Socket.IO, login, and moderation."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import UserBan


def active_ban_filter(now: datetime):
    return (
        UserBan.is_active.is_(True),
        or_(UserBan.expires_at.is_(None), UserBan.expires_at > now),
    )


async def active_ban_for_user(
    session: AsyncSession, user_id: UUID, *, now: datetime | None = None
) -> UserBan | None:
    checked_at = now or datetime.now(timezone.utc)
    return await session.scalar(
        select(UserBan)
        .where(UserBan.user_id == user_id, *active_ban_filter(checked_at))
        .order_by(UserBan.created_at.desc())
        .limit(1)
    )


async def is_user_banned(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: str,
    *,
    now: datetime | None = None,
) -> bool:
    try:
        db_user_id = UUID(user_id)
    except (ValueError, TypeError, AttributeError):
        return False
    async with session_factory() as session:
        return await active_ban_for_user(session, db_user_id, now=now) is not None
