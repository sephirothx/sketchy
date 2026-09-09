"""What a warned account is told, and how the app finds out.

A warning arrives by two routes and they must say the same thing: the socket
tells a player who is online the moment a moderator issues it, and
`GET /api/warnings/pending` tells everybody else on their next visit. Both
build their payload here so the two cannot drift.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import UserWarning
from app.services.player_reports import cited_notice_messages, notice_drawings


async def pending_warning_payload(
    session_factory: async_sessionmaker[AsyncSession], user_id: str
) -> dict:
    """The user's oldest unacknowledged warning, or ``{"warning": None}``.

    Includes the reported messages behind it - their own words, which is what
    makes the reason something they can weigh rather than just be told. Only
    the snapshot, and only the text and the time: the evidence is authored by
    the warned player by construction, so nothing here can name whoever
    reported them. Any drawings the reports carried are theirs for the same
    reason and come with it - by their metadata here, and their bytes over
    `GET /api/warnings/{warning_id}/drawings/{report_id}`.
    """
    try:
        target = UUID(user_id)
    except (ValueError, TypeError):
        return {"warning": None}
    async with session_factory() as session:
        warning = await session.scalar(
            select(UserWarning)
            .where(
                UserWarning.user_id == target,
                UserWarning.acknowledged_at.is_(None),
            )
            .order_by(UserWarning.created_at)
            .limit(1)
        )
        if warning is None:
            return {"warning": None}
        return {
            "warning": {
                "id": str(warning.id),
                "reason": warning.reason,
                "category": warning.category,
                "createdAt": warning.created_at.isoformat(),
                # Every cited line and every canvas the decision behind this
                # warning covered, not only the one report it names (#620).
                "messages": await cited_notice_messages(
                    session, warning.source_report_id
                ),
                "drawings": await notice_drawings(session, warning.source_report_id),
            }
        }
