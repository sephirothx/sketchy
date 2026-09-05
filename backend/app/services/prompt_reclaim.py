"""Retiring owned prompt lists without touching the games that played them.

Deleting a list used to delete its revisions, and an account deletion its
concepts too. A finished game pins the exact revision it drew from
(`game_prompt_sources`, `turn_prompt_offer_sources`, `prompt_usage_facts`,
all RESTRICT or CASCADE onto facts), so for every owner who had ever played a
saved list, both deletions rolled back whole (#605). The RESTRICTs are right:
another player's history must not lose its provenance because its author
tidied up (R-PRIV-05). What they were protecting against was the wrong
deletion.

So a list is **retired**, not deleted: `deleted_at` is set, the share code is
revoked, the visibility falls back to private, and the current-display
`prompts` rows go. From that moment nothing lists, opens, resolves or forks
it (R-LIST-01's "delete"). The immutable revisions stay behind exactly as
long as something pins them. `reclaim_retired_prompt_lists` runs from the
hourly retention sweep and, for lists retired longer than
`RETIRED_LIST_GRACE` ago, deletes the revisions nothing references, then the
list row once it has none, then the prompt versions and concepts that no
revision, list, turn, offer, usage fact or report names any more.

The grace is for the room that pinned a revision before the list was retired
and is still playing (R-LIST-07): its finished-game write lands within the
grace and lands intact, because the revision is still there to be
referenced. A day is far longer than a game.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from uuid import UUID

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    GamePromptSource,
    Prompt,
    PromptConcept,
    PromptContentReport,
    PromptList,
    PromptListRevision,
    PromptListRevisionItem,
    PromptUsageFact,
    PromptVersion,
    TurnPromptOffer,
    TurnPromptOfferSource,
    TurnRecord,
)
from app.domain_values import PromptListVisibility

logger = logging.getLogger(__name__)

RETIRED_LIST_GRACE = timedelta(days=1)
RECLAIM_BATCH_LISTS = 50
# What a retired list's authored copy becomes when its owner is erased: the
# list row has to stay while a game pins one of its revisions, and nothing
# reads the name, so nothing is lost by not keeping it.
RETIRED_LIST_NAME = "Deleted list"


async def retire_prompt_list(
    session: AsyncSession,
    prompt_list: PromptList,
    *,
    now: datetime | None = None,
    erase_copy: bool = False,
) -> None:
    """Take a list out of reach, keeping what played games pin.

    `erase_copy` is the account-erasure case: the name and description are
    the account's authored copy and go with it. An owner deleting their own
    list keeps them on the tombstone; nothing reads them either way.
    """
    retired_at = now or datetime.now(timezone.utc)
    prompt_list.deleted_at = retired_at
    prompt_list.share_code = None
    prompt_list.visibility = PromptListVisibility.PRIVATE.value
    if erase_copy:
        prompt_list.name = RETIRED_LIST_NAME
        prompt_list.description = ""
    await session.execute(delete(Prompt).where(Prompt.prompt_list_id == prompt_list.id))


@dataclass(frozen=True)
class ReclaimResult:
    lists_examined: int
    revisions_deleted: int
    lists_deleted: int
    versions_deleted: int
    concepts_deleted: int


def _revision_is_pinned(revision_id):
    return (
        exists().where(GamePromptSource.prompt_list_revision_id == revision_id)
        | exists().where(TurnPromptOfferSource.prompt_list_revision_id == revision_id)
        | exists().where(PromptUsageFact.prompt_list_revision_id == revision_id)
    )


def _version_is_referenced(version_id):
    return (
        exists().where(PromptListRevisionItem.prompt_version_id == version_id)
        | exists().where(Prompt.prompt_version_id == version_id)
        | exists().where(TurnRecord.prompt_version_id == version_id)
        | exists().where(TurnPromptOffer.prompt_version_id == version_id)
        | exists().where(PromptUsageFact.prompt_version_id == version_id)
        | exists().where(PromptContentReport.prompt_version_id == version_id)
    )


async def reclaim_retired_prompt_lists(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    grace: timedelta = RETIRED_LIST_GRACE,
    limit: int = RECLAIM_BATCH_LISTS,
) -> ReclaimResult:
    """Physically remove what retired lists no longer need, a bounded batch at a time.

    One transaction per run, over at most `limit` lists retired before
    `now - grace`, oldest first. Each list's unpinned revisions go, then the
    list row if no revision is left, then the versions and concepts those
    revisions were the last to reference. A list that is still pinned stays
    as a non-discoverable tombstone and is examined again next run, which
    costs one indexed select.
    """
    cutoff = (now or datetime.now(timezone.utc)) - grace
    revisions_deleted = lists_deleted = versions_deleted = concepts_deleted = 0
    async with session_factory() as session:
        async with session.begin():
            retired = (
                await session.scalars(
                    select(PromptList)
                    .where(
                        PromptList.deleted_at.is_not(None),
                        PromptList.deleted_at <= cutoff,
                    )
                    .order_by(PromptList.deleted_at, PromptList.id)
                    .limit(limit)
                )
            ).all()
            if not retired:
                return ReclaimResult(0, 0, 0, 0, 0)
            list_ids = [row.id for row in retired]

            # Every version the doomed revisions name: the candidates for
            # orphan reclaim once the memberships are gone.
            candidate_version_ids = set(
                (
                    await session.scalars(
                        select(PromptListRevisionItem.prompt_version_id)
                        .join(
                            PromptListRevision,
                            PromptListRevision.id == PromptListRevisionItem.revision_id,
                        )
                        .where(PromptListRevision.prompt_list_id.in_(list_ids))
                    )
                ).all()
            )
            unpinned = delete(PromptListRevision).where(
                PromptListRevision.prompt_list_id.in_(list_ids),
                ~_revision_is_pinned(PromptListRevision.id),
            )
            revisions_deleted = int((await session.execute(unpinned)).rowcount or 0)

            still_pinned = set(
                (
                    await session.scalars(
                        select(PromptListRevision.prompt_list_id.distinct()).where(
                            PromptListRevision.prompt_list_id.in_(list_ids)
                        )
                    )
                ).all()
            )
            gone = [list_id for list_id in list_ids if list_id not in still_pinned]
            if gone:
                lists_deleted = int(
                    (
                        await session.execute(
                            delete(PromptList).where(PromptList.id.in_(gone))
                        )
                    ).rowcount
                    or 0
                )

            if candidate_version_ids:
                orphan_versions = delete(PromptVersion).where(
                    PromptVersion.id.in_(candidate_version_ids),
                    ~_version_is_referenced(PromptVersion.id),
                )
                candidate_concept_ids = set(
                    (
                        await session.scalars(
                            select(PromptVersion.concept_id.distinct()).where(
                                PromptVersion.id.in_(candidate_version_ids)
                            )
                        )
                    ).all()
                )
                versions_deleted = int(
                    (await session.execute(orphan_versions)).rowcount or 0
                )
                if candidate_concept_ids:
                    orphan_concepts = delete(PromptConcept).where(
                        PromptConcept.id.in_(candidate_concept_ids),
                        ~exists().where(PromptVersion.concept_id == PromptConcept.id),
                        ~exists().where(Prompt.concept_id == PromptConcept.id),
                    )
                    concepts_deleted = int(
                        (await session.execute(orphan_concepts)).rowcount or 0
                    )
    result = ReclaimResult(
        lists_examined=len(retired),
        revisions_deleted=revisions_deleted,
        lists_deleted=lists_deleted,
        versions_deleted=versions_deleted,
        concepts_deleted=concepts_deleted,
    )
    if revisions_deleted or lists_deleted or versions_deleted or concepts_deleted:
        logger.info(
            "prompt reclaim: %d retired lists examined, %d revisions, %d lists, "
            "%d versions, %d concepts removed",
            *(
                result.lists_examined,
                revisions_deleted,
                lists_deleted,
                versions_deleted,
                concepts_deleted,
            ),
        )
    return result


async def retire_owned_lists(
    session: AsyncSession, owner_ids: list[UUID], *, now: datetime
) -> int:
    """Account erasure: retire every list the identities own, copy erased.

    A list the owner had already retired is retired again with its copy
    erased; its `deleted_at` keeps the earlier time, so the sweep's grace is
    not restarted by the erasure.
    """
    lists = (
        await session.scalars(
            select(PromptList)
            .where(
                PromptList.owner_user_id.in_(owner_ids),
                PromptList.is_bundled.is_(False),
            )
            .with_for_update()
        )
    ).all()
    for prompt_list in lists:
        already = prompt_list.deleted_at
        await retire_prompt_list(session, prompt_list, now=now, erase_copy=True)
        if already is not None:
            prompt_list.deleted_at = already
    return len(lists)
