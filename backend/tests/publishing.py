"""Publishing a list by hand, for tests that set its row directly.

A list is in the catalogue and playable by strangers when it is public *and*
has a live edition (#1360). Setting `visibility` alone, as these tests did
before editions, leaves a public list with nothing for anyone to see.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PromptList
from app.services.prompt_editions import (
    PUBLISHED,
    drop_editions,
    editions_of,
    snapshot_edition,
    working_copy_state,
)


async def publish_in_place(session: AsyncSession, row: PromptList, *, at: datetime) -> None:
    """What publishing writes: the row public, and its working copy live."""
    row.visibility = "public"
    row.published_at = at
    version_ids, tags, digest = await working_copy_state(session, row)
    live = (await editions_of(session, row.id)).get(PUBLISHED)
    if live is not None:
        if live.content_hash == digest:
            return
        await drop_editions(session, [live.id], now=at)
        await session.flush()
    await snapshot_edition(
        session, row, state=PUBLISHED, now=at, version_ids=version_ids, tags=tags, digest=digest
    )
