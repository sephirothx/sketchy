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

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import Refusal
from app.refusals import ErrorCode
from app.auth.avatars import avatar_url
from app.db.models import Friendship, User
from app.domain_values import AccountState, FriendshipState
from app.repositories.interfaces import GameHistoryRepository
from app.services.friends import (
    REGISTER_FIRST,
    FriendService,
    FriendshipOutcome,
    FriendshipRefused,
    FriendshipThrottled,
)


#: Names *why* a 403 from these endpoints happened.
#:
#: A status alone cannot say. The middleware answers 403 for a suspended
#: account before any of this runs, and step-up answers 403 with a header of
#: its own - so a client that reads "403" as "this caller is a guest" is
#: reading two other refusals as that too. A guest's refusal is the only one
#: that means *there is no list*, and a client acts on it: it shows an empty
#: friends list and says so. Getting that wrong wipes a real account's lists
#: off the screen.
#:
#: A header rather than a body field, following `X-Sketchy-Step-Up`: the
#: refusal keeps FastAPI's ordinary `{"detail": ...}` shape, and the reason
#: rides beside it where a client can read it without parsing anything.
ACCOUNT_REQUIRED_HEADER = "X-Sketchy-Account-Required"


async def _current_account(
    session_factory: async_sessionmaker[AsyncSession], request: Request
) -> User:
    """The registered account behind this request, or a refusal saying why.

    Shared by both routers here so that a guest is turned away with the same
    403 and the same sentence wherever they arrive - R-FRIEND-03's reason is
    the same one in either place, and two copies would drift.
    """
    value = getattr(request.state, "user_id", None)
    if not value:
        raise Refusal(401, ErrorCode.SIGN_IN_REQUIRED, "Sign in first.")
    async with session_factory() as session:
        user = await session.get(User, UUID(value))
    if user is None or user.state == AccountState.DELETED.value:
        raise Refusal(401, ErrorCode.SIGN_IN_REQUIRED, "Sign in first.")
    if user.is_anonymous:
        raise Refusal(
            403,
            ErrorCode.ACCOUNT_REQUIRED,
            REGISTER_FIRST,
            params={"action": "friends"},
            headers={ACCOUNT_REQUIRED_HEADER: "1"},
        )
    return user


# How many acceptances one message names at once. More than this and the rest
# wait for the next read; the message is a line per friendship, so a screenful
# is already past the point of being read.
MAX_ANNOUNCED_AT_ONCE = 50


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
        "avatarUrl": avatar_url(None if person.is_anonymous else person.avatar_key),
        "isAnonymous": person.is_anonymous,
        "status": row.status,
        "requestedByMe": row.requested_by_id == viewer_id,
        "createdAt": row.created_at.isoformat(),
        "respondedAt": row.responded_at.isoformat() if row.responded_at else None,
    }


class AnnouncedBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    user_ids: list[UUID] = Field(
        default_factory=list, alias="userIds", max_length=MAX_ANNOUNCED_AT_ONCE
    )


def create_friends_router(
    session_factory: async_sessionmaker[AsyncSession],
    friend_service: FriendService,
) -> APIRouter:
    router = APIRouter(prefix="/api/users/me/friends")

    async def current_account(request: Request) -> User:
        return await _current_account(session_factory, request)

    @router.get("")
    async def list_friends(request: Request):
        """The lists, and what this account is still owed the news of.

        `announce` is the durable half of R-FRIEND-12: the requests this
        account sent that were accepted and that nobody has told them about
        yet. It rides the read the client already makes rather than needing
        one of its own, and it is a fact on the row rather than a difference
        between two reads - a client that was reloading when the answer came
        has no earlier read to compare against (R-FRIEND-14).
        """
        me = await current_account(request)
        listing = await friend_service.listing(me.id)
        return {
            key: [_person_payload(row, person, me.id) for row, person in rows]
            for key, rows in listing.items()
        }

    @router.post("/announced")
    async def acknowledge_announced(body: AnnouncedBody, request: Request):
        """Record that the asker was told, for the friendships named.

        Sent after the message is shown, and naming exactly what it was
        about: recording first loses the news whenever the render does not
        happen, and recording *everything outstanding* swallows an acceptance
        that landed in between. The failure left is being told twice.
        """
        me = await current_account(request)
        told = await friend_service.announced(me.id, body.user_ids)
        return {"ok": True, "announced": told}

    @router.post("")
    async def request_friend(body: FriendBody, request: Request, response: Response):
        """Ask to be friends, or answer a request already waiting.

        Answers 200 whatever happened, unless the caller hit a ceiling of their
        own. That is the point: a 404 for an unknown id, or a 403 for a block,
        would each be a fact about somebody who is not in this conversation.
        """
        me = await current_account(request)
        try:
            # The hourly ceiling and its refund live in the service, so the
            # in-room command answers to the same one.
            outcome = await friend_service.request(me.id, body.user_id)
        except FriendshipThrottled as throttled:
            raise Refusal(429, ErrorCode.FRIENDS_THROTTLED, str(throttled)) from throttled
        except FriendshipRefused as refused:
            raise Refusal(409, ErrorCode.FRIEND_REFUSED, str(refused)) from refused
        response.status_code = 201 if outcome == FriendshipOutcome.CREATED else 200
        return {"status": _reported_status(outcome)}

    @router.post("/{user_id}/accept")
    async def accept_friend(user_id: UUID, request: Request):
        me = await current_account(request)
        if user_id == me.id:
            raise Refusal(422, ErrorCode.THAT_IS_YOU, "That is you.")
        try:
            outcome = await friend_service.accept(me.id, user_id)
        except FriendshipRefused as refused:
            raise Refusal(409, ErrorCode.FRIEND_REFUSED, str(refused)) from refused
        return {"status": _accept_status(outcome)}

    @router.delete("/{user_id}", status_code=204)
    async def remove_friend(user_id: UUID, request: Request, response: Response):
        """Decline, cancel, or unfriend - whichever this row is asking for.

        One verb, because from the caller's side they are one gesture. What
        differs is what is left behind, and that is decided in the service.
        """
        me = await current_account(request)
        if user_id == me.id:
            raise Refusal(422, ErrorCode.THAT_IS_YOU, "That is you.")
        await friend_service.remove(me.id, user_id)
        response.status_code = 204
        return None

    return router


#: How far back "recently" reaches.
#:
#: Long enough that a weekly game still counts, short enough that the list is
#: about who somebody is playing with rather than everyone they ever met. A
#: window rather than a page of history, so a player returning after a year
#: gets an empty list instead of a stale one - and so the scan is bounded by
#: an index on `finished_at` rather than by however many games they have.
RECENT_PLAYERS_WINDOW = timedelta(days=30)

#: At most this many, newest first. The surface is a short list to scan, not a
#: directory, and R-FRIEND-09 bounds friendships anyway.
RECENT_PLAYERS_LIMIT = 20


def create_recent_players_router(
    session_factory: async_sessionmaker[AsyncSession],
    history: GameHistoryRepository,
) -> APIRouter:
    """Who the caller has been playing with, as people they could befriend.

    Not a search, and not a directory (N-06): it answers only about games the
    caller themselves sat in, so it can never name somebody they have not met.
    That is the whole reason it exists - the lobby can only offer a friendship
    to whoever is standing there right now, and the person you actually want
    is usually the one you finished a game with yesterday.

    Deliberately does not filter by friendship or block. An account missing
    from a list is a fact, and "missing because they declined you" is exactly
    the fact R-FRIEND-04 refuses to disclose. Rows that are already friends or
    already have a request are dropped by the client, which is filtering what
    it can see anyway; a decline is not one of those, so it stays and its
    button quietly does nothing, which is what a decline is meant to feel
    like.
    """
    router = APIRouter(prefix="/api/users/me/recent-players")

    @router.get("")
    async def recent_players(request: Request):
        me = await _current_account(session_factory, request)
        found = await history.get_recent_co_players(
            str(me.id),
            since=datetime.now(timezone.utc) - RECENT_PLAYERS_WINDOW,
            limit=RECENT_PLAYERS_LIMIT,
        )
        return {
            "players": [
                {
                    "userId": person.user_id,
                    "displayName": person.display_name,
                    "nameColor": person.name_color,
                    "avatarUrl": avatar_url(person.avatar_key),
                    "lastPlayedAt": person.last_played_at.isoformat(),
                }
                for person in found
            ]
        }

    return router


def _reported_status(outcome: FriendshipOutcome) -> str:
    """What a *request* is told, which is less than what happened.

    `IGNORED` and `UNCHANGED` both report `pending`: from the outside, a
    request that was dropped and one that is genuinely waiting look the same,
    and that is the whole point of dropping it quietly.
    """
    if outcome == FriendshipOutcome.ACCEPTED:
        return FriendshipState.ACCEPTED.value
    return FriendshipState.PENDING.value


def _accept_status(outcome: FriendshipOutcome) -> str:
    """What an *answer* is told, which is the truth.

    The vagueness above protects somebody the caller has not met. Here they
    are answering a request already on their own list, so there is nothing to
    withhold - and saying `pending` when the row has just been declined by a
    block, or was never there, leaves a client showing a request that is gone.
    """
    if outcome == FriendshipOutcome.ACCEPTED:
        return FriendshipState.ACCEPTED.value
    if outcome == FriendshipOutcome.IGNORED:
        # A block landed between the request and this answer, and won.
        return FriendshipState.DECLINED.value
    return "unchanged"

