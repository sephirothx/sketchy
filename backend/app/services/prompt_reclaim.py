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
from app.services.sweeps import SweepBudget, overdue_probe
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
    # What the run left behind, over reclaimable lists only: the age of the
    # oldest one still past its grace, and how many there are (#478).
    oldest_overdue_seconds: float = 0.0
    backlog: int = 0


def _revision_is_pinned(revision_id):
    return (
        exists().where(GamePromptSource.prompt_list_revision_id == revision_id)
        | exists().where(TurnPromptOfferSource.prompt_list_revision_id == revision_id)
        | exists().where(PromptUsageFact.prompt_list_revision_id == revision_id)
    )


def _has_reclaimable_work(list_id):
    """Whether this retired list still has anything for the reclaim to do.

    A revision a finished game pins is permanent - the pin is that game's
    provenance and never lapses - so a tombstone whose every remaining
    revision is pinned has no work left, ever. Without this predicate such a
    list is still selected: the batch takes the oldest retired lists, the
    permanent ones are the oldest by construction, and once there are `limit`
    of them they are the whole batch for every future run. Every list retired
    afterwards then waits behind them indefinitely, while the sweep runs
    hourly and reports success (#478).

    Evaluated fresh each run rather than recorded, so a list becomes a
    candidate again by itself if a pin ever does go away.
    """
    revisions = select(PromptListRevision.id).where(
        PromptListRevision.prompt_list_id == list_id
    )
    return ~revisions.exists() | revisions.where(
        ~_revision_is_pinned(PromptListRevision.id)
    ).exists()


def _reclaimable(cutoff: datetime):
    """A retired list past its grace that the sweep can still act on."""
    return (
        PromptList.deleted_at.is_not(None),
        PromptList.deleted_at <= cutoff,
        _has_reclaimable_work(PromptList.id),
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


async def _remaining(
    session_factory: async_sessionmaker[AsyncSession], cutoff: datetime
) -> tuple[float, int]:
    """How far behind the reclaim is, over the lists it could still collect.

    Measured against `cutoff` rather than the clock, so the age is time spent
    past the grace and not the tombstone's own age. Zero rather than absent
    when there is nothing waiting: a series that appears only while a sweep
    is behind cannot be alerted on.
    """
    probe = overdue_probe(PromptList.deleted_at, *_reclaimable(cutoff))
    async with session_factory() as session:
        earliest = await session.scalar(probe.oldest)
        backlog = int(await session.scalar(probe.backlog) or 0)
    if earliest is None:
        return 0.0, backlog
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=timezone.utc)
    return max(0.0, (cutoff - earliest).total_seconds()), backlog


async def reclaim_retired_prompt_lists(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    grace: timedelta = RETIRED_LIST_GRACE,
    limit: int = RECLAIM_BATCH_LISTS,
    budget: SweepBudget | None = None,
) -> ReclaimResult:
    """Physically remove what retired lists no longer need, a bounded batch at a time.

    Scheduled by the retention loop, which hands every sweep its budget; a
    run under one takes no more lists than the budget has rows.

    One transaction per run, over at most `limit` lists retired before
    `now - grace` **that still have something to collect**, oldest first.
    Each list's unpinned revisions go, then the list row if no revision is
    left, then the versions and concepts those revisions were the last to
    reference.

    A list whose every remaining revision is pinned stays as a
    non-discoverable tombstone for ever, and is not selected at all: it is
    exempt rather than pending, and selecting it would let a handful of
    permanent tombstones fill the batch and starve every list retired after
    them (`_has_reclaimable_work`). What the run leaves is measured over the
    lists it could still collect, so the one sweep whose starvation would
    otherwise be unbounded is held to its SLA like the rest (#478).
    """
    if budget is not None:
        limit = max(1, min(limit, budget.rows))
    cutoff = (now or datetime.now(timezone.utc)) - grace
    revisions_deleted = lists_deleted = versions_deleted = concepts_deleted = 0
    async with session_factory() as session:
        async with session.begin():
            retired = (
                await session.scalars(
                    select(PromptList)
                    .where(*_reclaimable(cutoff))
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
    overdue_seconds, backlog = await _remaining(session_factory, cutoff)
    result = ReclaimResult(
        lists_examined=len(retired),
        revisions_deleted=revisions_deleted,
        lists_deleted=lists_deleted,
        versions_deleted=versions_deleted,
        concepts_deleted=concepts_deleted,
        oldest_overdue_seconds=overdue_seconds,
        backlog=backlog,
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
