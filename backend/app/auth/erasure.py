"""The erasure barrier: what a writer of account-owned content checks first.

An account deletion (`anonymize_account`) erases what the account authored
and tombstones how it was presented, in one transaction that holds the
account row `FOR UPDATE`. That transaction can only erase what is already in
the database. A message composed a moment earlier and still waiting in the
retention queue, a finished game still being written, an avatar upload or a
list save that passed authentication before the deletion committed: each of
these would write the erased name, text, or pixels back afterwards (#606).
Authentication performed before a deletion is not authorization to commit
after it.

So every such writer, inside its own transaction, re-reads the lifecycle of
the accounts it is about to write for under a **shared lock** on their rows,
in ascending id order. Against a deletion in flight the shared lock waits for
the `FOR UPDATE` and then sees `deleted`; against a deletion that starts
later, the deletion's `FOR UPDATE` waits for the writer's commit and then
erases what was just written. Either order ends erased. Ordering the locks by
id is what keeps two writers, or a writer and two deletions, from waiting on
each other in a cycle.

SQLite renders neither lock and has one writer at a time, so there the
re-read alone is the barrier; the ordering guarantees are proven on
PostgreSQL only.
"""
from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IdentityAlias, User
from app.domain_values import AccountState

# What every historical snapshot of an erased identity is rewritten to.
DELETED_DISPLAY_NAME = "Deleted player"

# The snapshot triple (display name, name colour, is anonymous) a tombstoned
# seat carries, in the order the finished-game writer keeps them.
TOMBSTONE_SNAPSHOT: tuple[str, None, bool] = (DELETED_DISPLAY_NAME, None, True)


class AccountErasedError(RuntimeError):
    """The account this write is for has been deleted since it was authorized."""


async def erased_identity_ids(
    session: AsyncSession, user_ids: Iterable[UUID]
) -> set[UUID]:
    """Lock the given identities (shared, ascending) and say which are erased.

    An identity counts as erased when its own row is `deleted`, when the row
    is gone altogether (retention purged the guest), or when it is a merged
    guest whose account is `deleted` - the alias rows keep `merged` while the
    account they resolve to is the one that carries the state.
    """
    wanted = sorted({UUID(str(value)) for value in user_ids})
    if not wanted:
        return set()
    states = dict(
        (
            await session.execute(
                select(User.id, User.state)
                .where(User.id.in_(wanted))
                .order_by(User.id)
                .with_for_update(read=True)
            )
        ).all()
    )
    erased = {uid for uid in wanted if states.get(uid) in (None, AccountState.DELETED.value)}
    merged = [uid for uid in wanted if states.get(uid) == AccountState.MERGED.value]
    if merged:
        targets = dict(
            (
                await session.execute(
                    select(IdentityAlias.source_user_id, IdentityAlias.target_user_id)
                    .where(IdentityAlias.source_user_id.in_(merged))
                )
            ).all()
        )
        unknown_targets = sorted(set(targets.values()) - states.keys())
        if unknown_targets:
            states.update(
                (
                    await session.execute(
                        select(User.id, User.state)
                        .where(User.id.in_(unknown_targets))
                        .order_by(User.id)
                        .with_for_update(read=True)
                    )
                ).all()
            )
        for source in merged:
            target = targets.get(source)
            if target is None or states.get(target) in (None, AccountState.DELETED.value):
                erased.add(source)
    return erased


async def require_live_account(session: AsyncSession, user_id: UUID | str) -> None:
    """Refuse, inside the caller's transaction, to write for an erased account."""
    if await erased_identity_ids(session, (UUID(str(user_id)),)):
        raise AccountErasedError("account not found")
