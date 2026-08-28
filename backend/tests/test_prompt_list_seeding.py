"""Unit tests for prompt list seeding, REST API, selection, and usage metrics."""
from __future__ import annotations

import pytest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.db.models import Base, PromptListRevision, PromptListRevisionItem
from app.db.seed import seed_prompt_lists
from app.prompts import letter_histogram
from app.repositories.interfaces import (
    PromptPickTotals,
    PromptUsage,
)
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository

pytestmark = pytest.mark.asyncio


async def create_test_db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return factory, engine


async def test_seed_bundled_prompt_lists():
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        seeded = await seed_prompt_lists(repo)
        assert len(seeded) >= 2

        slugs = {wl.slug for wl in seeded}
        assert "english_standard" in slugs
        assert "english_extended" in slugs

        std_words = await repo.get_prompts_by_slugs(["english_standard"])
        assert len(std_words) > 200
        assert "airplane" in std_words
        assert "guitar" in std_words

        ext_words = await repo.get_prompts_by_slugs(["english_extended"])
        assert len(ext_words) > 400
        assert "accordion" in ext_words

        combined_words = await repo.get_prompts_by_slugs(["english_standard", "english_extended"])
        assert len(combined_words) >= len(std_words)
        combined = await repo.resolve_selection(
            ["english_standard", "english_extended"]
        )
        assert combined.prompts.count("anchor") == 1
        assert len(combined.revision_ids) == 2

        first_revision_ids = combined.revision_ids
        await seed_prompt_lists(repo)
        assert (
            await repo.resolve_selection(
                ["english_standard", "english_extended"]
            )
        ).revision_ids == first_revision_ids
    finally:
        await engine.dispose()


async def test_legacy_text_only_seed_format_is_rejected(tmp_path):
    source = tmp_path / "legacy.json"
    source.write_text(
        """{
          "slug": "legacy",
          "name": "Legacy",
          "language": "en",
          "version": 1,
          "prompts": ["text-keyed prompt"]
        }""",
        encoding="utf-8",
    )
    factory, engine = await create_test_db()
    try:
        with pytest.raises(ValueError, match="stable conceptId"):
            await seed_prompt_lists(
                SqlAlchemyPromptListRepository(factory), directory=tmp_path
            )
    finally:
        await engine.dispose()


async def test_prompt_usage_tracking_metrics():
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await seed_prompt_lists(repo)
        selection = await repo.resolve_selection(["english_standard"])
        apple_id = selection.prompt_version_ids["apple"]
        banana_id = selection.prompt_version_ids["banana"]
        robot_id = selection.prompt_version_ids["robot"]

        # One game: "apple", "banana" and "robot" offered, "robot" drawn and
        # guessed by 2 of 3 possible guessers.
        await repo.record_prompt_usage(
            selection.revision_ids,
            PromptUsage(
                offers={apple_id: 1, banana_id: 1, robot_id: 1},
                picks={
                    robot_id: PromptPickTotals(
                        picks=1, correct_guesses=2, total_guessers=3
                    )
                },
            ),
        )

        word_stats_list = await repo.get_prompt_stats("english_standard")
        stats = next((w for w in word_stats_list if w.text == "robot"), None)
        assert stats is not None
        assert stats.offer_count == 1
        assert stats.pick_count == 1
        assert stats.correct_guess_count == 2
        assert stats.total_guesser_count == 3
        assert stats.pick_rate == 1.0
        assert stats.correct_guess_ratio == round(2 / 3, 4)

        # Banana was offered but not picked
        banana_stats = next((w for w in word_stats_list if w.text == "banana"), None)
        assert banana_stats is not None
        assert banana_stats.offer_count == 1
        assert banana_stats.pick_count == 0
        assert banana_stats.correct_guess_count == 0
        assert banana_stats.total_guesser_count == 0
        assert banana_stats.pick_rate == 0.0
        assert banana_stats.correct_guess_ratio == 0.0
    finally:
        await engine.dispose()


async def test_seeded_revisions_carry_the_letter_histogram_of_their_prompts():
    """A revision's stored tallies must equal counting its answers directly.

    This is the substitution wheel pricing depends on: summing these instead of
    walking a resident pool has to produce the same distribution, or letters are
    priced against content the game is not drawing from.
    """
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await seed_prompt_lists(repo)

        async with factory() as session:
            revisions = (
                await session.execute(
                    select(PromptListRevision).options(
                        selectinload(PromptListRevision.items).selectinload(
                            PromptListRevisionItem.prompt_version
                        )
                    )
                )
            ).scalars().all()

            assert revisions
            for revision in revisions:
                answers = [
                    item.prompt_version.canonical_answer for item in revision.items
                ]
                expected_counts, expected_total = letter_histogram(answers)
                assert revision.letter_counts == expected_counts
                assert revision.letter_total == expected_total
                assert revision.letter_total > 0
    finally:
        await engine.dispose()



async def test_pinning_agrees_with_resolution_about_what_a_selection_holds():
    """The count that sizes a game's draw must be the pool resolution would build."""
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await seed_prompt_lists(repo)
        slugs = ["english_standard", "english_extended"]

        pinned = await repo.authorize_selection(slugs)
        resolved = await repo.resolve_selection(slugs)

        assert pinned.prompt_count == len(resolved.prompts)
        assert pinned.revision_ids == resolved.revision_ids
        assert pinned.language == resolved.language
    finally:
        await engine.dispose()


async def test_summed_histograms_price_letters_like_the_pool_they_replace():
    """Wheel pricing must survive the substitution.

    Summing per-revision tallies double-counts a prompt that sits in two
    selected lists, where the merged pool holds it once. That is the drift this
    design accepts, so the test pins how small it is rather than pretending it
    is zero - the price is a clamped multiplier, and a fraction of a percent
    cannot move it.
    """
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await seed_prompt_lists(repo)
        slugs = ["english_standard", "english_extended"]

        pinned = await repo.authorize_selection(slugs)
        pool = (await repo.resolve_selection(slugs)).prompts
        expected_counts, expected_total = letter_histogram(pool)

        assert pinned.letter_total >= expected_total
        assert (pinned.letter_total - expected_total) / expected_total < 0.01
        for letter, count in expected_counts.items():
            assert abs(pinned.letter_counts.get(letter, 0) - count) <= 2

        # A single list has no cross-list duplicate, so there it is exact.
        only_standard = await repo.authorize_selection(["english_standard"])
        exact_counts, exact_total = letter_histogram(
            (await repo.resolve_selection(["english_standard"])).prompts
        )
        assert only_standard.letter_counts == exact_counts
        assert only_standard.letter_total == exact_total
    finally:
        await engine.dispose()


async def test_sampling_draws_distinct_prompts_and_records_where_each_came_from():
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await seed_prompt_lists(repo)
        pinned = await repo.authorize_selection(["english_standard"])
        revisions = list(pinned.revision_ids)

        sample = await repo.sample_prompts(revisions, limit=72)

        assert len(sample.prompts) == 72
        assert sample.drawable == pinned.prompt_count
        assert len({prompt.answer for prompt in sample.prompts}) == 72
        for prompt in sample.prompts:
            assert prompt.prompt_version_id
            assert prompt.source_revision_ids == tuple(revisions)

        # Nothing is drawn without somewhere to draw from.
        assert (await repo.sample_prompts(revisions, limit=0)).prompts == ()
        assert (await repo.sample_prompts([], limit=5)).prompts == ()
    finally:
        await engine.dispose()


async def test_sampling_skips_answers_a_room_has_already_shadowed():
    """A quick prompt of the same name wins, so the curated twin must not be drawn."""
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await seed_prompt_lists(repo)
        pinned = await repo.authorize_selection(["english_standard"])
        revisions = list(pinned.revision_ids)

        shadowed = {
            prompt.match_key
            for prompt in (
                await repo.sample_prompts(revisions, limit=10)
            ).prompts
        }
        sample = await repo.sample_prompts(
            revisions, limit=pinned.prompt_count, exclude_match_keys=shadowed
        )

        assert not shadowed & {prompt.match_key for prompt in sample.prompts}
        assert sample.drawable == pinned.prompt_count - len(shadowed)
        assert len(sample.prompts) == sample.drawable
    finally:
        await engine.dispose()


async def test_repeated_draws_reach_every_prompt_in_the_pool():
    """The draw has to be random across the whole revision, not a stable prefix."""
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await seed_prompt_lists(repo)
        pinned = await repo.authorize_selection(["english_standard"])
        revisions = list(pinned.revision_ids)

        seen: set[str] = set()
        for _ in range(40):
            seen |= {
                prompt.answer
                for prompt in (
                    await repo.sample_prompts(revisions, limit=50)
                ).prompts
            }

        assert len(seen) == pinned.prompt_count
    finally:
        await engine.dispose()


async def test_a_draw_that_excludes_most_of_a_list_still_fills_from_the_rest():
    """Asking for every drawable prompt must return every drawable prompt.

    A room whose quick prompts shadow most of its lists still has the rest to
    play. Drawing a small surplus and filtering afterwards silently returns
    fewer than were asked for, and the game starts on a thinner pool that
    repeats itself sooner.
    """
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await seed_prompt_lists(repo)
        pinned = await repo.authorize_selection(["english_standard"])
        revisions = list(pinned.revision_ids)

        everything = await repo.sample_prompts(
            revisions, limit=pinned.prompt_count
        )
        shadowed = {prompt.match_key for prompt in everything.prompts[:200]}
        drawable = pinned.prompt_count - len(shadowed)

        sample = await repo.sample_prompts(
            revisions, limit=drawable, exclude_match_keys=shadowed
        )

        assert sample.drawable == drawable
        assert len(sample.prompts) == drawable
        assert not shadowed & {prompt.match_key for prompt in sample.prompts}
    finally:
        await engine.dispose()
