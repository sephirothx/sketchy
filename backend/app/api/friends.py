"""Friend list, requests, and the three ways one ends.

Registered accounts only, on both sides. A guest is an identity that lives in
one browser and is purged after a month of not playing, so a friendship with
one would outlive the account and vanish without explanation - "where did my
friend go" is not a diagnosable bug report. The caller is told why; the target
never is, for the reasons in `app.services.friends`.

Note the asymmetry with blocks, which every account including a guest may use
(R-BLOCK-01): a block is a protection, and refusing the least-established
players the ability to mute somebody would be refusing safety. A friendship is
a convenience.
"""
from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.rate_limit import PersistentRateLimiter
from app.db.models import Friendship, User
from app.domain_values import AccountState, FriendshipState
from app.services.friends import (
    FriendService,
    FriendshipOutcome,
    FriendshipRefused,
)


def _limit(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


REGISTER_FIRST = (
    "Create an account to add friends - a guest account is removed after a "
    "month of not playing."
)


class FriendBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    user_id: UUID = Field(alias="userId")


def _person_payload(row: Friendship, person: User, viewer_id: UUID) -> dict:
    """One entry, from the reading account's point of view.

    `requestedByMe` rather than a requester id: which of the two asked is a
    fact about this pair, and the reader is one of them, but the raw id adds
    nothing they cannot already see and travels further than it needs to.
    """
    return {
        "userId": str(person.id),
        "displayName": person.display_name,
        "nameColor": person.name_color,
        "isAnonymous": person.is_anonymous,
        "status": row.status,
        "requestedByMe": row.requested_by_id == viewer_id,
        "createdAt": row.created_at.isoformat(),
        "respondedAt": row.responded_at.isoformat() if row.responded_at else None,
    }


def create_friends_router(
    session_factory: async_sessionmaker[AsyncSession],
    friend_service: FriendService,
    # Called with the *other* account whenever a call here changed what their
    # own lists say. The router has no socket of its own, the way the ban and
    # deletion paths do not either.
    on_friends_changed: Callable[[str], Awaitable[None]] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/users/me/friends")

    # Per account rather than per address: the address is the proxy's behind a
    # reverse proxy, and this is an action only a signed-in account can take
    # anyway. Persistent, so a restart is not a fresh allowance.
    request_limiter = PersistentRateLimiter(
        session_factory,
        scope="friend_request",
        limit=_limit("FRIEND_REQUEST_LIMIT", 20),
        window_seconds=3600,
    )

    async def current_account(request: Request) -> User:
        value = getattr(request.state, "user_id", None)
        if not value:
            raise HTTPException(status_code=401, detail="Sign in first.")
        async with session_factory() as session:
            user = await session.get(User, UUID(value))
        if user is None or user.state == AccountState.DELETED.value:
            raise HTTPException(status_code=401, detail="Sign in first.")
        if user.is_anonymous:
            raise HTTPException(status_code=403, detail=REGISTER_FIRST)
        return user

    @router.get("")
    async def list_friends(request: Request):
        me = await current_account(request)
        listing = await friend_service.listing(me.id)
        return {
            key: [_person_payload(row, person, me.id) for row, person in rows]
            for key, rows in listing.items()
        }

    @router.post("")
    async def request_friend(body: FriendBody, request: Request, response: Response):
        """Ask to be friends, or answer a request already waiting.

        Answers 200 whatever happened, unless the caller hit a ceiling of their
        own. That is the point: a 404 for an unknown id, or a 403 for a block,
        would each be a fact about somebody who is not in this conversation.
        """
        me = await current_account(request)
        if not await request_limiter.check(str(me.id)):
            raise HTTPException(
                status_code=429,
                detail="You have sent a lot of friend requests recently. "
                "Try again later.",
            )
        try:
            outcome = await friend_service.request(me.id, body.user_id)
        except FriendshipRefused as refused:
            await request_limiter.refund(str(me.id))
            raise HTTPException(status_code=409, detail=str(refused)) from refused
        if outcome in (FriendshipOutcome.IGNORED, FriendshipOutcome.UNCHANGED):
            # Nothing was written, so nothing was spent (R-RATE-05's rule).
            await request_limiter.refund(str(me.id))
        elif on_friends_changed is not None:
            # Only where something moved: a notification on a request that was
            # quietly dropped would be the tell the silence exists to avoid.
            await on_friends_changed(str(body.user_id))
        response.status_code = 201 if outcome == FriendshipOutcome.CREATED else 200
        return {"status": _reported_status(outcome)}

    @router.post("/{user_id}/accept")
    async def accept_friend(user_id: UUID, request: Request):
        me = await current_account(request)
        if user_id == me.id:
            raise HTTPException(status_code=422, detail="That is you.")
        try:
            outcome = await friend_service.accept(me.id, user_id)
        except FriendshipRefused as refused:
            raise HTTPException(status_code=409, detail=str(refused)) from refused
        if outcome == FriendshipOutcome.ACCEPTED and on_friends_changed is not None:
            # The person who asked is the one who has been waiting.
            await on_friends_changed(str(user_id))
        return {"status": _reported_status(outcome)}

    @router.delete("/{user_id}", status_code=204)
    async def remove_friend(user_id: UUID, request: Request, response: Response):
        """Decline, cancel, or unfriend - whichever this row is asking for.

        One verb, because from the caller's side they are one gesture. What
        differs is what is left behind, and that is decided in the service.
        """
        me = await current_account(request)
        if user_id == me.id:
            raise HTTPException(status_code=422, detail="That is you.")
        await friend_service.remove(me.id, user_id)
        response.status_code = 204
        return None

    return router


def _reported_status(outcome: FriendshipOutcome) -> str:
    """What the caller is told, which is less than what happened.

    `IGNORED` and `UNCHANGED` both report `pending`: from the outside, a
    request that was dropped and one that is genuinely waiting look the same,
    and that is the whole point of dropping it quietly.
    """
    if outcome == FriendshipOutcome.ACCEPTED:
        return FriendshipState.ACCEPTED.value
    return FriendshipState.PENDING.value

