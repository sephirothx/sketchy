"""Persistent player prompt lists: immutable revisions and access boundaries."""
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.db.models import (
    PromptListRevision,
    PromptListRevisionItem,
    PromptVersion,
    User,
    generate_uuid,
)
from app.prompts import letter_histogram
from app.repositories.interfaces import (
    PromptListConflictError,
    PromptListEntryInput,
    PromptListSelectionError,
)
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository

from tests.dbfixtures import create_test_db

pytestmark = pytest.mark.asyncio


async def _database():
    factory, engine = await create_test_db()
    owner_id = generate_uuid()
    other_id = generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add_all(
                [
                    User(
                        id=owner_id,
                        username="owner",
                        password_hash="hash",
                        display_name="Owner",
                        is_anonymous=False,
                        state="registered",
                    ),
                    User(
                        id=other_id,
                        username="other",
                        password_hash="hash",
                        display_name="Other",
                        is_anonymous=False,
                        state="registered",
                    ),
                ]
            )
    return factory, engine, str(owner_id), str(other_id)


async def test_owned_lists_are_uuidv7_revisioned_and_private_by_default():
    factory, engine, owner_id, other_id = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Party animals",
            description="Our recurring list",
            language="en",
            visibility="private",
            prompts=(
                PromptListEntryInput(answer="red panda"),
                PromptListEntryInput(answer="otter"),
            ),
        )

        assert UUID(created.id).version == 7
        assert created.version == 1
        assert created.visibility == "private"
        assert created.share_code is None
        assert [entry.answer for entry in created.prompts] == ["red panda", "otter"]
        assert all(UUID(entry.concept_id).version == 7 for entry in created.prompts)
        assert await repo.list_all() == []  # never leaks into the public catalogue
        assert await repo.get_owned(other_id, created.id) is None
        with pytest.raises(PromptListSelectionError, match="not found"):
            await repo.resolve_selection([created.slug])

        selection = await repo.resolve_selection(
            [created.slug], requesting_user_id=owner_id
        )
        assert selection.prompts == ("red panda", "otter")
        assert len(selection.revision_ids) == 1

        panda = created.prompts[0]
        updated = await repo.update_owned(
            owner_id,
            created.id,
            expected_version=1,
            name="Party animals",
            description="Revised",
            visibility="unlisted",
            prompts=(
                PromptListEntryInput(
                    concept_id=panda.concept_id,
                    answer="giant panda",
                    aliases=("panda",),
                ),
                PromptListEntryInput(answer="capybara"),
            ),
        )
        assert updated.version == 2
        assert updated.share_code and len(updated.share_code) >= 8
        assert updated.prompts[0].concept_id == panda.concept_id
        assert updated.prompts[0].prompt_version_id != panda.prompt_version_id
        assert updated.prompts[0].aliases == ("panda",)

        async with factory() as session:
            revisions = (
                await session.scalars(
                    select(PromptListRevision).where(
                        PromptListRevision.prompt_list_id == UUID(created.id)
                    )
                )
            ).all()
            panda_versions = (
                await session.scalars(
                    select(PromptVersion).where(
                        PromptVersion.concept_id == UUID(panda.concept_id)
                    )
                )
            ).all()
        assert {revision.version for revision in revisions} == {1, 2}
        assert {version.canonical_answer for version in panda_versions} == {
            "red panda",
            "giant panda",
        }

        with pytest.raises(PromptListConflictError, match="Reload"):
            await repo.update_owned(
                owner_id,
                created.id,
                expected_version=1,
                name="Stale",
                description="",
                visibility="private",
                prompts=(PromptListEntryInput(answer="apple"),),
            )

        shared = await repo.get_shared(updated.share_code)
        assert shared is not None and shared.slug == created.slug
        with pytest.raises(PromptListSelectionError):
            await repo.resolve_selection([created.slug])
        shared_selection = await repo.resolve_selection(
            [created.slug], share_codes=(updated.share_code,)
        )
        assert shared_selection.prompts == ("giant panda", "capybara")
    finally:
        await engine.dispose()


async def test_only_the_owner_can_delete_a_player_list():
    factory, engine, owner_id, other_id = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Mine",
            description="",
            language="en",
            visibility="private",
            prompts=(PromptListEntryInput(answer="apple"),),
        )
        assert await repo.delete_owned(other_id, created.id) is False
        assert await repo.get_owned(owner_id, created.id) is not None
        assert await repo.delete_owned(owner_id, created.id) is True
        assert await repo.get_owned(owner_id, created.id) is None
    finally:
        await engine.dispose()


async def test_an_owned_list_revision_is_priced_when_it_is_written():
    """Owned lists take the same path: no revision exists without its tallies.

    Wheel pricing reads these instead of walking a resident pool, so a revision
    written without them would silently price every letter at the same rate.
    """
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Mine",
            description="",
            language="en",
            visibility="private",
            prompts=(
                PromptListEntryInput(answer="banjo"),
                PromptListEntryInput(answer="kazoo"),
            ),
        )

        async with factory() as session:
            revision = (
                await session.execute(
                    select(PromptListRevision).where(
                        PromptListRevision.prompt_list_id == UUID(created.id)
                    )
                )
            ).scalars().one()

        expected_counts, expected_total = letter_histogram(["banjo", "kazoo"])
        assert revision.letter_counts == expected_counts
        assert revision.letter_total == expected_total == 10
    finally:
        await engine.dispose()


async def test_pinning_refuses_the_colliding_selections_resolution_refuses():
    """Pinning reads no prompts, so it must ask the database the same question.

    `resolve_selection` catches colliding answers by walking everything it
    loads. If pinning let a collision through, a room would be admitted on a
    selection where one guess could credit two different prompts.
    """
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        first = await repo.create_owned(
            owner_id,
            name="First",
            description="",
            language="en",
            visibility="private",
            prompts=(PromptListEntryInput(answer="otter"),),
        )
        # A different list whose alias reaches the same answer.
        second = await repo.create_owned(
            owner_id,
            name="Second",
            description="",
            language="en",
            visibility="private",
            prompts=(
                PromptListEntryInput(answer="river weasel", aliases=("otter",)),
            ),
        )
        slugs = [first.slug, second.slug]

        with pytest.raises(PromptListSelectionError, match="ambiguous"):
            await repo.resolve_selection(slugs, requesting_user_id=owner_id)
        with pytest.raises(PromptListSelectionError, match="ambiguous"):
            await repo.authorize_selection(slugs, requesting_user_id=owner_id)

        # Each on its own is a legitimate selection.
        for slug in slugs:
            pinned = await repo.authorize_selection(
                [slug], requesting_user_id=owner_id
            )
            assert pinned.prompt_count == 1
    finally:
        await engine.dispose()


async def test_pinning_refuses_a_list_the_requester_may_not_read():
    """R-LIST-06a rests on this check, and pinning is now the only one that runs."""
    factory, engine, owner_id, other_id = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Private",
            description="",
            language="en",
            visibility="private",
            prompts=(PromptListEntryInput(answer="otter"),),
        )

        with pytest.raises(PromptListSelectionError, match="not found"):
            await repo.authorize_selection(
                [created.slug], requesting_user_id=other_id
            )
        assert (
            await repo.authorize_selection(
                [created.slug], requesting_user_id=owner_id
            )
        ).prompt_count == 1
    finally:
        await engine.dispose()


async def test_a_revisions_tallies_cover_every_member_whatever_moderation_says():
    """Moderation state is mutable; a revision's membership is not.

    Counting only what was active when the revision was written makes the
    stored tallies a function of something that can change afterwards. A
    version hidden then restored is drawable again but missing from the counts
    for good, and a revision whose content was all hidden at write time keeps a
    zero total - which drops wheel pricing onto the drawn sample, the very
    thing storing a histogram exists to avoid.
    """
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Mine",
            description="",
            language="en",
            visibility="private",
            prompts=(
                PromptListEntryInput(answer="banjo"),
                PromptListEntryInput(answer="kazoo"),
            ),
        )

        # A moderator hides one of them, then the owner edits the list.
        async with factory() as session:
            async with session.begin():
                version = (
                    await session.execute(
                        select(PromptVersion).where(
                            PromptVersion.canonical_answer == "kazoo"
                        )
                    )
                ).scalars().one()
                version.moderation_state = "hidden"

        updated = await repo.update_owned(
            owner_id,
            created.id,
            expected_version=created.version,
            name="Mine",
            description="",
            visibility="private",
            prompts=(
                PromptListEntryInput(answer="banjo"),
                PromptListEntryInput(answer="kazoo"),
                PromptListEntryInput(answer="fiddle"),
            ),
        )

        async with factory() as session:
            revision = (
                await session.execute(
                    select(PromptListRevision)
                    .where(PromptListRevision.prompt_list_id == UUID(created.id))
                    .order_by(PromptListRevision.version.desc())
                )
            ).scalars().first()
            members = (
                await session.execute(
                    select(PromptVersion.canonical_answer)
                    .join(
                        PromptListRevisionItem,
                        PromptListRevisionItem.prompt_version_id == PromptVersion.id,
                    )
                    .where(PromptListRevisionItem.revision_id == revision.id)
                )
            ).scalars().all()

        assert updated.version == created.version + 1
        expected_counts, expected_total = letter_histogram(members)
        assert revision.letter_counts == expected_counts
        assert revision.letter_total == expected_total

        # And the revision written while "kazoo" was hidden counts it too: it
        # is a member, and a moderator restoring it must not need a rewrite.
        async with factory() as session:
            first = (
                await session.execute(
                    select(PromptListRevision)
                    .where(PromptListRevision.prompt_list_id == UUID(created.id))
                    .order_by(PromptListRevision.version)
                )
            ).scalars().first()
        first_counts, first_total = letter_histogram(["banjo", "kazoo"])
        assert first.letter_counts == first_counts
        assert first.letter_total == first_total
    finally:
        await engine.dispose()


async def _pin_a_game_to(factory, owner_id: str, revision_id: str) -> None:
    """A finished game that names the list's revision as a prompt source."""
    from datetime import datetime, timedelta, timezone

    from app.repositories.interfaces import (
        GameParticipantInput,
        GameRecordInput,
        TurnRecordInput,
    )
    from app.repositories.sqlalchemy import SqlAlchemyGameHistoryRepository

    started = datetime.now(timezone.utc) - timedelta(minutes=10)
    seat = str(generate_uuid())
    await SqlAlchemyGameHistoryRepository(factory).save_game(
        GameRecordInput(
            room_name="Uses the list",
            scoring_mode="default",
            hint_mode="none",
            drawing_seconds=60,
            total_rounds=1,
            player_count=1,
            started_at=started,
            finished_at=started + timedelta(minutes=5),
            prompt_source_mode="curated",
            prompt_source_revision_ids=(revision_id,),
        ),
        [
            GameParticipantInput(
                user_id=owner_id,
                final_score=0,
                final_rank=1,
                seat_id=seat,
                display_name="Owner",
                is_anonymous=False,
            )
        ],
        [
            TurnRecordInput(
                id=str(generate_uuid()),
                round_number=1,
                turn_number=1,
                drawer_user_id=owner_id,
                drawer_seat_id=seat,
                prompt="otter",
                duration_seconds=60,
            )
        ],
        [],
    )


async def _current_revision_id(factory, list_id: str) -> str:
    async with factory() as session:
        revision = await session.scalar(
            select(PromptListRevision)
            .where(PromptListRevision.prompt_list_id == UUID(list_id))
            .order_by(PromptListRevision.version.desc())
        )
    assert revision is not None
    return str(revision.id)


async def test_deleting_a_list_a_finished_game_used_keeps_that_games_provenance():
    """R-LIST-01 lets an owner delete a list; R-PRIV-05 keeps the game intact.

    Found by #612: with foreign keys enforced, deleting a used list rolled the
    whole transaction back because the game's pinned revision restricted it.
    The list is retired instead (#605): gone from its owner, pinned revision
    kept for the game.
    """
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Played once",
            description="",
            language="en",
            visibility="private",
            prompts=(PromptListEntryInput(answer="otter"),),
        )
        revision_id = await _current_revision_id(factory, created.id)
        await _pin_a_game_to(factory, owner_id, revision_id)

        assert await repo.delete_owned(owner_id, created.id) is True

        assert await repo.get_owned(owner_id, created.id) is None
        async with factory() as session:
            assert await session.get(PromptListRevision, UUID(revision_id)) is not None
    finally:
        await engine.dispose()


async def test_erasing_the_owner_of_a_used_list_succeeds():
    """R-PRIV-05: the other players' history is never damaged, so erasure
    cannot delete the revision their game pinned - and it cannot fail either."""
    from app.auth.account_data import anonymize_account

    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Played once",
            description="",
            language="en",
            visibility="private",
            prompts=(PromptListEntryInput(answer="otter"),),
        )
        revision_id = await _current_revision_id(factory, created.id)
        await _pin_a_game_to(factory, owner_id, revision_id)

        await anonymize_account(factory, user_id=owner_id)

        async with factory() as session:
            owner = await session.get(User, UUID(owner_id))
            assert owner is not None and owner.state == "deleted"
            assert await session.get(PromptListRevision, UUID(revision_id)) is not None
    finally:
        await engine.dispose()


# --- #605: retire, keep what games pin, reclaim the rest ---------------------


async def _content_counts(factory) -> dict[str, int]:
    from sqlalchemy import func

    from app.db.models import (
        PromptAlias,
        PromptConcept,
        PromptList,
        PromptVersionAlias,
    )

    async with factory() as session:
        return {
            "lists": await session.scalar(select(func.count(PromptList.id))),
            "revisions": await session.scalar(select(func.count(PromptListRevision.id))),
            "items": await session.scalar(
                select(func.count(PromptListRevisionItem.prompt_version_id))
            ),
            "versions": await session.scalar(select(func.count(PromptVersion.id))),
            "concepts": await session.scalar(select(func.count(PromptConcept.id))),
            "aliases": await session.scalar(select(func.count(PromptAlias.id))),
            "version_aliases": await session.scalar(
                select(func.count(PromptVersionAlias.prompt_version_id))
            ),
        }


async def test_a_deleted_list_is_out_of_reach_at_once_and_its_pinned_revision_stays():
    from datetime import datetime, timedelta, timezone

    from app.db.models import GamePromptSource, PromptList
    from app.services.prompt_reclaim import reclaim_retired_prompt_lists

    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Shared then gone",
            description="",
            language="en",
            visibility="unlisted",
            prompts=(PromptListEntryInput(answer="otter", aliases=("sea otter",)),),
        )
        assert created.share_code is not None
        revision_id = await _current_revision_id(factory, created.id)
        await _pin_a_game_to(factory, owner_id, revision_id)

        assert await repo.delete_owned(owner_id, created.id) is True
        assert await repo.delete_owned(owner_id, created.id) is False, "retired once"

        # Gone from every way in: the owner's listing, the share code, a room.
        assert await repo.list_owned(owner_id) == []
        assert await repo.get_owned(owner_id, created.id) is None
        assert await repo.get_shared(created.share_code) is None
        with pytest.raises(PromptListSelectionError, match="not found"):
            await repo.resolve_selection([created.slug], requesting_user_id=owner_id)
        # A retired list does not count against the owner's allowance.
        for index in range(25):
            await repo.create_owned(
                owner_id,
                name=f"Fresh {index}",
                description="",
                language="en",
                visibility="private",
                prompts=(PromptListEntryInput(answer=f"answer {index}"),),
            )

        # The sweep, well after the grace: the pinned revision and its content
        # stay, the tombstone row stays with them, the display rows are gone.
        later = datetime.now(timezone.utc) + timedelta(days=2)
        result = await reclaim_retired_prompt_lists(factory, now=later)
        assert result.lists_examined == 1
        assert result.revisions_deleted == 0 and result.lists_deleted == 0
        async with factory() as session:
            tombstone = await session.get(PromptList, UUID(created.id))
            assert tombstone is not None and tombstone.share_code is None
            assert tombstone.deleted_at is not None
            assert await session.get(PromptListRevision, UUID(revision_id)) is not None
            assert (
                await session.scalar(
                    select(GamePromptSource).where(
                        GamePromptSource.prompt_list_revision_id == UUID(revision_id)
                    )
                )
                is not None
            )
    finally:
        await engine.dispose()


async def test_a_room_that_pinned_a_list_before_its_deletion_still_finishes_its_game():
    """R-LIST-07: the pin is a revision id held in memory; the grace before
    reclaim is what keeps that id valid until the game is written."""
    from datetime import datetime, timedelta, timezone

    from app.services.prompt_reclaim import reclaim_retired_prompt_lists

    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Played while deleted",
            description="",
            language="en",
            visibility="private",
            prompts=(PromptListEntryInput(answer="otter"),),
        )
        pinned = await repo.authorize_selection([created.slug], requesting_user_id=owner_id)
        (revision_id,) = pinned.revision_ids

        assert await repo.delete_owned(owner_id, created.id) is True
        # Within the grace, the sweep leaves the revision for the running game.
        await reclaim_retired_prompt_lists(factory)
        await _pin_a_game_to(factory, owner_id, revision_id)

        later = datetime.now(timezone.utc) + timedelta(days=2)
        await reclaim_retired_prompt_lists(factory, now=later)
        async with factory() as session:
            assert await session.get(PromptListRevision, UUID(revision_id)) is not None
    finally:
        await engine.dispose()


async def test_repeated_create_and_delete_of_unused_lists_leaves_nothing_behind():
    from datetime import datetime, timedelta, timezone

    from app.services.prompt_reclaim import reclaim_retired_prompt_lists

    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        for round_number in range(3):
            created = await repo.create_owned(
                owner_id,
                name=f"Scratch {round_number}",
                description="",
                language="en",
                visibility="private",
                prompts=(
                    PromptListEntryInput(answer="otter", aliases=("sea otter",)),
                    PromptListEntryInput(answer="heron"),
                ),
            )
            await repo.update_owned(
                owner_id,
                created.id,
                expected_version=1,
                name=f"Scratch {round_number}",
                description="",
                visibility="private",
                prompts=(PromptListEntryInput(answer="heron"),),
            )
            assert await repo.delete_owned(owner_id, created.id) is True
        before = await _content_counts(factory)
        assert before["lists"] == 3 and before["revisions"] == 6

        later = datetime.now(timezone.utc) + timedelta(days=2)
        result = await reclaim_retired_prompt_lists(factory, now=later, limit=2)
        assert result.lists_examined == 2 and result.lists_deleted == 2
        assert (await _content_counts(factory))["lists"] == 1, "bounded batch"
        await reclaim_retired_prompt_lists(factory, now=later)

        assert await _content_counts(factory) == {
            "lists": 0,
            "revisions": 0,
            "items": 0,
            "versions": 0,
            "concepts": 0,
            "aliases": 0,
            "version_aliases": 0,
        }
    finally:
        await engine.dispose()


async def test_reclaim_keeps_a_version_a_report_cites_and_drops_its_unused_sibling():
    from datetime import datetime, timedelta, timezone

    from app.db.models import PromptContentReport
    from app.services.prompt_reclaim import reclaim_retired_prompt_lists

    factory, engine, owner_id, other_id = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Reported",
            description="",
            language="en",
            visibility="private",
            prompts=(
                PromptListEntryInput(answer="reported answer"),
                PromptListEntryInput(answer="harmless answer"),
            ),
        )
        reported = next(
            entry for entry in created.prompts if entry.answer == "reported answer"
        )
        async with factory() as session:
            async with session.begin():
                session.add(
                    PromptContentReport(
                        id=generate_uuid(),
                        reporter_user_id=UUID(other_id),
                        reported_owner_user_id=UUID(owner_id),
                        prompt_list_id=UUID(created.id),
                        prompt_version_id=UUID(reported.prompt_version_id),
                        target_type="prompt",
                        list_name_snapshot=created.name,
                        prompt_snapshot="reported answer",
                        reason="inappropriate",
                        details="",
                    )
                )
        assert await repo.delete_owned(owner_id, created.id) is True

        later = datetime.now(timezone.utc) + timedelta(days=2)
        result = await reclaim_retired_prompt_lists(factory, now=later)
        assert result.lists_deleted == 1 and result.revisions_deleted == 1
        assert result.versions_deleted == 1 and result.concepts_deleted == 1
        async with factory() as session:
            assert await session.get(PromptVersion, UUID(reported.prompt_version_id)) is not None
            report = await session.scalar(select(PromptContentReport))
            assert report.prompt_version_id == UUID(reported.prompt_version_id)
            assert report.prompt_list_id is None, "SET NULL: the list row is gone"
            assert report.list_name_snapshot == "Reported"
    finally:
        await engine.dispose()


# --- #613: an unchanged save changes nothing, an edit rewrites only what moved


def _capture(engine) -> list[str]:
    from sqlalchemy import event

    statements: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    return statements


def _display_updates(statements: list[str]) -> list[str]:
    return [s for s in statements if s.lstrip().startswith("UPDATE prompts")]


async def _big_list(repo, owner_id: str, size: int = 500):
    return await repo.create_owned(
        owner_id,
        name="Big",
        description="",
        language="en",
        visibility="private",
        prompts=tuple(PromptListEntryInput(answer=f"prompt {index:03d}") for index in range(size)),
    )


def _restated(saved) -> tuple[PromptListEntryInput, ...]:
    return tuple(
        PromptListEntryInput(answer=e.answer, concept_id=e.concept_id, aliases=e.aliases)
        for e in saved.prompts
    )


async def test_an_exact_restatement_adds_no_revision_and_keeps_the_version():
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Same",
            description="d",
            language="en",
            visibility="private",
            prompts=(
                PromptListEntryInput(answer="otter", aliases=("sea otter",)),
                PromptListEntryInput(answer="heron"),
            ),
        )
        statements = _capture(engine)
        same = await repo.update_owned(
            owner_id,
            created.id,
            expected_version=1,
            name="Same",
            description="d",
            visibility="private",
            prompts=_restated(created),
        )
        assert same.version == 1 and same.prompts == created.prompts
        assert not [s for s in statements if s.lstrip().startswith(("INSERT", "UPDATE", "DELETE"))]
        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count(PromptListRevision.id)).where(
                        PromptListRevision.prompt_list_id == UUID(created.id)
                    )
                )
                == 1
            )
        # Optimistic concurrency still applies to a restatement.
        with pytest.raises(PromptListConflictError):
            await repo.update_owned(
                owner_id, created.id, expected_version=7, name="Same", description="d",
                visibility="private", prompts=_restated(created),
            )
        # A metadata-only edit is still an edit (R-LIST-05): a revision, a version.
        renamed = await repo.update_owned(
            owner_id, created.id, expected_version=1, name="Renamed", description="d",
            visibility="private", prompts=_restated(created),
        )
        assert renamed.version == 2 and renamed.name == "Renamed"
    finally:
        await engine.dispose()


async def test_a_one_answer_edit_in_a_big_list_rewrites_one_display_row():
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await _big_list(repo, owner_id)
        entries = list(_restated(created))
        entries[250] = PromptListEntryInput(answer="prompt two-fifty", concept_id=entries[250].concept_id)
        statements = _capture(engine)

        updated = await repo.update_owned(
            owner_id, created.id, expected_version=1, name="Big", description="",
            visibility="private", prompts=tuple(entries),
        )

        assert updated.version == 2
        assert updated.prompts[250].answer == "prompt two-fifty"
        assert updated.prompts[250].concept_id == created.prompts[250].concept_id
        updates = _display_updates(statements)
        assert len(updates) == 1, updates
        assert not any("__editing__" in s for s in statements), "no swap, no temporary text"
    finally:
        await engine.dispose()


async def test_swapped_answers_and_alias_only_edits_still_land():
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id, name="Swap", description="", language="en", visibility="private",
            prompts=(PromptListEntryInput(answer="one"), PromptListEntryInput(answer="two"),
                     PromptListEntryInput(answer="three")),
        )
        one, two, three = created.prompts
        swapped = await repo.update_owned(
            owner_id, created.id, expected_version=1, name="Swap", description="",
            visibility="private",
            prompts=(
                PromptListEntryInput(answer="two", concept_id=one.concept_id),
                PromptListEntryInput(answer="one", concept_id=two.concept_id),
                PromptListEntryInput(answer="three", concept_id=three.concept_id),
            ),
        )
        assert [e.answer for e in swapped.prompts] == ["two", "one", "three"]
        assert swapped.prompts[0].concept_id == one.concept_id
        assert await repo.get_prompts(created.id) == ["one", "three", "two"]

        aliased = await repo.update_owned(
            owner_id, created.id, expected_version=2, name="Swap", description="",
            visibility="private",
            prompts=(
                PromptListEntryInput(answer="two", concept_id=one.concept_id, aliases=("deux",)),
                PromptListEntryInput(answer="one", concept_id=two.concept_id),
                PromptListEntryInput(answer="three", concept_id=three.concept_id),
            ),
        )
        assert aliased.version == 3 and aliased.prompts[0].aliases == ("deux",)
        # A new prompt taking a removed prompt's text, and one taking a
        # changed prompt's old text, both land.
        reused = await repo.update_owned(
            owner_id, created.id, expected_version=3, name="Swap", description="",
            visibility="private",
            prompts=(
                PromptListEntryInput(answer="four", concept_id=one.concept_id),
                PromptListEntryInput(answer="two"),
                PromptListEntryInput(answer="three", concept_id=three.concept_id),
                PromptListEntryInput(answer="one"),
            ),
        )
        assert [e.answer for e in reused.prompts] == ["four", "two", "three", "one"]
        assert await repo.get_prompts(created.id) == ["four", "one", "three", "two"]
    finally:
        await engine.dispose()


async def test_usage_reads_only_the_memberships_the_game_touched():
    from datetime import datetime, timezone

    from app.db.models import PromptUsageFact
    from app.repositories.interfaces import PromptPickTotals, PromptUsage

    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await _big_list(repo, owner_id, size=200)
        revision_id = await _current_revision_id(factory, created.id)
        offered = created.prompts[3].prompt_version_id
        picked = created.prompts[7].prompt_version_id
        usage = PromptUsage(
            batch_id=str(generate_uuid()),
            occurred_at=datetime.now(timezone.utc),
            scoring_mode="default",
            hint_mode="none",
            offers={offered: 2, picked: 1},
            picks={picked: PromptPickTotals(picks=1, correct_guesses=1, total_guessers=3)},
        )
        statements = _capture(engine)

        await repo.record_prompt_usage([revision_id], usage)

        membership_reads = [
            s for s in statements
            if s.lstrip().startswith("SELECT") and "prompt_list_revision_items" in s
        ]
        assert membership_reads and all(
            "prompt_list_revision_items.prompt_version_id IN" in s for s in membership_reads
        )
        async with factory() as session:
            facts = (await session.scalars(select(PromptUsageFact))).all()
        assert {str(f.prompt_version_id).replace("-", "") for f in facts} == {
            offered.replace("-", ""), picked.replace("-", "")
        }
        assert sum(f.offer_count for f in facts) == 3 and sum(f.pick_count for f in facts) == 1
    finally:
        await engine.dispose()
