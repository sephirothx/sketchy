"""Reclaiming deleted lists and unlisted prompt versions nothing needs, without touching the games that played them.

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

A save writes no revision since #1359: it overwrites the list's working copy
and stamps the versions it takes out of it, and `reclaim_unlisted_versions`
collects those a grace later when nothing names them. The superseded-revision
sweep that bounded a live list's revisions (#1258) went with the revisions it
swept.
"""
from __future__ import annotations

from dataclasses import dataclass
from app.services.sweeps import SweepBudget, SweepReport, overdue_probe
from datetime import datetime, timedelta, timezone
import logging
import time
from uuid import UUID

from sqlalchemy import delete, exists, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
    # Its working copy's versions leave it now; a room that drew them before
    # the deletion still writes them, so they are collected a grace later.
    held = PromptVersion.id.in_(
        select(Prompt.prompt_version_id).where(Prompt.prompt_list_id == prompt_list.id)
    )
    # In id order, as every multi-row version write takes them (#1385 review).
    await session.execute(
        select(PromptVersion.id).where(held).order_by(PromptVersion.id).with_for_update()
    )
    await session.execute(
        update(PromptVersion)
        .where(held)
        .values(unlisted_at=retired_at, unlisted_from_list_id=prompt_list.id)
        .execution_options(synchronize_session=False)
    )
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
    # Whether the run stopped on its budget with work still owed, which is
    # what makes the retention loop schedule the next run sooner.
    exhausted: bool = False


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
                # In the order of `ix_prompt_usage_facts_list_occurred_at`,
                # so a batch reads its slice rather than the whole list's.
                facts = (
                    select(PromptUsageFact.id)
                    .where(PromptUsageFact.prompt_list_id.in_(list_ids))
                    .order_by(
                        PromptUsageFact.prompt_list_id,
                        PromptUsageFact.occurred_at,
                        PromptUsageFact.id,
                    )
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
) -> tuple[int, bool]:
    """Clear reclaimable lists' history a committed batch at a time, within
    the budget's rows and seconds: (rows cleared, whether the budget ran out
    before the history did)."""
    cleared = 0
    started = time.monotonic()
    while cleared < budget.rows and time.monotonic() - started < budget.seconds:
        batch = await _drain_one_batch(
            session_factory, cutoff, limit, min(budget.batch, budget.rows - cleared)
        )
        cleared += batch
        if batch == 0:
            return cleared, False
    return cleared, True


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
    history_cleared, drain_cut_short = await _drain_history(
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
                    exhausted=drain_cut_short and backlog > 0,
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
        # Cut short with lists still owed: the retention loop comes back
        # sooner rather than in an hour (R-PRIV-16), or a popular list's
        # history drains at one budget an hour and outlives its SLA.
        exhausted=backlog > 0 and (drain_cut_short or len(retired) >= limit),
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


UNLISTED_SWEEP = "unlisted_prompt_versions"


def _unlisted_reclaimable(cutoff: datetime):
    """A version taken out of every working copy more than the grace ago."""
    return (PromptVersion.unlisted_at.is_not(None), PromptVersion.unlisted_at <= cutoff)


async def reclaim_unlisted_versions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    grace: timedelta = RETIRED_LIST_GRACE,
    budget: SweepBudget | None = None,
) -> SweepReport:
    """Collect versions a save or a deletion took out of a working copy, a
    grace later, when nothing names them (#1359).

    A save overwrites the working copy in place and writes no revision, so a
    replaced wording is named by nothing the moment the save commits - except
    a game that drew it before then, which holds it in memory and writes it
    into its turns when it ends. The grace is that game's (the retired-list
    reclaim's day). After it, what nothing names - no list, turn, offer, usage
    fact, report or takedown record - goes, with any concept it leaves empty;
    what something does name is unstamped, kept by that reference from then on.
    Committed batches of ordered keys within the budget (R-PRIV-16).
    """
    budget = budget or SweepBudget()
    cutoff = (now or datetime.now(timezone.utc)) - grace
    started = time.monotonic()
    deleted = batches = 0
    exhausted = True
    while deleted < budget.rows and time.monotonic() - started < budget.seconds:
        async with session_factory() as session:
            async with session.begin():
                candidates = (
                    await session.scalars(
                        select(PromptVersion.id)
                        .where(*_unlisted_reclaimable(cutoff))
                        .order_by(PromptVersion.unlisted_at, PromptVersion.id)
                        .limit(min(budget.batch, budget.rows - deleted))
                    )
                ).all()
                if not candidates:
                    exhausted = False
                    break
                # Locked in id order, as every multi-row version writer takes
                # them, and only those nobody holds: a moderator deciding on
                # the concept holds its wordings, and they are the next pass's
                # (#1385 review). Waiting on them instead, while holding the
                # rest of the batch, could deadlock against the decision.
                version_ids = set(
                    (
                        await session.scalars(
                            select(PromptVersion.id)
                            .where(PromptVersion.id.in_(candidates))
                            .order_by(PromptVersion.id)
                            .with_for_update(skip_locked=True)
                        )
                    ).all()
                )
                if not version_ids:
                    break
                versions_deleted, _ = await reclaim_orphans(session, version_ids)
                # The rest are named by something that keeps them now.
                await session.execute(
                    update(PromptVersion)
                    .where(PromptVersion.id.in_(version_ids))
                    .values(unlisted_at=None, unlisted_from_list_id=None)
                    .execution_options(synchronize_session=False)
                )
        deleted += versions_deleted
        batches += 1
    probe = overdue_probe(PromptVersion.unlisted_at, *_unlisted_reclaimable(cutoff))
    async with session_factory() as session:
        earliest = await session.scalar(probe.oldest)
        backlog = int(await session.scalar(probe.backlog) or 0)
    overdue = 0.0
    if earliest is not None:
        if earliest.tzinfo is None:
            earliest = earliest.replace(tzinfo=timezone.utc)
        overdue = max(0.0, (cutoff - earliest).total_seconds())
    return SweepReport(
        deleted,
        name=UNLISTED_SWEEP,
        batches=batches,
        seconds=time.monotonic() - started,
        exhausted=exhausted and backlog > 0,
        oldest_overdue_seconds=overdue,
        backlog=backlog,
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
