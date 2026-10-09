"""Writing to an account's inbox (#1436, R-INBOX-01).

Every write here joins the caller's transaction, so an entry commits with the
fact it is about - a warning, a share, a friendship, a role - or not at all:
there is no fact nobody was told about and no message about a fact that
rolled back. Telling a connected account that its inbox moved is the caller's
job once its commit has landed (`inbox_changed`, see `main.py`).

An entry names its fact by `subject_id` where there is one row or account to
name, and the inbox holds one entry per subject per kind: a second share of a
drawing says nothing the first did not. Some kinds `renew` instead - a friend
request asked again after it was cancelled, a second invitation from the same
friend - which brings the one entry back to the top, unread.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InboxEntry, generate_uuid

__all__ = [
    "INBOX_RETENTION_DAYS",
    "add_entry",
    "count_reviewed_reports",
    "forget_subjects",
    "mark_read",
]

#: How long an entry is kept, read or not (R-INBOX-06). An entry is only the
#: message; the fact behind it keeps its own retention. Ninety days is a
#: player session's idle window (R-AUTH-03): an absence longer than that is a
#: fresh sign-in anyway.
INBOX_RETENTION_DAYS = 90


def _insert(session: AsyncSession):
    return (
        postgresql_insert
        if session.get_bind().dialect.name == "postgresql"
        else sqlite_insert
    )


async def add_entry(
    session: AsyncSession,
    *,
    user_id: UUID | str,
    kind: str,
    subject_id: UUID | str | None = None,
    params: dict | None = None,
    created_at: datetime | None = None,
    renew: bool = False,
) -> bool:
    """Put one entry in an account's inbox, in the caller's transaction.

    Answers whether the inbox moved - an entry written, or one renewed - so
    the caller knows whether there is anybody to tell. With a subject the
    entry is the one for that subject: left alone when it is already there,
    or with `renew`, brought back to the top and marked unread."""
    at = created_at or datetime.now(timezone.utc)
    values = {
        "id": generate_uuid(),
        "user_id": UUID(str(user_id)),
        "kind": kind,
        "subject_id": UUID(str(subject_id)) if subject_id is not None else None,
        "params": params or {},
        "created_at": at,
        "read_at": None,
    }
    if subject_id is None:
        session.add(InboxEntry(**values))
        return True
    statement = _insert(session)(InboxEntry).values(values)
    target = {
        "index_elements": ["user_id", "kind", "subject_id"],
        "index_where": text("subject_id IS NOT NULL"),
    }
    if renew:
        statement = statement.on_conflict_do_update(
            **target,
            set_={"created_at": at, "read_at": None, "params": values["params"]},
        )
    else:
        statement = statement.on_conflict_do_nothing(**target)
    result = await session.execute(statement)
    return bool(result.rowcount)


async def count_reviewed_reports(
    session: AsyncSession,
    reporter_ids: dict[UUID, int],
    *,
    now: datetime | None = None,
) -> list[UUID]:
    """Tell each reporter how many of their reports were just decided.

    Counted into the reporter's unread entry when there is one, so a
    moderator working through a queue leaves one line - "3 reports you sent
    have been reviewed" - rather than three. Only that they were reviewed:
    what was decided is the reported player's business (R-MOD-20). Answers
    the reporters whose inbox moved."""
    at = now or datetime.now(timezone.utc)
    moved: list[UUID] = []
    for reporter_id, count in sorted(reporter_ids.items(), key=lambda item: str(item[0])):
        if count <= 0:
            continue
        unread = await session.scalar(
            select(InboxEntry)
            .where(
                InboxEntry.user_id == reporter_id,
                InboxEntry.kind == "reports_reviewed",
                InboxEntry.read_at.is_(None),
            )
            .order_by(InboxEntry.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if unread is not None:
            unread.params = {"count": int(unread.params.get("count", 0)) + count}
            unread.created_at = at
        else:
            await add_entry(
                session,
                user_id=reporter_id,
                kind="reports_reviewed",
                params={"count": count},
                created_at=at,
            )
        moved.append(reporter_id)
    return moved


async def forget_subjects(
    session: AsyncSession,
    *,
    kinds: tuple[str, ...],
    subject_ids: list[UUID],
    user_ids: list[UUID] | None = None,
) -> None:
    """Delete the entries about facts that are gone - a friend request
    withdrawn, a friendship ended, an account erased - so the inbox does not
    keep offering an answer to something nobody is asking any more."""
    if not subject_ids:
        return
    where = [InboxEntry.kind.in_(kinds), InboxEntry.subject_id.in_(subject_ids)]
    if user_ids is not None:
        where.append(InboxEntry.user_id.in_(user_ids))
    await session.execute(delete(InboxEntry).where(*where))


async def mark_read(
    session: AsyncSession,
    *,
    user_ids: list[UUID],
    kind: str | None = None,
    subject_id: UUID | None = None,
    entry_ids: list[UUID] | None = None,
    now: datetime | None = None,
) -> int:
    """Mark entries read: named ones, every one about a subject, or all.

    Scoped to the account's own identities in every form, so an id that is
    somebody else's entry reads nothing."""
    where = [InboxEntry.user_id.in_(user_ids), InboxEntry.read_at.is_(None)]
    if kind is not None:
        where.append(InboxEntry.kind == kind)
    if subject_id is not None:
        where.append(InboxEntry.subject_id == subject_id)
    if entry_ids is not None:
        if not entry_ids:
            return 0
        where.append(InboxEntry.id.in_(entry_ids))
    result = await session.execute(
        update(InboxEntry)
        .where(and_(*where))
        .values(read_at=now or datetime.now(timezone.utc))
    )
    return int(result.rowcount or 0)
