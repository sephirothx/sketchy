"""An account's inbox over REST (#1436, R-INBOX-01..07).

One read for the bell and the inbox, and one write for reading. The socket
carries `inbox_changed` with nothing in it, which a client answers by reading
this again: the payload is built in exactly one place, so a push and a visit
cannot say different things, and a tab that missed the push - offline, or
between a drop and the reconnect - is caught by the read it makes on
connecting.

An entry is the message, and what it says is read here from the fact it
names, at the moment it is shown: who shared a drawing and whether it is
still in the Gallery, whether a friend request is still waiting, whether an
offer of a role still stands. A fact that has gone leaves its entry saying
so, rather than a stale line offering to act on it.

Two things ride along with every read, because they are what the client has
to act on: the oldest warning not yet acknowledged, which is the dialog the
player must answer before taking a seat (R-INBOX-04), and the role the account
has been offered, which is what the account menu's way into enrolment shows
for.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import Refusal
from app.auth.pending_role import pending_offer
from app.auth.warnings import pending_warning_payload
from app.db.models import (
    Friendship,
    GameParticipant,
    InboxEntry,
    TurnDrawing,
    TurnDrawingShare,
    TurnRecord,
    User,
    UserWarning,
)
from app.domain_values import FriendshipState
from app.refusals import ErrorCode
from app.repositories.sqlalchemy import _identity_ids
from app.request_text import ControlFreeModel
from app.services.friends import friendship_key
from app.services.inbox import mark_read

#: Entries per read. The bell's panel shows the newest; the rest are a page
#: away, never all at once.
INBOX_PAGE = 20
#: The most entries one read-request may name.
MAX_READ_IDS = 100


def _person(user: User | None) -> dict | None:
    if user is None:
        return None
    return {"userId": str(user.id), "displayName": user.display_name, "nameColor": user.name_color}


async def _sharers(session: AsyncSession, turn_ids: list[UUID]) -> dict:
    """Each drawing's earliest share still standing that is not its drawer's
    - who an entry names, read now so a sharer who took theirs back or was
    erased is never the one named (R-SHARE-09)."""
    if not turn_ids:
        return {}
    named: dict = {}
    rows = await session.execute(
        select(
            TurnDrawingShare.turn_id,
            TurnDrawingShare.participant_id,
            TurnRecord.drawer_participant_id,
            GameParticipant.display_name_snapshot,
            GameParticipant.name_color_snapshot,
            GameParticipant.is_anonymous_snapshot,
        )
        .join(TurnRecord, TurnRecord.id == TurnDrawingShare.turn_id)
        .join(GameParticipant, GameParticipant.id == TurnDrawingShare.participant_id)
        .where(TurnDrawingShare.turn_id.in_(turn_ids))
        .order_by(
            TurnDrawingShare.turn_id,
            TurnDrawingShare.created_at,
            TurnDrawingShare.participant_id,
        )
    )
    for share in rows.all():
        if share.turn_id in named or share.participant_id == share.drawer_participant_id:
            continue
        named[share.turn_id] = {
            "displayName": share.display_name_snapshot,
            "nameColor": share.name_color_snapshot,
            "isAnonymous": share.is_anonymous_snapshot,
        }
    return named


async def _render(session: AsyncSession, entries: list[InboxEntry]) -> list[dict]:
    """Each entry with what it says now, read in one statement per kind."""
    by_kind: dict[str, list[InboxEntry]] = {}
    for entry in entries:
        by_kind.setdefault(entry.kind, []).append(entry)
    now = datetime.now(timezone.utc)

    warnings = {}
    if "warning" in by_kind:
        rows = await session.execute(
            select(UserWarning, User.avatar_upload_blocked_until)
            .join(User, User.id == UserWarning.user_id)
            .where(UserWarning.id.in_([e.subject_id for e in by_kind["warning"]]))
        )
        warnings = {warning.id: (warning, until) for warning, until in rows.all()}

    drawings = {}
    sharers = {}
    if "drawing_shared" in by_kind:
        turn_ids = [e.subject_id for e in by_kind["drawing_shared"]]
        rows = await session.execute(
            select(
                TurnRecord.id,
                TurnRecord.prompt,
                TurnDrawing.gallery_share_count,
                TurnDrawing.gallery_hidden_at,
            )
            .join(TurnDrawing, TurnDrawing.turn_id == TurnRecord.id, isouter=True)
            .where(TurnRecord.id.in_(turn_ids))
        )
        drawings = {row.id: row for row in rows.all()}
        sharers = await _sharers(session, turn_ids)

    people_ids = {
        e.subject_id
        for kind in ("friend_request", "friend_accepted", "game_invite")
        for e in by_kind.get(kind, [])
    }
    people = (
        {
            user.id: user
            for user in (
                await session.scalars(select(User).where(User.id.in_(people_ids)))
            ).all()
        }
        if people_ids
        else {}
    )
    friendships = {}
    pairs = {
        friendship_key(e.user_id, e.subject_id)
        for kind in ("friend_request", "friend_accepted")
        for e in by_kind.get(kind, [])
    }
    if pairs:
        rows = await session.scalars(
            select(Friendship).where(
                or_(
                    *[
                        and_(Friendship.user_low_id == low, Friendship.user_high_id == high)
                        for low, high in pairs
                    ]
                )
            )
        )
        friendships = {(row.user_low_id, row.user_high_id): row for row in rows.all()}

    owners = {}
    if "role" in by_kind:
        owners = {
            user.id: user
            for user in (
                await session.scalars(
                    select(User).where(User.id.in_({e.user_id for e in by_kind["role"]}))
                )
            ).all()
        }

    rendered: list[dict] = []
    for entry in entries:
        body: dict = {
            "id": str(entry.id),
            "kind": entry.kind,
            "createdAt": entry.created_at.isoformat(),
            "read": entry.read_at is not None,
        }
        if entry.kind == "warning":
            found = warnings.get(entry.subject_id)
            if found is None:
                continue
            warning, until = found
            body["warning"] = {
                "id": str(warning.id),
                "kind": warning.kind,
                "reason": warning.reason,
                "category": warning.category,
                "acknowledged": warning.acknowledged_at is not None,
                "uploadAgainAt": (
                    until.isoformat()
                    if warning.kind == "avatar_removal" and until is not None and until > now
                    else None
                ),
            }
        elif entry.kind == "drawing_shared":
            drawing = drawings.get(entry.subject_id)
            if drawing is None:
                continue
            body["drawing"] = {
                "turnId": str(entry.subject_id),
                "prompt": drawing.prompt,
                "inGallery": bool(drawing.gallery_share_count)
                and drawing.gallery_hidden_at is None,
                "sharedBy": sharers.get(entry.subject_id),
            }
        elif entry.kind in ("friend_request", "friend_accepted"):
            row = friendships.get(friendship_key(entry.user_id, entry.subject_id))
            if row is None:
                state = "gone"
            elif row.status == FriendshipState.ACCEPTED.value:
                state = "friends"
            elif (
                row.status == FriendshipState.PENDING.value
                and row.requested_by_id == entry.subject_id
            ):
                state = "pending"
            else:
                state = "gone"
            body["person"] = _person(people.get(entry.subject_id))
            body["state"] = state
        elif entry.kind == "game_invite":
            body["person"] = _person(people.get(entry.subject_id))
            body["expiresAt"] = entry.params.get("expiresAt")
        elif entry.kind == "reports_reviewed":
            body["count"] = int(entry.params.get("count", 1))
        elif entry.kind == "role":
            owner = owners.get(entry.user_id)
            role = entry.params.get("role")
            change = entry.params.get("change")
            body["role"] = role
            body["change"] = change
            # An offer stands for its lifetime only; past it, enrolment
            # would grant nothing (R-ROLE-02).
            body["offerOpen"] = bool(
                change == "offered" and owner is not None and pending_offer(owner) == role
            )
        if entry.kind in ("friend_request", "friend_accepted", "game_invite") and body.get("person") is None:
            continue
        rendered.append(body)
    return rendered


async def inbox_payload(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: str,
    *,
    before: str | None = None,
    limit: int = INBOX_PAGE,
) -> dict:
    """One page of the account's inbox, newest first, with the unread count,
    the warning still to be acknowledged and the role on offer."""
    target = UUID(user_id)
    async with session_factory() as session:
        identity_ids = list(await _identity_ids(session, target))
        unread = int(
            await session.scalar(
                select(func.count())
                .select_from(InboxEntry)
                .where(InboxEntry.user_id.in_(identity_ids), InboxEntry.read_at.is_(None))
            )
            or 0
        )
        query = select(InboxEntry).where(InboxEntry.user_id.in_(identity_ids))
        if before:
            try:
                anchor_id = UUID(before)
            except ValueError:
                anchor_id = None
            anchor = (
                await session.scalar(
                    select(InboxEntry).where(
                        InboxEntry.id == anchor_id, InboxEntry.user_id.in_(identity_ids)
                    )
                )
                if anchor_id is not None
                else None
            )
            if anchor is None:
                raise Refusal(404, ErrorCode.NO_SUCH_NOTICE, "No such inbox entry.")
            query = query.where(
                or_(
                    InboxEntry.created_at < anchor.created_at,
                    and_(
                        InboxEntry.created_at == anchor.created_at,
                        InboxEntry.id < anchor.id,
                    ),
                )
            )
        page = (
            await session.scalars(
                query.order_by(InboxEntry.created_at.desc(), InboxEntry.id.desc()).limit(
                    limit + 1
                )
            )
        ).all()
        has_more = len(page) > limit
        page = list(page[:limit])
        entries = await _render(session, page)
        owner = await session.get(User, identity_ids[0])
        pending_role = pending_offer(owner) if owner is not None else None
    warning = (await pending_warning_payload(session_factory, str(identity_ids[0])))["warning"]
    return {
        "entries": entries,
        "unreadCount": unread,
        "next": str(page[-1].id) if has_more and page else None,
        "mustAcknowledge": warning,
        "pendingRole": pending_role,
    }


class ReadBody(ControlFreeModel):
    """Entries to mark read, by id; or `all` of them."""

    ids: list[str] = Field(default_factory=list, max_length=MAX_READ_IDS)
    all: bool = False


def create_inbox_router(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    on_inbox_changed: Callable[[str], Awaitable[None]] | None = None,
) -> APIRouter:
    """`on_inbox_changed` tells the account's other tabs that something was
    read, so the count on every bell agrees (R-INBOX-03)."""
    router = APIRouter(prefix="/api/inbox")

    def caller(request: Request) -> str:
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise Refusal(401, ErrorCode.SIGN_IN_REQUIRED, "Sign in first.")
        return user_id

    @router.get("")
    async def read_inbox(request: Request, before: str | None = Query(default=None, max_length=64)):
        return await inbox_payload(session_factory, caller(request), before=before)

    @router.post("/read")
    async def mark_entries_read(body: ReadBody, request: Request):
        user_id = caller(request)
        ids: list[UUID] = []
        for raw in body.ids:
            try:
                ids.append(UUID(raw))
            except ValueError:
                continue
        async with session_factory() as session:
            async with session.begin():
                identity_ids = list(await _identity_ids(session, UUID(user_id)))
                marked = await mark_read(
                    session, user_ids=identity_ids, entry_ids=None if body.all else ids
                )
                unread = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(InboxEntry)
                        .where(
                            InboxEntry.user_id.in_(identity_ids),
                            InboxEntry.read_at.is_(None),
                        )
                    )
                    or 0
                )
        if marked and on_inbox_changed is not None:
            await on_inbox_changed(str(identity_ids[0]))
        return {"unreadCount": unread}

    return router


async def drawers_told_about_game(
    session_factory: async_sessionmaker[AsyncSession], game_id: str
) -> list[str]:
    """The drawers a finished game's live shares left an unread entry for -
    told once its history is in, since the shares were written with it
    (R-SHARE-09)."""
    try:
        target = UUID(game_id)
    except (ValueError, TypeError):
        return []
    async with session_factory() as session:
        rows = await session.scalars(
            select(InboxEntry.user_id)
            .join(TurnRecord, TurnRecord.id == InboxEntry.subject_id)
            .where(
                InboxEntry.kind == "drawing_shared",
                InboxEntry.read_at.is_(None),
                TurnRecord.game_id == target,
            )
            .distinct()
        )
        return sorted(str(user_id) for user_id in rows.all())
