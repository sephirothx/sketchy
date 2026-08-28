"""One administrator gate, for every surface that needs one.

Written out twice already - once in `api/operations.py`, once in
`api/bug_reports.py` - with the same body and two versions of the comment
explaining the 404. The runtime-tuning surfaces (#446) would have been a third
and a fourth, and a check that decides who may change a live server is the last
thing that should exist in four copies drifting apart.

The 404 is deliberate, and R-ROLE-01 requires it: an ordinary player asking for
an administrator's URL is told the URL does not exist, not that it exists and
they may not have it. Whether a deployment has an operator page at all is not
something the page should confirm.

Moderation keeps its own reviewer gate on purpose. It admits two roles rather
than one and answers 403, because its surfaces are reachable from the in-app
report flow, where "no such page" would be a worse answer than "not you".
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.domain_values import UserRole


def admin_gate(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[Request], Awaitable[User]]:
    """The `require_admin(request)` a router factory closes over."""

    async def require_admin(request: Request) -> User:
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(status_code=401, detail="Sign in first.")
        try:
            target = UUID(user_id)
        except ValueError as error:
            # A session carrying something that is not an identifier is not a
            # session this server issued.
            raise HTTPException(status_code=404, detail="Not found.") from error
        async with session_factory() as session:
            user = await session.get(User, target)
        if user is None or user.role != UserRole.ADMIN.value:
            raise HTTPException(status_code=404, detail="Not found.")
        return user

    return require_admin
