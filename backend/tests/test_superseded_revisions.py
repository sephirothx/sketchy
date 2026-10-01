"""Superseded revisions of live prompt lists are reclaimed, and only those
nothing needs (#1258).

Every content save writes the whole list again as a new revision, and only
retired lists were reclaimed, so a live list kept every revision it was ever
saved as. The sweep keeps a live list's current revision and every revision
still inside the grace, and nothing else: a finished game names its list
(#1358), a copy the list it came from (#1361), and a hidden prompt is kept by
its owner's takedown record (#1357).
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
from app.domain_values import PromptContentModerationState, UserRole
from app.repositories.interfaces import PromptListEntryInput
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository
from app.services.prompt_reclaim import RETIRED_LIST_GRACE, reclaim_superseded_revisions
from app.services.sweeps import SweepBudget
from tests.test_owned_prompt_lists import _database, _play_a_game_from
from tests.test_prompt_content_moderation import (  # noqa: F401 - env is a fixture
    _staff_member,
    env,
    published,
    register,
    taken_down,
)

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
        list_id, (played_from, older, hiding, plain, young, current) = await _saved(
            repo, factory, owner_id, "Saved often", ["otter", "heron", "crane", "ibis", "swan", "lark"]
        )
        await _play_a_game_from(factory, owner_id, list_id)
        other_id, (fork,) = await _saved(repo, factory, owner_id, "Copied", ["heron"])
        async with factory() as session, session.begin():
            # A copy of the list, which names the list rather than a revision
            # of it (#1361) and so holds none.
            await session.execute(
                update(PromptList)
                .where(PromptList.id == UUID(other_id))
                .values(is_copy=True, copied_from_list_id=UUID(list_id))
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
        await _age(factory, [played_from, older, hiding, plain, young], LONG_AGO)
        assert await _answer_versions(factory, "ibis") == 1

        report = await reclaim_superseded_revisions(factory, now=now)

        # Neither a hidden word (#1357), a finished game (#1358) nor a copy
        # (#1361) is a hold: what the grace keeps is all that stays.
        assert int(report) == 4
        assert await _revisions(factory, list_id) == [young, current]
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


async def _hide(factory, version_id: str) -> None:
    async with factory() as session, session.begin():
        await taken_down(session, await session.get(PromptVersion, UUID(version_id)))


async def test_a_takedown_outlives_the_revisions_it_was_found_in():
    """A revision holding a hidden word used to be kept as the takedown's
    record - asked of the revision, not of each item (#1258 review). The
    record is its own row now (#1357): the revision goes like any other, and
    the word still cannot be typed back in."""
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id, name="Mixed", description="", language="en",
            prompts=(PromptListEntryInput(answer="offensive word"), PromptListEntryInput(answer="fine")),
        )
        word = next(prompt for prompt in created.prompts if prompt.answer == "offensive word")
        fine = next(prompt for prompt in created.prompts if prompt.answer == "fine")
        await _hide(factory, word.prompt_version_id)
        await repo.update_owned(
            owner_id, created.id, expected_version=created.version, name="Mixed", description="",
            prompts=(PromptListEntryInput(answer="fine", concept_id=fine.concept_id),),
        )
        revisions = await _revisions(factory, created.id)
        await _age(factory, revisions, LONG_AGO)

        report = await reclaim_superseded_revisions(factory)

        assert int(report) == 1
        assert await _revisions(factory, created.id) == revisions[1:]
        assert await _answer_versions(factory, "offensive word") == 1, "the record keeps its spelling"
        again = await repo.create_owned(
            owner_id, name="Again", description="", language="en",
            prompts=(PromptListEntryInput(answer="offensive word"),),
        )
        assert again.prompts[0].moderation_state == PromptContentModerationState.HIDDEN.value
    finally:
        await engine.dispose()


async def test_an_edited_copy_keeps_what_it_was_copied_from():
    """A copy's first revision used to say what it was copied from, and the
    copy count, the credit and the lineage all read it there: editing the copy
    superseded it, and reclaiming it erased all three (#1258 review). The copy
    names its origin on the list now (#1361), so the revision goes and none of
    the three moves."""
    factory, engine, owner_id, other_id = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        original = await repo.create_owned(
            owner_id, name="Original", description="", language="en",
            prompts=(PromptListEntryInput(answer="otter"), PromptListEntryInput(answer="heron")),
        )
        await published(factory, original.id)
        copy = await repo.fork_published(other_id, original.id)
        await repo.update_owned(
            other_id, copy.id, expected_version=copy.version, name=copy.name, description="",
            prompts=(PromptListEntryInput(answer="otter"), PromptListEntryInput(answer="crane")),
        )
        await _age(factory, await _revisions(factory, copy.id), LONG_AGO)

        assert int(await reclaim_superseded_revisions(factory)) == 1

        assert (await repo.get_owned(owner_id, original.id)).copy_count == 1
        edited = await repo.get_owned(other_id, copy.id)
        assert edited.copied_from.status == "published"
        assert edited.copied_from.list_id == original.id
    finally:
        await engine.dispose()


async def test_a_takedown_decided_after_its_revision_went_still_reaches_the_owner(env):  # noqa: F811
    """A report outlives the grace easily. Reclaiming the only revision that
    tied the reported word to its owner once hid a later takedown from nobody's
    next list (#1258 review), so the revision was held; the decision now
    records the takedown against the owner the report names (#1357)."""
    new_client, factory, prompts = env
    owner_http, reporter_http, moderator_http = new_client(), new_client(), new_client()
    owner = await register(owner_http, "SqOwner")
    await register(reporter_http, "SqReporter")
    moderator = await register(moderator_http, "SqModerator")
    await _staff_member(factory, moderator, UserRole.MODERATOR)
    first = await prompts.create_owned(
        owner["id"], name="Original", description="", language="en",
        prompts=(PromptListEntryInput(answer="borderline word"), PromptListEntryInput(answer="fine")),
    )
    await published(factory, first.id)
    word = next(prompt for prompt in first.prompts if prompt.answer == "borderline word")
    fine = next(prompt for prompt in first.prompts if prompt.answer == "fine")
    filed = await reporter_http.post(
        "/api/prompt-content-reports",
        json={"promptListId": first.id, "promptVersionId": word.prompt_version_id,
              "reason": "other", "details": "Decide it."},
    )
    assert filed.status_code == 201, filed.text
    await prompts.update_owned(
        owner["id"], first.id, expected_version=first.version, name="Original", description="",
        prompts=(PromptListEntryInput(answer="fine", concept_id=fine.concept_id),),
    )
    later = datetime.now(timezone.utc) + timedelta(days=2)

    assert int(await reclaim_superseded_revisions(factory, now=later)) == 1, "a report is no hold"

    decided = await moderator_http.patch(
        f"/api/moderation/prompt-content-reports/{filed.json()['id']}",
        json={"status": "resolved", "note": "hidden", "moderationState": "hidden"},
    )
    assert decided.status_code == 200, decided.text
    again = await prompts.create_owned(
        owner["id"], name="Again", description="", language="en",
        prompts=(PromptListEntryInput(answer="borderline word"),),
    )
    assert again.prompts[0].moderation_state == PromptContentModerationState.HIDDEN.value
