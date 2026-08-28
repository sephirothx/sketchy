"""Telling an account that its own role changed - and knowing that it landed.

A role is granted from the operations page while the player it is about may be
anywhere: mid-game, in the lobby, or asleep. So the notice arrives by two
routes and they must say the same thing - the socket tells whoever is
connected the moment an administrator acts, and `GET /api/role-notices/pending`
tells everybody else on their next visit. Both build their payload here, so the
two cannot drift, exactly as `app/auth/warnings.py` does for a warning.

The row is written by `PATCH /api/admin/players/{id}/role` in the transaction
that changes the role. Nothing here can grant anything: this module only
answers what the account has yet to be told, and records that it was.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import RoleChangeNotice


async def pending_role_notice_payload(
    session_factory: async_sessionmaker[AsyncSession], user_id: str
) -> dict:
    """The account's *newest* unacknowledged notice, or ``{"notice": None}``.

    Newest rather than oldest, which is where this parts company with a
    warning. Two warnings are two things a moderator said and both are worth
    reading; two role notices are one fact recorded twice, and the older one is
    simply wrong. An account promoted and then demoted while it was offline is
    told once, correctly, instead of being congratulated on a role it no longer
    holds and then contradicted.
    """
    try:
        target = UUID(user_id)
    except (ValueError, TypeError):
        return {"notice": None}
    async with session_factory() as session:
        notice = await session.scalar(
            select(RoleChangeNotice)
            .where(
                RoleChangeNotice.user_id == target,
                RoleChangeNotice.acknowledged_at.is_(None),
            )
            .order_by(RoleChangeNotice.created_at.desc())
            .limit(1)
        )
        if notice is None:
            return {"notice": None}
        return {
            "notice": {
                "id": str(notice.id),
                "role": notice.role,
                "createdAt": notice.created_at.isoformat(),
            }
        }


def create_role_notice_router(
    session_factory: async_sessionmaker[AsyncSession],
) -> APIRouter:
    """The two player-facing halves: read your own notice, and settle it."""
    router = APIRouter()

    @router.get("/api/role-notices/pending")
    async def pending_role_notice(request: Request):
        """The caller's own newest unacknowledged notice.

        The catch-up route for a player who was offline when an administrator
        acted; the payload is shared with the live socket push.
        """
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(status_code=401, detail="Sign in first.")
        return await pending_role_notice_payload(session_factory, user_id)

    @router.post("/api/role-notices/{notice_id}/acknowledge")
    async def acknowledge_role_notice(notice_id: UUID, request: Request):
        """Record that the notice reached the account it was about.

        Everything older is settled with it. The account has just been shown
        where it stands now, so an earlier notice has nothing left to say - and
        leaving it pending would pop up a stale role on the next visit.
        """
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(status_code=401, detail="Sign in first.")
        caller = UUID(user_id)
        async with session_factory() as session:
            async with session.begin():
                notice = await session.scalar(
                    select(RoleChangeNotice)
                    .where(RoleChangeNotice.id == notice_id)
                    .with_for_update()
                )
                # Somebody else's notice is not this caller's to see, or to
                # acknowledge away; answering 404 keeps its existence private.
                if notice is None or notice.user_id != caller:
                    raise HTTPException(status_code=404, detail="No such notice.")
                now = datetime.now(timezone.utc)
                pending = (
                    await session.scalars(
                        select(RoleChangeNotice)
                        .where(
                            RoleChangeNotice.user_id == caller,
                            RoleChangeNotice.acknowledged_at.is_(None),
                            RoleChangeNotice.created_at <= notice.created_at,
                        )
                        .with_for_update()
                    )
                ).all()
                for row in pending:
                    row.acknowledged_at = now
            return {"ok": True}

    return router
