"""Recording which words an owner may not type back in, and forgetting them.

A moderator hiding a prompt reaches every list its owner saves (R-MOD-11), so
the takedown is recorded per owner in `prompt_takedowns` (#1357). The decision
writes the rows, a save that carries the decision onto a new concept writes
one for it, and a decision that leaves the word up or the account's deletion
removes them.

Both halves are here because both have a trap. Two decisions on one concept
can each find no row and both insert, so the insert ignores a row that is
already there rather than failing the second decision. And a row keeps its
concept's versions from the orphan collection - they are the spellings a save
compares against - while the sweep only ever looks at versions a revision it is
deleting named: a version kept by a row after its revisions went is a
candidate nowhere else, so removing the row has to offer its versions to the
collection there and then, or the hidden text stays for good.
"""
from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PromptTakedown, PromptVersion
from app.services.prompt_reclaim import reclaim_orphans


async def record_takedowns(
    session: AsyncSession, rows: Iterable[tuple[UUID, UUID]]
) -> None:
    """Record (owner, concept) pairs, leaving any already recorded alone."""
    values = [
        {"owner_user_id": owner_id, "concept_id": concept_id}
        for owner_id, concept_id in sorted(set(rows))
    ]
    if not values:
        return
    insert = (
        postgresql_insert
        if session.get_bind().dialect.name == "postgresql"
        else sqlite_insert
    )
    await session.execute(
        insert(PromptTakedown).values(values).on_conflict_do_nothing(
            index_elements=["owner_user_id", "concept_id"]
        )
    )


async def release_takedowns(session: AsyncSession, *where) -> None:
    """Remove the rows `where` selects, and collect the versions they kept."""
    concept_ids = set(
        (
            await session.scalars(
                delete(PromptTakedown).where(*where).returning(PromptTakedown.concept_id)
            )
        ).all()
    )
    if not concept_ids:
        return
    versions = set(
        (
            await session.scalars(
                select(PromptVersion.id).where(PromptVersion.concept_id.in_(concept_ids))
            )
        ).all()
    )
    await reclaim_orphans(session, versions)
