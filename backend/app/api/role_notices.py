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

from app.auth.pending_role import pending_offer
from app.db.models import RoleChangeNotice, User


async def pending_role_notice_payload(
    session_factory: async_sessionmaker[AsyncSession], user_id: str
) -> dict:
    """The account's *newest* unacknowledged notice, and what is waiting on it.

    Two things, because they answer different questions and both travel this
    way. `notice` is what the account has still to be *told*; `pendingRole` is
    what is *outstanding* on it - a staff role offered and waiting on a second
    factor (R-AUTH-20). A withdrawal is the case that needs both: it settles
    the notice, so there is nothing left to say, and it ends the offer, which
    a connected browser has to hear or it goes on showing the way into an
    enrolment that would now grant nothing.

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
        return {"notice": None, "pendingRole": None}
    async with session_factory() as session:
        account = await session.get(User, target)
        standing = pending_offer(account) if account is not None else None
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
            return {"notice": None, "pendingRole": standing}
        if notice.pending and standing is None:
            # The invitation outlived the offer. A notice about a role is a
            # message; `users.pending_role` is the fact, and the two part
            # company whenever the offer ends without the row being settled -
            # a lapse, most of all, which is nobody's write at all. Telling
            # somebody a role is waiting when the server would grant nothing
            # on enrolment sends them to do a thing for no reason, so the fact
            # is what answers here.
            #
            # Nothing older is offered in its place: an offer is the newest
            # thing that happened to this account's role, so there is nothing
            # behind it still worth saying.
            return {"notice": None, "pendingRole": None}
        return {
            "pendingRole": standing,
            "notice": {
                "id": str(notice.id),
                "role": notice.role,
                # Whether the role is theirs or is waiting on them. The second
                # asks for something - a second factor, before it takes effect
                # (R-AUTH-20) - so it cannot be worded like the first.
                "pending": notice.pending,
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
