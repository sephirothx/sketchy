"""Reclaiming prompt-list revisions nothing needs, without touching the games that played them.

A finished game used to pin the exact revision it drew from
(`game_prompt_sources`, `turn_prompt_offer_sources`, `prompt_usage_facts`,
RESTRICT), so deleting a list rolled back whole for every owner whose list a
game had played (#605), and a list became a **retired** tombstone instead:
`deleted_at` set, the visibility back to private, the current-display
`prompts` rows gone. From that moment nothing lists, opens, resolves or forks
it (R-LIST-01's "delete").

Since #1358 those tables name the list, not a revision, and nothing pins a
revision: the history reads the same without one, since each turn stores its
prompt text and version. `reclaim_retired_prompt_lists` runs from the hourly
retention sweep and, for lists retired longer than `RETIRED_LIST_GRACE` ago,
deletes their revisions and the list row - the game sources going with it,
the usage facts staying with the list set to null - then the prompt versions
and concepts that no revision, list, turn, offer, usage fact, report or
takedown record names any more.

The grace is for the room that drew from the list before it was retired and
is still playing (R-LIST-07): its finished-game write references the prompt
versions it drew, and they are still there within the grace. A day is far
longer than a game.

A live list's superseded revisions go the same way (#1258):
`reclaim_superseded_revisions`, also hourly, deletes a revision a newer save
replaced more than the grace ago, unless something still needs it
(`_superseded_reclaimable`), with the same orphan step after it.
"""
from __future__ import annotations

from dataclasses import dataclass
from app.services.sweeps import SweepBudget, SweepReport, overdue_probe
from datetime import datetime, timedelta, timezone
import logging
import time
from uuid import UUID

from sqlalchemy import delete, exists, func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.db.models import (
    GamePromptSource,
    Prompt,
    PromptConcept,
    PromptContentReport,
    PromptList,
    PromptListRevision,
    PromptListRevisionItem,
    PromptTakedown,
    PromptUsageFact,
    PromptVersion,
    TurnPromptOffer,
    TurnPromptOfferSource,
    TurnRecord,
)
from app.domain_values import (
    PromptListVisibility,
)

logger = logging.getLogger(__name__)

RETIRED_LIST_GRACE = timedelta(days=1)
RECLAIM_BATCH_LISTS = 50
# What a retired list's authored copy becomes when its owner is erased: the
# list row stays until the reclaim's grace passes, and nothing reads the name,
# so nothing is lost by not keeping it.
RETIRED_LIST_NAME = "Deleted list"


async def retire_prompt_list(
    session: AsyncSession,
    prompt_list: PromptList,
    *,
    now: datetime | None = None,
    erase_copy: bool = False,
) -> None:
    """Take a list out of reach, leaving the rest to the reclaim.

    `erase_copy` is the account-erasure case: the name and description are
    the account's authored copy and go with it. An owner deleting their own
    list keeps them on the tombstone; nothing reads them either way.
    """
    retired_at = now or datetime.now(timezone.utc)
    prompt_list.deleted_at = retired_at
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
    # Game sources removed and usage facts detached from the lists, in the
    # committed batches that come before any list is deleted (#1358).
    history_cleared: int = 0


def _reclaimable(cutoff: datetime):
    """A retired list past its grace.

    Nothing pins a revision any more: a finished game names its list, not a
    revision, and goes on reading the same without it (#1358). So every
    retired list past its grace is collected whole, and none lingers as a
    tombstone - the ones a game pinned used to, for ever, and needed a
    starvation guard to keep them out of the batch (#478).
    """
    return (PromptList.deleted_at.is_not(None), PromptList.deleted_at <= cutoff)


def _has_history(list_id):
    """Whether a finished game still names this list: a source row of the game
    or of an offer, or a usage fact (#1358)."""
    return (
        exists().where(GamePromptSource.prompt_list_id == list_id)
        | exists().where(TurnPromptOfferSource.prompt_list_id == list_id)
        | exists().where(PromptUsageFact.prompt_list_id == list_id)
    )


async def _drain_one_batch(
    session_factory: async_sessionmaker[AsyncSession],
    cutoff: datetime,
    limit: int,
    rows: int,
) -> int:
    """Clear up to `rows` of the history naming the oldest reclaimable lists,
    in one committed transaction; how many rows it cleared.

    Deleting a list removes its games' source rows and sets its usage facts'
    list to null, work that grows with how much the list was played rather
    than with the list (#1376 review). Done first, in bounded batches of
    deterministically ordered keys (R-PRIV-16), the list delete that follows
    cascades over nothing.
    """
    candidates = (
        select(PromptList.id)
        .where(*_reclaimable(cutoff))
        .order_by(PromptList.deleted_at, PromptList.id)
        .limit(limit)
    )
    cleared = 0
    async with session_factory() as session:
        async with session.begin():
            list_ids = list((await session.scalars(candidates)).all())
            if not list_ids:
                return 0
            for table, key in (
                (GamePromptSource, GamePromptSource.game_id),
                (TurnPromptOfferSource, TurnPromptOfferSource.offer_id),
            ):
                if cleared >= rows:
                    break
                doomed = (
                    select(table.prompt_list_id, key)
                    .where(table.prompt_list_id.in_(list_ids))
                    .order_by(table.prompt_list_id, key)
                    .limit(rows - cleared)
                )
                cleared += int(
                    (
                        await session.execute(
                            delete(table).where(
                                tuple_(table.prompt_list_id, key).in_(doomed)
                            )
                        )
                    ).rowcount
                    or 0
                )
            if cleared < rows:
                facts = (
                    select(PromptUsageFact.id)
                    .where(PromptUsageFact.prompt_list_id.in_(list_ids))
                    .order_by(PromptUsageFact.id)
                    .limit(rows - cleared)
                )
                cleared += int(
                    (
                        await session.execute(
                            update(PromptUsageFact)
                            .where(PromptUsageFact.id.in_(facts))
                            .values(prompt_list_id=None)
                            .execution_options(synchronize_session=False)
                        )
                    ).rowcount
                    or 0
                )
    return cleared


async def _drain_history(
    session_factory: async_sessionmaker[AsyncSession],
    cutoff: datetime,
    limit: int,
    budget: SweepBudget,
) -> int:
    """Clear reclaimable lists' history a committed batch at a time, within
    the budget's rows and seconds."""
    cleared = 0
    started = time.monotonic()
    while cleared < budget.rows and time.monotonic() - started < budget.seconds:
        batch = await _drain_one_batch(
            session_factory, cutoff, limit, min(budget.batch, budget.rows - cleared)
        )
        cleared += batch
        if batch == 0:
            break
    return cleared


def _version_is_referenced(version_id):
    return (
        exists().where(PromptListRevisionItem.prompt_version_id == version_id)
        | exists().where(Prompt.prompt_version_id == version_id)
        | exists().where(TurnRecord.prompt_version_id == version_id)
        | exists().where(TurnPromptOffer.prompt_version_id == version_id)
        | exists().where(PromptUsageFact.prompt_version_id == version_id)
        | exists().where(PromptContentReport.prompt_version_id == version_id)
    )


def _concept_is_taken_down(concept_id):
    # An owner's takedown record names the concept, and its versions are the
    # spellings the owner's saves compare against (#1357): they stay while it does.
    return exists().where(PromptTakedown.concept_id == concept_id)


async def reclaim_orphans(
    session: AsyncSession, candidate_version_ids: set[UUID]
) -> tuple[int, int]:
    """Delete the candidate versions nothing names any more, then the
    concepts left with no version and no list row: (versions, concepts)."""
    if not candidate_version_ids:
        return 0, 0
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
        (
            await session.execute(
                delete(PromptVersion).where(
                    PromptVersion.id.in_(candidate_version_ids),
                    ~_version_is_referenced(PromptVersion.id),
                    ~_concept_is_taken_down(PromptVersion.concept_id),
                )
            )
        ).rowcount
        or 0
    )
    concepts_deleted = 0
    if candidate_concept_ids:
        concepts_deleted = int(
            (
                await session.execute(
                    delete(PromptConcept).where(
                        PromptConcept.id.in_(candidate_concept_ids),
                        ~exists().where(PromptVersion.concept_id == PromptConcept.id),
                        ~exists().where(Prompt.concept_id == PromptConcept.id),
                    )
                )
            ).rowcount
            or 0
        )
    return versions_deleted, concepts_deleted


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
    run under one takes no more lists than the budget has rows, and clears no
    more play history than that either.

    First the history naming the oldest lists past their grace - their games'
    source rows, their usage facts' pointer - is cleared in committed batches
    within the budget (`_drain_history`): that work grows with how much a list
    was played rather than with the list, and a cascade from one list delete
    was a transaction of any size (#1376 review). Then one transaction over at
    most `limit` of those lists with nothing left naming them, oldest first:
    each list's revisions go, then the list row, then the versions and
    concepts those revisions were the last to reference. A list whose history
    outlasts the budget waits for the next run, still counted as backlog.

    Nothing pins a revision since #1358, so a list past its grace is
    collected whole: its revisions, then its row, then what only they named.
    """
    if budget is not None:
        limit = max(1, min(limit, budget.rows))
    cutoff = (now or datetime.now(timezone.utc)) - grace
    history_cleared = await _drain_history(
        session_factory, cutoff, limit, budget or SweepBudget()
    )
    revisions_deleted = lists_deleted = versions_deleted = concepts_deleted = 0
    async with session_factory() as session:
        async with session.begin():
            retired = (
                await session.scalars(
                    select(PromptList)
                    .where(*_reclaimable(cutoff), ~_has_history(PromptList.id))
                    .order_by(PromptList.deleted_at, PromptList.id)
                    .limit(limit)
                )
            ).all()
            if not retired:
                overdue_seconds, backlog = await _remaining(session_factory, cutoff)
                return ReclaimResult(
                    0, 0, 0, 0, 0,
                    oldest_overdue_seconds=overdue_seconds,
                    backlog=backlog,
                    history_cleared=history_cleared,
                )
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
            revisions_deleted = int(
                (
                    await session.execute(
                        delete(PromptListRevision).where(
                            PromptListRevision.prompt_list_id.in_(list_ids)
                        )
                    )
                ).rowcount
                or 0
            )
            # The list goes with them: a finished game's sources go with it,
            # and its usage facts stay with the list set to null (#1358).
            lists_deleted = int(
                (
                    await session.execute(
                        delete(PromptList).where(PromptList.id.in_(list_ids))
                    )
                ).rowcount
                or 0
            )

            versions_deleted, concepts_deleted = await reclaim_orphans(
                session, candidate_version_ids
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
        history_cleared=history_cleared,
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


# --- superseded revisions of live lists (#1258) -------------------------------

RECLAIM_BATCH_REVISIONS = 200
SUPERSEDED_SWEEP = "superseded_list_revisions"


def _successor():
    """The revisions of the same list saved after the one in the outer query."""
    return aliased(PromptListRevision)


def _superseded_since():
    """When the outer query's revision stopped being current: its successor's
    creation, the earliest of the revisions saved after it."""
    newer = _successor()
    return (
        select(func.min(newer.created_at))
        .where(
            newer.prompt_list_id == PromptListRevision.prompt_list_id,
            newer.version > PromptListRevision.version,
        )
        .scalar_subquery()
    )


def _superseded_reclaimable(cutoff: datetime):
    """A revision of a live, owned list the sweep may delete.

    Replaced by a newer save more than the grace ago - the same day the
    retired-list reclaim waits, for the same room: one that pinned this
    revision when its game started and is still playing it - and kept for
    good while anything needs it: a fork that says it
    was copied from here (R-LIST-20's copy count reads that), a copy's own
    first revision (the one that says what it was copied from: the count, the
    credit and the lineage all read it, so editing a copy would otherwise
    erase all three a day later). A hidden word is not a hold: the owner's
    takedown record keeps it (#1357). The current revision is never superseded, so never a candidate.
    """
    newer = _successor()
    fork = aliased(PromptListRevision)
    return (
        PromptList.id == PromptListRevision.prompt_list_id,
        PromptList.deleted_at.is_(None),
        PromptList.is_bundled.is_(False),
        exists().where(
            newer.prompt_list_id == PromptListRevision.prompt_list_id,
            newer.version > PromptListRevision.version,
            newer.created_at <= cutoff,
        ),
        ~exists().where(fork.forked_from_revision_id == PromptListRevision.id),
        PromptListRevision.forked_from_revision_id.is_(None),
    )


async def reclaim_superseded_revisions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    grace: timedelta = RETIRED_LIST_GRACE,
    limit: int = RECLAIM_BATCH_REVISIONS,
    budget: SweepBudget | None = None,
) -> SweepReport:
    """Delete superseded, unneeded revisions of live lists, a bounded batch at a time.

    Bounded by the budget's rows, counting each revision's item rows: one
    transaction per pass, oldest superseded first.

    Every content save writes the whole list again as a new revision, and
    only retired lists were ever reclaimed, so a live list kept every
    revision it was ever saved as: storage grew with saves, not with lists -
    500 rows a save of a 500-prompt list - and the owner's export with it,
    until it passed its ceiling for good (#1258, #1250). What a live list
    keeps now is its current revision, every revision still inside the
    grace, and the revisions something needs (`_superseded_reclaimable`);
    versions and concepts only those revisions named go with them.
    """
    # Rows, not revisions: a revision of a 500-prompt list is 500 item rows,
    # so the budget's row allowance decides how many a pass deletes - at
    # least one, whatever its size.
    row_budget = (budget or SweepBudget()).rows
    limit = max(1, min(limit, row_budget))
    started = time.monotonic()
    cutoff = (now or datetime.now(timezone.utc)) - grace
    revisions_deleted = versions_deleted = concepts_deleted = 0
    candidates = 0
    async with session_factory() as session:
        async with session.begin():
            items = aliased(PromptListRevisionItem)
            sized = (
                await session.execute(
                    select(
                        PromptListRevision.id,
                        select(func.count())
                        .where(items.revision_id == PromptListRevision.id)
                        .scalar_subquery(),
                    )
                    .where(*_superseded_reclaimable(cutoff))
                    .order_by(PromptListRevision.created_at, PromptListRevision.id)
                    .limit(limit)
                )
            ).all()
            candidates = len(sized)
            doomed: list[UUID] = []
            spent = 0
            for revision_id, items in sized:
                if doomed and spent + items + 1 > row_budget:
                    break
                doomed.append(revision_id)
                spent += items + 1
            if doomed:
                candidate_version_ids = set(
                    (
                        await session.scalars(
                            select(PromptListRevisionItem.prompt_version_id.distinct()).where(
                                PromptListRevisionItem.revision_id.in_(doomed)
                            )
                        )
                    ).all()
                )
                revisions_deleted = int(
                    (
                        await session.execute(
                            delete(PromptListRevision).where(PromptListRevision.id.in_(doomed))
                        )
                    ).rowcount
                    or 0
                )
                versions_deleted, concepts_deleted = await reclaim_orphans(
                    session, candidate_version_ids
                )
    probe = overdue_probe(_superseded_since(), *_superseded_reclaimable(cutoff))
    async with session_factory() as session:
        earliest = await session.scalar(probe.oldest)
        backlog = int(await session.scalar(probe.backlog) or 0)
    overdue = 0.0
    if earliest is not None:
        if earliest.tzinfo is None:
            earliest = earliest.replace(tzinfo=timezone.utc)
        overdue = max(0.0, (cutoff - earliest).total_seconds())
    if revisions_deleted:
        logger.info(
            "prompt reclaim: %d superseded revisions of live lists, %d versions, %d concepts removed",
            revisions_deleted,
            versions_deleted,
            concepts_deleted,
        )
    return SweepReport(
        revisions_deleted,
        name=SUPERSEDED_SWEEP,
        batches=1 if revisions_deleted else 0,
        seconds=time.monotonic() - started,
        exhausted=revisions_deleted < candidates or revisions_deleted >= limit,
        oldest_overdue_seconds=overdue,
        backlog=backlog,
        detail={"versions": versions_deleted, "concepts": concepts_deleted},
    )


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
