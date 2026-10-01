"""Deleting prompt lists, and collecting the prompt versions nothing names.

A list is deleted outright (#1362): its working copy, editions, tags and stars
go with the row at once, and a copy of it, a report about it and a version
unlisted from it let go of it (`SET NULL`). The history its games wrote -
their source rows, their offers' source rows, its usage facts - keeps its id
as an opaque value with no foreign key, so a delete costs what the list holds
and never what it was played: a list played in ten thousand games names
~300,000 history rows, and a cascade over them would have been a
multi-second transaction inside the owner's Delete or an account erasure.
Until #1362 that is what kept a deleted list as a tombstone for a day while a
budgeted sweep drained its history; the history needs nothing from the list,
since each turn stores its own prompt text and version (#1358).

The versions a deleted list held are stamped `unlisted_at`, as a save stamps
the wordings it drops, because a room that drew from the list before the
delete still writes them into its turns when its game ends. A day later
`reclaim_unlisted_versions` collects the ones nothing names - no list, turn,
offer, usage fact, report or takedown record - with any concept they leave
empty, and unstamps the rest.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import time
from uuid import UUID

from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    Prompt,
    PromptConcept,
    PromptContentReport,
    PromptList,
    PromptListEdition,
    PromptListEditionItem,
    PromptTakedown,
    PromptUsageFact,
    PromptVersion,
    TurnPromptOffer,
    TurnRecord,
)
from app.services.sweeps import SweepBudget, SweepReport, overdue_probe

logger = logging.getLogger(__name__)

# How long a wording a list no longer holds is kept for the game that drew it.
UNLISTED_GRACE = timedelta(days=1)


def _held_by(list_ids):
    """Every version these lists hold, in their working copies or editions."""
    return PromptVersion.id.in_(
        select(Prompt.prompt_version_id)
        .where(Prompt.prompt_list_id.in_(list_ids))
        .union(
            select(PromptListEditionItem.prompt_version_id)
            .join(PromptListEdition, PromptListEdition.id == PromptListEditionItem.edition_id)
            .where(PromptListEdition.prompt_list_id.in_(list_ids))
        )
    )


async def delete_prompt_lists(
    session: AsyncSession, list_ids: list[UUID], *, now: datetime | None = None
) -> int:
    """Delete these lists outright (#1362); how many went.

    The caller holds the list rows `FOR UPDATE`. The versions they held are
    locked in one id order - the order every multi-row version writer takes
    them (#1385 review) - and stamped for the unlisted sweep, then the rows
    go and everything that is the list's goes with them.
    """
    if not list_ids:
        return 0
    held = _held_by(list_ids)
    await session.execute(
        select(PromptVersion.id).where(held).order_by(PromptVersion.id).with_for_update()
    )
    await session.execute(
        update(PromptVersion)
        .where(held)
        .values(unlisted_at=now or datetime.now(timezone.utc), unlisted_from_list_id=None)
        .execution_options(synchronize_session=False)
    )
    return int(
        (await session.execute(delete(PromptList).where(PromptList.id.in_(list_ids)))).rowcount
        or 0
    )


async def delete_owned_lists(
    session: AsyncSession, owner_ids: list[UUID], *, now: datetime
) -> int:
    """Account erasure: delete every list the identities own (R-PRIV-05).

    Their name, description and prompts are the account's authored copy and
    go with the rows; a copy someone else made keeps its own content and
    credits a deleted list (R-LIST-21).
    """
    list_ids = list(
        (
            await session.scalars(
                select(PromptList.id)
                .where(
                    PromptList.owner_user_id.in_(owner_ids),
                    PromptList.is_bundled.is_(False),
                )
                .order_by(PromptList.id)
                .with_for_update()
            )
        ).all()
    )
    return await delete_prompt_lists(session, list_ids, now=now)


def _version_is_referenced(version_id):
    return (
        exists().where(Prompt.prompt_version_id == version_id)
        | exists().where(TurnRecord.prompt_version_id == version_id)
        | exists().where(TurnPromptOffer.prompt_version_id == version_id)
        | exists().where(PromptUsageFact.prompt_version_id == version_id)
        | exists().where(PromptContentReport.prompt_version_id == version_id)
        | exists().where(PromptListEditionItem.prompt_version_id == version_id)
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


UNLISTED_SWEEP = "unlisted_prompt_versions"


def _unlisted_reclaimable(cutoff: datetime):
    """A version taken out of every working copy more than the grace ago."""
    return (PromptVersion.unlisted_at.is_not(None), PromptVersion.unlisted_at <= cutoff)


async def reclaim_unlisted_versions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    grace: timedelta = UNLISTED_GRACE,
    budget: SweepBudget | None = None,
) -> SweepReport:
    """Collect versions a save or a deletion took out of a working copy, a
    grace later, when nothing names them (#1359).

    A save overwrites the working copy in place and writes no revision, so a
    replaced wording is named by nothing the moment the save commits - except
    a game that drew it before then, which holds it in memory and writes it
    into its turns when it ends. The grace is that game's: a day is far
    longer than a game. After it, what nothing names - no list, turn, offer, usage
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
