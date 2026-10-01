"""Persistent player prompt lists: immutable revisions and access boundaries."""
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    PromptList,
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
            prompts=(
                PromptListEntryInput(answer="red panda"),
                PromptListEntryInput(answer="otter"),
            ),
        )

        assert UUID(created.id).version == 7
        assert created.version == 1
        assert created.visibility == "private"
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
        assert len(selection.list_ids) == 1

        panda = created.prompts[0]
        updated = await repo.update_owned(
            owner_id,
            created.id,
            expected_version=1,
            name="Party animals",
            description="Revised",
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
        # A save never takes a list out of private; publishing does (R-LIST-02).
        assert updated.visibility == "private"
        assert updated.prompts[0].concept_id == panda.concept_id
        assert updated.prompts[0].prompt_version_id != panda.prompt_version_id
        assert updated.prompts[0].aliases == ("panda",)

        async with factory() as session:
            panda_versions = (
                await session.scalars(
                    select(PromptVersion).where(
                        PromptVersion.concept_id == UUID(panda.concept_id)
                    )
                )
            ).all()
        # A save overwrites the working copy (#1359); the old wording stays,
        # stamped, until the grace has passed.
        assert {
            (version.canonical_answer, version.unlisted_at is not None)
            for version in panda_versions
        } == {("red panda", True), ("giant panda", False)}

        with pytest.raises(PromptListConflictError, match="Reload"):
            await repo.update_owned(
                owner_id,
                created.id,
                expected_version=1,
                name="Stale",
                description="",
                prompts=(PromptListEntryInput(answer="apple"),),
            )

        with pytest.raises(PromptListSelectionError):
            await repo.resolve_selection([created.slug], requesting_user_id=other_id)
        owner_selection = await repo.resolve_selection(
            [created.slug], requesting_user_id=owner_id
        )
        assert owner_selection.prompts == ("giant panda", "capybara")
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
            prompts=(PromptListEntryInput(answer="apple"),),
        )
        assert await repo.delete_owned(other_id, created.id) is False
        assert await repo.get_owned(owner_id, created.id) is not None
        assert await repo.delete_owned(owner_id, created.id) is True
        assert await repo.get_owned(owner_id, created.id) is None
    finally:
        await engine.dispose()


async def test_an_owned_list_is_priced_when_it_is_written():
    """Owned lists take the same path: no working copy exists without its
    tallies (#1359, on the list row since there is no revision).

    Wheel pricing reads these instead of walking a resident pool, so a list
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
            prompts=(
                PromptListEntryInput(answer="banjo"),
                PromptListEntryInput(answer="kazoo"),
            ),
        )

        async with factory() as session:
            row = await session.get(PromptList, UUID(created.id))

        expected_counts, expected_total = letter_histogram(["banjo", "kazoo"])
        assert row.letter_counts == expected_counts
        assert row.letter_total == expected_total == 10
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
            prompts=(PromptListEntryInput(answer="otter"),),
        )
        # A different list whose alias reaches the same answer.
        second = await repo.create_owned(
            owner_id,
            name="Second",
            description="",
            language="en",
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


async def test_a_lists_tallies_cover_every_member_whatever_moderation_says():
    """Moderation state is mutable; the save that wrote the tallies is not.

    Counting only what was active when the working copy was saved makes the
    stored tallies a function of something that can change afterwards. A
    version hidden then restored is drawable again but missing from the counts
    until the next save, and a list whose content was all hidden at save time
    keeps a zero total - which drops wheel pricing onto the drawn sample, the
    very thing storing a histogram exists to avoid.
    """
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Mine",
            description="",
            language="en",
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
            prompts=(
                PromptListEntryInput(answer="banjo"),
                PromptListEntryInput(answer="kazoo"),
                PromptListEntryInput(answer="fiddle"),
            ),
        )

        async with factory() as session:
            row = await session.get(PromptList, UUID(created.id))

        assert updated.version == created.version + 1
        # "kazoo" was hidden when the save ran, and is counted: it is a member,
        # and a moderator restoring it must not need a rewrite.
        expected_counts, expected_total = letter_histogram(["banjo", "kazoo", "fiddle"])
        assert row.letter_counts == expected_counts
        assert row.letter_total == expected_total
    finally:
        await engine.dispose()


async def _play_a_game_from(factory, owner_id: str, list_id: str) -> None:
    """A finished game that names the list as a prompt source (#1358)."""
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
            prompt_source_list_ids=(list_id,),
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
    )


async def test_deleting_a_list_a_finished_game_played_succeeds():
    """R-LIST-01 lets an owner delete a list; R-PRIV-05 keeps the game intact.

    Found by #612: with foreign keys enforced, deleting a used list rolled the
    whole transaction back because the game's pinned revision restricted it.
    The list was retired instead (#605); since #1358 the game names the list,
    and nothing it references can stop the deletion.
    """
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Played once",
            description="",
            language="en",
            prompts=(PromptListEntryInput(answer="otter"),),
        )
        await _play_a_game_from(factory, owner_id, created.id)

        assert await repo.delete_owned(owner_id, created.id) is True

        assert await repo.get_owned(owner_id, created.id) is None
    finally:
        await engine.dispose()


async def test_erasing_the_owner_of_a_used_list_succeeds():
    """R-PRIV-05: the other players' history is never damaged, so erasure
    cannot fail because a game played the account's list."""
    from app.auth.account_data import anonymize_account

    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Played once",
            description="",
            language="en",
            prompts=(PromptListEntryInput(answer="otter"),),
        )
        await _play_a_game_from(factory, owner_id, created.id)

        await anonymize_account(factory, user_id=owner_id)

        async with factory() as session:
            owner = await session.get(User, UUID(owner_id))
            assert owner is not None and owner.state == "deleted"
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
            "versions": await session.scalar(select(func.count(PromptVersion.id))),
            "concepts": await session.scalar(select(func.count(PromptConcept.id))),
            "aliases": await session.scalar(select(func.count(PromptAlias.id))),
            "version_aliases": await session.scalar(
                select(func.count(PromptVersionAlias.prompt_version_id))
            ),
        }


async def test_a_deleted_list_goes_at_once_and_its_games_read_the_same():
    """Deleted outright (R-LIST-01, #1362), even though a finished game
    played it: the game's source rows keep the list's id as an opaque value,
    and the game reads the same without the list (#1358)."""
    from app.db.models import GamePromptSource, GameRecord, PromptList, TurnRecord

    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Kept then gone",
            description="",
            language="en",
            prompts=(PromptListEntryInput(answer="otter", aliases=("sea otter",)),),
        )
        await _play_a_game_from(factory, owner_id, created.id)

        assert await repo.delete_owned(owner_id, created.id) is True
        assert await repo.delete_owned(owner_id, created.id) is False, "deleted once"

        # Gone from every way in, and from the database.
        assert await repo.list_owned(owner_id) == []
        assert await repo.get_owned(owner_id, created.id) is None
        with pytest.raises(PromptListSelectionError, match="not found"):
            await repo.resolve_selection([created.slug], requesting_user_id=owner_id)
        async with factory() as session:
            assert await session.get(PromptList, UUID(created.id)) is None
            assert await session.scalar(select(GamePromptSource.prompt_list_id)) == UUID(
                created.id
            ), "the history keeps the id, naming nothing"
            assert await session.scalar(select(func.count(GameRecord.id))) == 1
            assert await session.scalar(select(TurnRecord.prompt)) == "otter"
    finally:
        await engine.dispose()


async def test_a_room_that_pinned_a_list_before_its_deletion_still_finishes_its_game():
    """R-LIST-07: the room holds what it drew, and its game is written after
    the list is gone, naming it by an id that no longer resolves (#1362)."""
    from app.db.models import GamePromptSource

    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Played while deleted",
            description="",
            language="en",
            prompts=(PromptListEntryInput(answer="otter"),),
        )
        pinned = await repo.authorize_selection([created.slug], requesting_user_id=owner_id)
        (list_id,) = pinned.list_ids

        assert await repo.delete_owned(owner_id, created.id) is True
        await _play_a_game_from(factory, owner_id, list_id)
        async with factory() as session:
            assert await session.scalar(select(func.count(GamePromptSource.game_id))) == 1
    finally:
        await engine.dispose()


async def test_deleting_a_list_leaves_no_wording_pointing_at_it():
    """A wording a save took out of the list within the grace points back at
    it. The delete locks and clears those in its one id-ordered pass rather
    than leaving them to the row's `SET NULL`, which would update versions
    outside that order (#1394 review). This checks the end state; the order
    itself only shows under a concurrent writer."""
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id, name="Edited", description="", language="en",
            prompts=(PromptListEntryInput(answer="gull"),),
        )
        gull = created.prompts[0]
        await repo.update_owned(
            owner_id, created.id, expected_version=created.version, name="Edited",
            description="",
            prompts=(PromptListEntryInput(answer="seagull", concept_id=gull.concept_id),),
        )
        async with factory() as session:
            assert (
                await session.get(PromptVersion, UUID(gull.prompt_version_id))
            ).unlisted_from_list_id == UUID(created.id)

        assert await repo.delete_owned(owner_id, created.id)

        async with factory() as session:
            stamped = await session.get(PromptVersion, UUID(gull.prompt_version_id))
        assert stamped.unlisted_at is not None and stamped.unlisted_from_list_id is None
    finally:
        await engine.dispose()


async def test_repeated_create_and_delete_of_unused_lists_leaves_nothing_behind():
    from datetime import datetime, timedelta, timezone

    from app.services.prompt_reclaim import reclaim_unlisted_versions

    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        for round_number in range(3):
            created = await repo.create_owned(
                owner_id,
                name=f"Scratch {round_number}",
                description="",
                language="en",
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
                prompts=(PromptListEntryInput(answer="heron"),),
            )
            assert await repo.delete_owned(owner_id, created.id) is True
        assert (await _content_counts(factory))["lists"] == 0, "deleted at once"

        # The versions were stamped when the lists went, and are collected a
        # grace later.
        later = datetime.now(timezone.utc) + timedelta(days=2)
        await reclaim_unlisted_versions(factory, now=later)

        assert await _content_counts(factory) == {
            "lists": 0,
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
    from app.services.prompt_reclaim import reclaim_unlisted_versions

    factory, engine, owner_id, other_id = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Reported",
            description="",
            language="en",
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
        # A waiting report does not hold the list: a takedown decided later is
        # recorded against the owner the report names (#1357), and the
        # reported version stays for the report itself.
        swept = await reclaim_unlisted_versions(factory, now=later)
        assert int(swept) == 1, "the harmless sibling goes; the reported one stays"
        async with factory() as session:
            assert await session.get(PromptVersion, UUID(reported.prompt_version_id)) is not None
            report = await session.scalar(select(PromptContentReport))
            assert report.prompt_version_id == UUID(reported.prompt_version_id)
            assert report.prompt_list_id == UUID(created.id), "the id stays, naming nothing"
            assert report.list_name_snapshot == "Reported"
    finally:
        await engine.dispose()



async def _a_word_saved_away(repo, owner_id):
    """A list whose save took `gone` out, the version stamped as unlisted from it."""
    created = await repo.create_owned(
        owner_id, name="Edited", description="", language="en",
        prompts=(PromptListEntryInput(answer="gone"), PromptListEntryInput(answer="kept")),
    )
    gone = next(entry for entry in created.prompts if entry.answer == "gone")
    kept = next(entry for entry in created.prompts if entry.answer == "kept")
    await repo.update_owned(
        owner_id, created.id, expected_version=created.version, name="Edited",
        description="", prompts=(PromptListEntryInput(answer="kept", concept_id=kept.concept_id),),
    )
    return created, UUID(gone.prompt_version_id)


async def test_a_version_the_sweep_keeps_is_no_longer_unlisted_from_anything():
    """Kept by a report, a removed wording loses both stamps together: it is
    named by something now, and no longer a page's grace-window prompt."""
    from datetime import datetime, timedelta, timezone

    from app.db.models import PromptContentReport
    from app.services.prompt_reclaim import reclaim_unlisted_versions

    factory, engine, owner_id, other_id = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created, gone = await _a_word_saved_away(repo, owner_id)
        async with factory() as session:
            stamped = await session.get(PromptVersion, gone)
            assert stamped.unlisted_at is not None
            assert stamped.unlisted_from_list_id == UUID(created.id)
        async with factory() as session:
            async with session.begin():
                session.add(
                    PromptContentReport(
                        id=generate_uuid(), reporter_user_id=UUID(other_id),
                        reported_owner_user_id=UUID(owner_id), prompt_list_id=UUID(created.id),
                        prompt_version_id=gone, target_type="prompt",
                        list_name_snapshot="Edited", prompt_snapshot="gone",
                        reason="inappropriate", details="",
                    )
                )

        await reclaim_unlisted_versions(factory, now=datetime.now(timezone.utc) + timedelta(days=2))

        async with factory() as session:
            kept = await session.get(PromptVersion, gone)
            assert kept is not None
            assert (kept.unlisted_at, kept.unlisted_from_list_id) == (None, None)
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not __import__("os").environ.get("TEST_DATABASE_URL"),
    reason="row locks are PostgreSQL's",
)
async def test_the_unlisted_sweep_passes_over_a_version_a_decision_holds():
    """A moderator's decision holds every wording of the concept. The sweep
    takes what nobody holds and leaves the rest for its next pass rather than
    waiting on it with its batch locked - which could deadlock against the
    decision (#1385 review)."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    from app.services.prompt_reclaim import reclaim_unlisted_versions

    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        _, gone = await _a_word_saved_away(repo, owner_id)
        later = datetime.now(timezone.utc) + timedelta(days=2)
        async with factory() as holder:
            async with holder.begin():
                await holder.execute(
                    select(PromptVersion.id).where(PromptVersion.id == gone).with_for_update()
                )
                swept = await asyncio.wait_for(
                    reclaim_unlisted_versions(factory, now=later), timeout=5
                )
                assert int(swept) == 0
        swept = await reclaim_unlisted_versions(factory, now=later)
        assert int(swept) == 1, "released, it goes on the next pass"
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
        prompts=tuple(PromptListEntryInput(answer=f"prompt {index:03d}") for index in range(size)),
    )


def _restated(saved) -> tuple[PromptListEntryInput, ...]:
    return tuple(
        PromptListEntryInput(answer=e.answer, concept_id=e.concept_id, aliases=e.aliases)
        for e in saved.prompts
    )


async def test_an_exact_restatement_writes_nothing_and_keeps_the_version():
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Same",
            description="d",
            language="en",
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
            prompts=_restated(created),
        )
        assert same.version == 1 and same.prompts == created.prompts
        assert not [s for s in statements if s.lstrip().startswith(("INSERT", "UPDATE", "DELETE"))]
        # Optimistic concurrency still applies to a restatement.
        with pytest.raises(PromptListConflictError):
            await repo.update_owned(
                owner_id, created.id, expected_version=7, name="Same", description="d",
                prompts=_restated(created),
            )
        # A metadata-only edit is still an edit (R-LIST-05): a version.
        renamed = await repo.update_owned(
            owner_id, created.id, expected_version=1, name="Renamed", description="d",
            prompts=_restated(created),
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
            prompts=tuple(entries),
        )

        assert updated.version == 2
        assert updated.prompts[250].answer == "prompt two-fifty"
        assert updated.prompts[250].concept_id == created.prompts[250].concept_id
        updates = _display_updates(statements)
        assert len(updates) == 1, updates
        assert not any("__editing__" in s for s in statements), "no swap, no temporary text"
    finally:
        await engine.dispose()


async def test_a_one_prompt_edit_writes_rows_for_the_change_not_the_list():
    """#1359: a save overwrites the working copy in place. Before it, a
    one-word edit of a 500-prompt list wrote the whole list again as a
    revision - 500 item rows, and the rest of the display rows besides."""
    from sqlalchemy import event

    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await _big_list(repo, owner_id)
        entries = list(_restated(created))
        entries[250] = PromptListEntryInput(answer="prompt two-fifty", concept_id=entries[250].concept_id)
        written: list[int] = []

        def count(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().startswith(("INSERT", "UPDATE", "DELETE")):
                written.append(len(parameters) if executemany else 1)

        event.listen(engine.sync_engine, "before_cursor_execute", count)
        try:
            await repo.update_owned(
                owner_id, created.id, expected_version=1, name="Big", description="",
                prompts=tuple(entries),
            )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count)

        # The new wording, its display row, the old wording's stamp, the list.
        assert sum(written) <= 5, written
    finally:
        await engine.dispose()


async def test_swapped_answers_and_alias_only_edits_still_land():
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id, name="Swap", description="", language="en",
            prompts=(PromptListEntryInput(answer="one"), PromptListEntryInput(answer="two"),
                     PromptListEntryInput(answer="three")),
        )
        one, two, three = created.prompts
        swapped = await repo.update_owned(
            owner_id, created.id, expected_version=1, name="Swap", description="",
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


async def test_usage_is_credited_to_the_lists_the_draw_found_it_in():
    """No revision's membership is asked when a game ends (#1358): each
    version is credited to the lists its draw found it in, and only to lists
    the game played - a source it did not play credits nobody."""
    from datetime import datetime, timezone

    from app.db.models import PromptUsageFact
    from app.repositories.interfaces import PromptPickTotals, PromptUsage

    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await _big_list(repo, owner_id, size=200)
        offered = created.prompts[3].prompt_version_id
        picked = created.prompts[7].prompt_version_id
        stranger = created.prompts[9].prompt_version_id
        usage = PromptUsage(
            batch_id=str(generate_uuid()),
            occurred_at=datetime.now(timezone.utc),
            scoring_mode="default",
            hint_mode="none",
            offers={offered: 2, picked: 1, stranger: 1},
            picks={picked: PromptPickTotals(picks=1, correct_guesses=1, total_guessers=3)},
            sources={
                offered: (created.id,),
                picked: (created.id,),
                stranger: (str(generate_uuid()),),
            },
        )
        statements = _capture(engine)

        await repo.record_prompt_usage([created.id], usage)

        assert not [s for s in statements if "prompt_list_revision" in s]
        async with factory() as session:
            facts = (await session.scalars(select(PromptUsageFact))).all()
        assert {str(f.prompt_version_id).replace("-", "") for f in facts} == {
            offered.replace("-", ""), picked.replace("-", "")
        }
        assert {str(f.prompt_list_id).replace("-", "") for f in facts} == {
            created.id.replace("-", "")
        }
        assert sum(f.offer_count for f in facts) == 3 and sum(f.pick_count for f in facts) == 1
    finally:
        await engine.dispose()


async def test_a_collision_the_fold_created_since_the_rows_were_written_is_caught():
    """Two lists, one with `feu d'artifice` and one with the typographic
    apostrophe. Rows written before #1011 carry keys that differ, while the
    game matches under the fold in force now, so both the walk and the
    pinning query key the *text* afresh rather than trusting the stored key
    (review of #1070)."""
    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        plain = await repo.create_owned(
            owner_id, name="Plain", description="", language="fr",
            prompts=(PromptListEntryInput(answer="feu d'artifice"),),
        )
        curly = await repo.create_owned(
            owner_id, name="Curly", description="", language="fr",
            prompts=(PromptListEntryInput(answer="feu d\u2019artifice"),),
        )
        # What a row written under the old fold carries: the apostrophe kept.
        async with factory() as session:
            async with session.begin():
                version = await session.scalar(
                    select(PromptVersion).where(
                        PromptVersion.canonical_answer == "feu d\u2019artifice"
                    )
                )
                version.match_key = "feu d\u2019artifice"
        slugs = [plain.slug, curly.slug]

        with pytest.raises(PromptListSelectionError, match="ambiguous"):
            await repo.resolve_selection(slugs, requesting_user_id=owner_id)
        with pytest.raises(PromptListSelectionError, match="ambiguous"):
            await repo.authorize_selection(slugs, requesting_user_id=owner_id)
        for slug in slugs:
            assert (await repo.authorize_selection([slug], requesting_user_id=owner_id)).prompt_count == 1
    finally:
        await engine.dispose()


# --- #1385 review: the draw is held to what was checked ----------------------


async def test_a_draw_refuses_a_list_saved_since_it_was_checked():
    """A save between authorization and the draw could add an answer that
    collides with another selected list's - `beaver` with the alias `otter`
    beside a list holding `otter` - which the check never saw. The draw
    refuses content at any version but the one checked."""
    from app.repositories.interfaces import PromptListsChangedError

    factory, engine, owner_id, _ = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        first = await repo.create_owned(
            owner_id, name="First", description="", language="en",
            prompts=(PromptListEntryInput(answer="otter"),),
        )
        second = await repo.create_owned(
            owner_id, name="Second", description="", language="en",
            prompts=(PromptListEntryInput(answer="panda"),),
        )
        pinned = await repo.authorize_selection(
            [first.slug, second.slug], requesting_user_id=owner_id
        )
        await repo.update_owned(
            owner_id, second.id, expected_version=second.version, name="Second",
            description="", prompts=(PromptListEntryInput(answer="beaver", aliases=("otter",)),),
        )

        with pytest.raises(PromptListsChangedError):
            await repo.sample_prompts(
                list(pinned.list_ids), limit=5, expected_versions=pinned.list_versions
            )
        with pytest.raises(PromptListSelectionError, match="ambiguous"):
            await repo.authorize_selection([first.slug, second.slug], requesting_user_id=owner_id)
        # Unchanged, it draws.
        again = await repo.authorize_selection([first.slug], requesting_user_id=owner_id)
        drawn = await repo.sample_prompts(
            list(again.list_ids), limit=5, expected_versions=again.list_versions
        )
        assert [prompt.answer for prompt in drawn.prompts] == ["otter"]
    finally:
        await engine.dispose()


async def _draw_database(tmp_path):
    """The suite's database, or on SQLite a file one: an in-memory database
    shares one cache, where a writer meets a table lock rather than a reader's
    snapshot, so only a file shows what the draw's readers see (#1385 review)."""
    import os

    if os.environ.get("TEST_DATABASE_URL"):
        return await _database()
    from tests.dbfixtures import _run_driver_script, _sqlite_schema_script, create_test_engine

    engine = create_test_engine(f"sqlite+aiosqlite:///{tmp_path / 'draw.db'}")
    async with engine.begin() as conn:
        await _run_driver_script(conn, _sqlite_schema_script())
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    owner_id = generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(
                User(
                    id=owner_id, username="owner", password_hash="hash",
                    display_name="Owner", is_anonymous=False, state="registered",
                )
            )
    return factory, engine, str(owner_id), None


async def test_a_save_landing_mid_draw_does_not_take_the_drawn_prompts_sources(
    monkeypatch, tmp_path
):
    """The draw reads its prompts, then where each came from. A save that
    rewords a drawn prompt between the two statements left it with no source
    - no provenance and no usage facts (#1385 review). The draw reads one
    snapshot, on either engine."""
    import app.repositories.sqlalchemy as repository

    factory, engine, owner_id, _ = await _draw_database(tmp_path)
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id, name="Mine", description="", language="en",
            prompts=(PromptListEntryInput(answer="otter"),),
        )
        pinned = await repo.authorize_selection([created.slug], requesting_user_id=owner_id)
        original = repository._source_lists

        async def a_save_lands_first(session, pins, version_ids):
            await repo.update_owned(
                owner_id, created.id, expected_version=created.version, name="Mine",
                description="",
                prompts=(PromptListEntryInput(answer="sea otter", concept_id=created.prompts[0].concept_id),),
            )
            return await original(session, pins, version_ids)

        monkeypatch.setattr(repository, "_source_lists", a_save_lands_first)
        drawn = await repo.sample_prompts(
            list(pinned.list_ids), limit=5, expected_versions=pinned.list_versions
        )

        assert [prompt.answer for prompt in drawn.prompts] == ["otter"]
        assert drawn.prompts[0].source_list_ids == (created.id,)
    finally:
        await engine.dispose()


async def test_a_save_landing_after_the_version_check_is_not_drawn(monkeypatch, tmp_path):
    """The version check and the sample are one snapshot: a save committing
    between them - `beaver` with the alias `otter`, beside a list holding
    `otter` - is not in what the draw returns (#1385 review)."""
    import app.repositories.sqlalchemy as repository

    factory, engine, owner_id, _ = await _draw_database(tmp_path)
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        first = await repo.create_owned(
            owner_id, name="First", description="", language="en",
            prompts=(PromptListEntryInput(answer="otter"),),
        )
        second = await repo.create_owned(
            owner_id, name="Second", description="", language="en",
            prompts=(PromptListEntryInput(answer="panda"),),
        )
        pinned = await repo.authorize_selection(
            [first.slug, second.slug], requesting_user_id=owner_id
        )
        original = repository._draw_snapshot

        async def checked_then_saved(session, expected_versions, pinned=()):
            await original(session, expected_versions, pinned)
            await repo.update_owned(
                owner_id, second.id, expected_version=second.version, name="Second",
                description="", prompts=(PromptListEntryInput(answer="beaver", aliases=("otter",)),),
            )

        monkeypatch.setattr(repository, "_draw_snapshot", checked_then_saved)
        drawn = await repo.sample_prompts(
            list(pinned.list_ids), limit=5, expected_versions=pinned.list_versions
        )

        assert sorted(prompt.answer for prompt in drawn.prompts) == ["otter", "panda"]
    finally:
        await engine.dispose()
