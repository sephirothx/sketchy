"""Shared active-ban queries for HTTP, Socket.IO, login, and moderation."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import UserBan
from app.services.player_reports import cited_notice_messages, notice_drawings


def active_ban_filter(now: datetime):
    # The one definition of an active suspension: not revoked, not past its
    # expiry (#553). Every reader takes it from here.
    return (
        UserBan.revoked_at.is_(None),
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


async def suspension_payload(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: str,
    *,
    now: datetime | None = None,
) -> dict:
    """What a suspended account is told about its own suspension.

    Shared by the HTTP refusal and the socket eviction so the two cannot drift
    into telling somebody different things about the same ban.
    """
    body: dict = {
        "detail": "This account is suspended.",
        "suspended": True,
        "reason": None,
        "category": None,
        "expiresAt": None,
    }
    try:
        target = UUID(user_id)
    except ValueError:
        return body
    async with session_factory() as session:
        ban = await active_ban_for_user(session, target, now=now)
    if ban is None:
        return body
    body["reason"] = ban.reason
    body["category"] = ban.category
    body["expiresAt"] = ban.expires_at.isoformat() if ban.expires_at else None
    async with session_factory() as session:
        # Their own words, and their own work: every cited line and every
        # canvas the decision behind this suspension covered, not only the
        # one report it names (#620). Metadata here; the bytes over
        # `GET /api/suspension/drawings/{report_id}`, which the ban-time
        # credential may reach.
        body["messages"] = await cited_notice_messages(session, ban.source_report_id)
        body["drawings"] = await notice_drawings(session, ban.source_report_id)
    return body
