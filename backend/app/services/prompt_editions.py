"""Publishing a prompt list as an immutable edition, and retiring editions (#1360).

A list's working copy is what its owner edits; an **edition** is what other
players see. Publishing snapshots the working copy into a new edition - its
prompts in order, tags, name, description and letter histogram - and the
catalogue, the rooms that do not own the list, copies and reports all read
that edition. The owner keeps editing the working copy without any of it
moving, and **Publish update** makes the next edition.

A list has at most one `published` (live) and one `under_review` (pending)
edition. A new edition that is published replaces the live one; one that goes
under review - R-LIST-13's operator switch - leaves the live one playing until a
moderator clears it, which is the unit a future review team approves (#1184).
A replaced or withdrawn edition is deleted rather than kept: games and copies
point at editions `SET NULL`, so nothing needs one once it stops being served,
and its prompt versions are stamped `unlisted_at` for the collection a grace
later, like a wording a save drops (#1359).
"""
from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime
import hashlib
import json
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Prompt,
    PromptList,
    PromptListEdition,
    PromptListEditionItem,
    PromptListEditionTag,
    PromptListTag,
    PromptTag,
    PromptVersion,
    generate_uuid,
)
from app.prompt_content import LIST_TAG_SLUG_ORDER

PUBLISHED = "published"
UNDER_REVIEW = "under_review"


def content_hash(
    *,
    language: str,
    name: str,
    description: str,
    tags: Sequence[str],
    version_ids: Sequence[UUID],
) -> str:
    """What an edition holds, as one digest: equal for equal content.

    The working copy is hashed the same way, which is how the owner's editor
    is told whether players see what it shows (unpublished changes, #1363).
    """
    payload = {
        "language": language,
        "name": name,
        "description": description,
        "tags": [slug for slug in LIST_TAG_SLUG_ORDER if slug in set(tags)],
        "prompts": [str(version_id) for version_id in version_ids],
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


async def working_copy_state(
    session: AsyncSession, prompt_list: PromptList
) -> tuple[list[UUID], tuple[str, ...], str]:
    """The working copy's versions in order, its tags, and its content hash."""
    version_ids = list(
        (
            await session.scalars(
                select(Prompt.prompt_version_id)
                .where(Prompt.prompt_list_id == prompt_list.id)
                .order_by(Prompt.position, Prompt.id)
            )
        ).all()
    )
    tags = tuple(
        (
            await session.scalars(
                select(PromptTag.slug)
                .join(PromptListTag, PromptListTag.tag_id == PromptTag.id)
                .where(PromptListTag.prompt_list_id == prompt_list.id)
            )
        ).all()
    )
    digest = content_hash(
        language=prompt_list.language,
        name=prompt_list.name,
        description=prompt_list.description,
        tags=tags,
        version_ids=version_ids,
    )
    return version_ids, tags, digest


async def editions_of(
    session: AsyncSession, prompt_list_id: UUID
) -> dict[str, PromptListEdition]:
    """The list's live and pending editions, by state."""
    return {
        edition.state: edition
        for edition in (
            await session.scalars(
                select(PromptListEdition).where(
                    PromptListEdition.prompt_list_id == prompt_list_id
                )
            )
        ).all()
    }


async def drop_editions(
    session: AsyncSession, edition_ids: Collection[UUID], *, now: datetime
) -> None:
    """Delete these editions, stamping the versions they held for the
    collection a grace later: a game that drew from one still writes its
    versions into its turns when it ends (#1359), and a reader with the
    catalogue page open may still report one (#1385 review).

    The versions are locked in id order first, as every multi-row version
    writer takes them; one the working copy or another edition still holds
    is unstamped by the sweep, which finds it named."""
    if not edition_ids:
        return
    editions = (
        await session.execute(
            select(PromptListEdition.id, PromptListEdition.prompt_list_id).where(
                PromptListEdition.id.in_(list(edition_ids))
            )
        )
    ).all()
    for edition_id, prompt_list_id in editions:
        held = PromptVersion.id.in_(
            select(PromptListEditionItem.prompt_version_id).where(
                PromptListEditionItem.edition_id == edition_id
            )
        )
        await session.execute(
            select(PromptVersion.id).where(held).order_by(PromptVersion.id).with_for_update()
        )
        await session.execute(
            update(PromptVersion)
            .where(held)
            .values(unlisted_at=now, unlisted_from_list_id=prompt_list_id)
            .execution_options(synchronize_session=False)
        )
    await session.execute(
        delete(PromptListEdition).where(PromptListEdition.id.in_(list(edition_ids)))
    )


async def snapshot_edition(
    session: AsyncSession,
    prompt_list: PromptList,
    *,
    state: str,
    now: datetime,
    version_ids: Sequence[UUID],
    tags: Sequence[str],
    digest: str,
) -> PromptListEdition:
    """Write the working copy as the list's next edition, in `state`.

    The caller holds the list row `FOR UPDATE` and has made room: a list has
    at most one edition in each state.
    """
    prompt_list.edition_count += 1
    edition = PromptListEdition(
        id=generate_uuid(),
        prompt_list_id=prompt_list.id,
        number=prompt_list.edition_count,
        state=state,
        name=prompt_list.name,
        description=prompt_list.description,
        language=prompt_list.language,
        content_hash=digest,
        letter_counts=dict(prompt_list.letter_counts or {}),
        letter_total=prompt_list.letter_total or 0,
        created_at=now,
        published_at=now if state == PUBLISHED else None,
    )
    session.add(edition)
    await session.flush()
    session.add_all(
        PromptListEditionItem(
            edition_id=edition.id, prompt_version_id=version_id, position=position
        )
        for position, version_id in enumerate(version_ids)
    )
    if tags:
        tag_ids = (
            await session.scalars(select(PromptTag.id).where(PromptTag.slug.in_(list(tags))))
        ).all()
        session.add_all(
            PromptListEditionTag(edition_id=edition.id, tag_id=tag_id) for tag_id in tag_ids
        )
    return edition


async def promote_pending(
    session: AsyncSession, prompt_list_id: UUID, *, now: datetime
) -> PromptListEdition | None:
    """A moderator cleared the pending edition: it goes live, and the edition
    it replaces is dropped. None when there is nothing pending."""
    editions = await editions_of(session, prompt_list_id)
    pending = editions.get(UNDER_REVIEW)
    if pending is None:
        return None
    live = editions.get(PUBLISHED)
    if live is not None:
        await drop_editions(session, [live.id], now=now)
        # Gone before the pending one takes its state: one live per list.
        await session.flush()
    pending.state = PUBLISHED
    pending.published_at = now
    return pending
