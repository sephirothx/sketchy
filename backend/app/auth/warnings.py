"""What a warned account is told, and what it cannot do until it has read it.

A warning reaches the player through their inbox (#1436): the read of
`GET /api/inbox` carries the oldest warning not yet acknowledged, which the
client shows as a dialog that can only be answered. Built here so every
surface that shows it says the same thing.

Until it is acknowledged the account cannot take a seat - create, join or
quick-play a room - or publish or star a prompt list (R-INBOX-04). Enforced on
the server, so another tab or a modified client cannot skip the dialog.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User, UserWarning
from app.services.player_reports import cited_notice_messages, notice_drawings


async def has_unacknowledged_warning(
    session_factory: async_sessionmaker[AsyncSession], user_id: str | None
) -> bool:
    """Whether the account has a warning it has not acknowledged yet."""
    if not user_id:
        return False
    try:
        target = UUID(str(user_id))
    except ValueError:
        return False
    async with session_factory() as session:
        return (
            await session.scalar(
                select(UserWarning.id)
                .where(
                    UserWarning.user_id == target,
                    UserWarning.acknowledged_at.is_(None),
                )
                .limit(1)
            )
        ) is not None


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
                "kind": warning.kind,
                "reason": warning.reason,
                "category": warning.category,
                "createdAt": warning.created_at.isoformat(),
                # Every cited line and every canvas the decision behind this
                # warning covered, not only the one report it names (#620).
                "messages": await cited_notice_messages(
                    session, warning.source_report_id
                ),
                "drawings": await notice_drawings(session, warning.source_report_id),
                # A removal says when another picture may go up, in the
                # reader's language rather than a sentence built here.
                "uploadAgainAt": await _upload_again_at(session, warning),
            }
        }


async def _upload_again_at(session: AsyncSession, warning: UserWarning) -> str | None:
    if warning.kind != "avatar_removal":
        return None
    until = await session.scalar(
        select(User.avatar_upload_blocked_until).where(User.id == warning.user_id)
    )
    if until is None or until <= datetime.now(timezone.utc):
        return None
    return until.isoformat()
