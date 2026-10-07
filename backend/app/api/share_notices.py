"""Telling a drawer that somebody else shared their drawing (#1430, R-SHARE-09).

Another player may put a public game's drawing in the Gallery without asking
(R-SHARE-02), so the drawer is told, once per drawing, and can take it back
out from where they are told. The pattern is `role_notices.py`'s: the notice
is a row written in the transaction that made the share, a connected account
hears it on the socket the moment that commits, everybody else on their next
visit through `GET /api/share-notices/pending`, and both build their payload
here so the two cannot drift.

The share the notice is about may be gone by the time it is read - its sharer
took it back, the drawer already withdrew it, a moderator hid it - and a
notice about a drawing that is not in the Gallery has nothing to say, so the
pending read shows only the ones still true.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import Refusal
from app.db.models import DrawingShareNotice, GameParticipant, TurnDrawing, TurnRecord
from app.refusals import ErrorCode
from app.repositories.sqlalchemy import _identity_ids

#: How many notices one read shows; the rest are counted, not listed. A drawer
#: back from a week away should see a short card, not a page.
PENDING_SHOWN = 5


def _still_shared():
    """A notice is still worth reading while its drawing is in the Gallery."""
    return and_(
        TurnDrawing.turn_id == DrawingShareNotice.turn_id,
        TurnDrawing.gallery_shared_at.is_not(None),
        TurnDrawing.gallery_hidden_at.is_(None),
    )


async def pending_share_notice_payload(
    session_factory: async_sessionmaker[AsyncSession], user_id: str
) -> dict:
    """The account's newest unacknowledged notices, and how many there are.

    Every identity of the account - a guest's drawing shared before it was
    merged into this account was told to the guest's id."""
    try:
        target = UUID(user_id)
    except (ValueError, TypeError):
        return {"notices": [], "total": 0}
    async with session_factory() as session:
        identity_ids = await _identity_ids(session, target)
        pending = (
            DrawingShareNotice.user_id.in_(identity_ids),
            DrawingShareNotice.acknowledged_at.is_(None),
        )
        total = int(
            await session.scalar(
                select(func.count())
                .select_from(DrawingShareNotice)
                .join(TurnDrawing, _still_shared())
                .where(*pending)
            )
            or 0
        )
        rows = (
            await session.execute(
                select(
                    DrawingShareNotice.id,
                    DrawingShareNotice.turn_id,
                    DrawingShareNotice.created_at,
                    TurnRecord.prompt,
                    GameParticipant.display_name_snapshot,
                    GameParticipant.name_color_snapshot,
                    GameParticipant.is_anonymous_snapshot,
                )
                .join(TurnDrawing, _still_shared())
                .join(TurnRecord, TurnRecord.id == DrawingShareNotice.turn_id)
                .join(
                    GameParticipant,
                    GameParticipant.id == DrawingShareNotice.sharer_participant_id,
                )
                .where(*pending)
                .order_by(DrawingShareNotice.created_at.desc(), DrawingShareNotice.id.desc())
                .limit(PENDING_SHOWN)
            )
        ).all()
    return {
        "notices": [
            {
                "id": str(row.id),
                "turnId": str(row.turn_id),
                "prompt": row.prompt,
                "sharerDisplayName": row.display_name_snapshot,
                "sharerNameColor": row.name_color_snapshot,
                "sharerIsAnonymous": row.is_anonymous_snapshot,
                "createdAt": row.created_at.isoformat(),
            }
            for row in rows
        ],
        "total": total,
    }


def create_share_notice_router(
    session_factory: async_sessionmaker[AsyncSession],
) -> APIRouter:
    """The player-facing halves: read your own notices, and settle them."""
    router = APIRouter()

    @router.get("/api/share-notices/pending")
    async def pending_share_notices(request: Request):
        """The caller's newest unacknowledged notices, for a drawer who was not
        connected when their drawing was shared; the payload is the push's."""
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise Refusal(401, ErrorCode.SIGN_IN_REQUIRED, "Sign in first.")
        return await pending_share_notice_payload(session_factory, user_id)

    @router.post("/api/share-notices/{notice_id}/acknowledge")
    async def acknowledge_share_notices(notice_id: UUID, request: Request):
        """Settle the notice and every older one: the card that was shown
        listed the newest and counted the rest, so all of them were told."""
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise Refusal(401, ErrorCode.SIGN_IN_REQUIRED, "Sign in first.")
        async with session_factory() as session:
            async with session.begin():
                identity_ids = await _identity_ids(session, UUID(user_id))
                notice = await session.scalar(
                    select(DrawingShareNotice).where(DrawingShareNotice.id == notice_id)
                )
                # Somebody else's notice is not this caller's to see, or to
                # acknowledge away; answering 404 keeps its existence private.
                if notice is None or notice.user_id not in identity_ids:
                    raise Refusal(404, ErrorCode.NO_SUCH_NOTICE, "No such notice.")
                await session.execute(
                    update(DrawingShareNotice)
                    .where(
                        DrawingShareNotice.user_id.in_(identity_ids),
                        DrawingShareNotice.acknowledged_at.is_(None),
                        DrawingShareNotice.created_at <= notice.created_at,
                    )
                    .values(acknowledged_at=datetime.now(timezone.utc))
                )
        return {"ok": True}

    return router
