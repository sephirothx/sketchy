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

from app.db.models import PlayerReportMessageEvidence, UserWarning
from app.services.player_reports import (
    drawing_evidence_for_report,
    drawing_evidence_payload,
)


async def pending_warning_payload(
    session_factory: async_sessionmaker[AsyncSession], user_id: str
) -> dict:
    """The user's oldest unacknowledged warning, or ``{"warning": None}``.

    Includes the reported messages behind it - their own words, which is what
    makes the reason something they can weigh rather than just be told. Only
    the snapshot, and only the text and the time: the evidence is authored by
    the warned player by construction, so nothing here can name whoever
    reported them. The drawing the report carried, if one did, is theirs for
    the same reason and comes with it - by its metadata here, and its bytes
    over `GET /api/warnings/{warning_id}/drawing`.
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
        messages: list[dict] = []
        drawing = drawing_evidence_payload(
            await drawing_evidence_for_report(session, warning.source_report_id)
        )
        if warning.source_report_id is not None:
            rows = (
                await session.scalars(
                    select(PlayerReportMessageEvidence)
                    .where(
                        PlayerReportMessageEvidence.report_id
                        == warning.source_report_id,
                        # Their own reported words (R-MOD-12). What others
                        # said around them is a moderator's context, not
                        # something to show the player back.
                        PlayerReportMessageEvidence.role == "cited",
                    )
                    .order_by(PlayerReportMessageEvidence.position)
                )
            ).all()
            messages = [
                {
                    "text": row.text_snapshot,
                    "at": row.message_created_at.isoformat()
                    if row.message_created_at
                    else None,
                }
                for row in rows
            ]
        return {
            "warning": {
                "id": str(warning.id),
                "reason": warning.reason,
                "createdAt": warning.created_at.isoformat(),
                "messages": messages,
                "drawing": drawing,
            }
        }
