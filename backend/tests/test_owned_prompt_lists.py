"""Persistent player prompt lists: immutable revisions and access boundaries."""
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

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
                        display_name="Owner",
                        is_anonymous=False,
                        state="registered",
                    ),
                    User(
                        id=other_id,
                        username="other",
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
            prompt_source_mode="lists",
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


@pytest.mark.xfail(
    strict=True,
    reason="#605: game_prompt_sources RESTRICTs the revision the list deletion removes",
)
async def test_deleting_a_list_a_finished_game_used_keeps_that_games_provenance():
    """R-LIST-01 lets an owner delete a list; R-PRIV-05 keeps the game intact.

    Found by #612: with foreign keys enforced, deleting a used list rolls the
    whole transaction back because the game's pinned revision restricts it.
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


@pytest.mark.xfail(
    strict=True,
    reason="#605: account erasure deletes owned lists the same way, and fails the same way",
)
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
