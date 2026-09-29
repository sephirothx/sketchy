"""Superseded revisions of live prompt lists are reclaimed, and only those
nothing needs (#1258).

Every content save writes the whole list again as a new revision, and only
retired lists were reclaimed, so a live list kept every revision it was ever
saved as. The sweep keeps a live list's current revision, every revision
still inside the grace, and any a finished game pins, a fork was copied from,
or a hidden prompt is recorded in.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update

from app.db.models import (
    PromptList,
    PromptListRevision,
    PromptListRevisionItem,
    PromptVersion,
)
from app.domain_values import PromptContentModerationState
from app.repositories.interfaces import PromptListEntryInput
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository
from app.services.prompt_reclaim import RETIRED_LIST_GRACE, reclaim_superseded_revisions
from app.services.sweeps import SweepBudget
from tests.test_owned_prompt_lists import _database, _pin_a_game_to

LONG_AGO = datetime.now(timezone.utc) - timedelta(days=10)


async def _saved(repo, factory, owner_id: str, name: str, answers: list[str]) -> tuple[str, list[str]]:
    """A list saved once per answer, one prompt each; its revision ids, oldest first."""
    created = await repo.create_owned(
        owner_id, name=name, description="", language="en",
        prompts=(PromptListEntryInput(answer=answers[0]),),
    )
    for version, answer in enumerate(answers[1:], start=1):
        await repo.update_owned(
            owner_id, created.id, expected_version=version, name=name, description="",
            prompts=(PromptListEntryInput(answer=answer),),
        )
    return created.id, await _revisions(factory, created.id)


async def _revisions(factory, list_id: str) -> list[str]:
    async with factory() as session:
        return [
            str(revision_id)
            for revision_id in (
                await session.scalars(
                    select(PromptListRevision.id)
                    .where(PromptListRevision.prompt_list_id == UUID(list_id))
                    .order_by(PromptListRevision.version)
                )
            ).all()
        ]


async def _age(factory, revision_ids: list[str], when: datetime) -> None:
    async with factory() as session, session.begin():
        await session.execute(
            update(PromptListRevision)
            .where(PromptListRevision.id.in_([UUID(revision_id) for revision_id in revision_ids]))
            .values(created_at=when)
        )


async def _answer_versions(factory, answer: str) -> int:
    async with factory() as session:
        return int(
            await session.scalar(
                select(func.count(PromptVersion.id)).where(PromptVersion.canonical_answer == answer)
            )
            or 0
        )


async def test_a_live_list_keeps_what_is_current_young_or_needed_and_nothing_else():
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        list_id, (pinned, forked_from, hiding, plain, young, current) = await _saved(
            repo, factory, owner_id, "Saved often", ["otter", "heron", "crane", "ibis", "swan", "lark"]
        )
        await _pin_a_game_to(factory, owner_id, pinned)
        other_id, (fork,) = await _saved(repo, factory, owner_id, "Copied", ["heron"])
        async with factory() as session, session.begin():
            await session.execute(
                update(PromptListRevision)
                .where(PromptListRevision.id == UUID(fork))
                .values(forked_from_revision_id=UUID(forked_from))
            )
            crane = await session.scalar(
                select(PromptListRevisionItem.prompt_version_id).where(
                    PromptListRevisionItem.revision_id == UUID(hiding)
                )
            )
            await session.execute(
                update(PromptVersion)
                .where(PromptVersion.id == crane)
                .values(moderation_state=PromptContentModerationState.HIDDEN.value)
            )
        now = datetime.now(timezone.utc)
        # Everything but the current save was superseded ten days ago; the
        # current one, which supersedes `young`, was saved just now.
        await _age(factory, [pinned, forked_from, hiding, plain, young], LONG_AGO)
        assert await _answer_versions(factory, "ibis") == 1

        report = await reclaim_superseded_revisions(factory, now=now)

        assert int(report) == 1
        assert await _revisions(factory, list_id) == [pinned, forked_from, hiding, young, current]
        assert await _answer_versions(factory, "ibis") == 0, "the content only it named went with it"
        assert await _revisions(factory, other_id) == [fork], "the fork itself is a current revision"
        assert report.backlog == 0 and report.oldest_overdue_seconds == 0

        again = await reclaim_superseded_revisions(factory, now=now)
        assert int(again) == 0
    finally:
        await engine.dispose()


async def test_the_grace_counts_from_the_save_that_superseded_a_revision():
    """A revision is in use until the save after it and a game after that:
    the room that pinned it at its game's start plays it to the end."""
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        list_id, (first, second) = await _saved(repo, factory, owner_id, "Saved twice", ["otter", "heron"])
        superseded_at = datetime.now(timezone.utc) - timedelta(hours=3)
        # Created long ago, superseded three hours ago: the grace is not over.
        await _age(factory, [first], LONG_AGO)
        await _age(factory, [second], superseded_at)

        inside = await reclaim_superseded_revisions(factory, now=superseded_at + RETIRED_LIST_GRACE - timedelta(seconds=1))
        assert int(inside) == 0
        assert await _revisions(factory, list_id) == [first, second]

        past = await reclaim_superseded_revisions(factory, now=superseded_at + RETIRED_LIST_GRACE + timedelta(seconds=1))
        assert int(past) == 1
        assert await _revisions(factory, list_id) == [second]
    finally:
        await engine.dispose()


async def test_a_retired_list_is_left_to_its_own_sweep():
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        list_id, revisions = await _saved(repo, factory, owner_id, "Deleted", ["otter", "heron"])
        await _age(factory, revisions, LONG_AGO)
        assert await repo.delete_owned(owner_id, list_id) is True
        report = await reclaim_superseded_revisions(factory)
        assert int(report) == 0
        async with factory() as session:
            assert await session.get(PromptList, UUID(list_id)) is not None
    finally:
        await engine.dispose()


async def test_a_run_deletes_no_more_rows_than_its_budget_has():
    """Counting each revision's items: a revision of a 500-prompt list is 500
    rows, and a pass of 200 of them would be 100,000 against a budget of
    5,000. Here each revision is one item and itself: two rows."""
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        list_id, revisions = await _saved(repo, factory, owner_id, "Many saves", ["a1", "b2", "c3", "d4"])
        await _age(factory, revisions, LONG_AGO)
        report = await reclaim_superseded_revisions(factory, budget=SweepBudget(rows=4, batch=2))
        assert int(report) == 2 and report.exhausted
        assert report.backlog == 1, "the third superseded save waits for the next pass"
        assert report.oldest_overdue_seconds > 0
        await reclaim_superseded_revisions(factory)
        assert await _revisions(factory, list_id) == [revisions[-1]]
    finally:
        await engine.dispose()
