"""Unit tests for prompt list seeding, REST API, selection, and usage metrics."""
from __future__ import annotations

from uuid import uuid4

import pytest

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import (
    PromptListRevision,
    PromptListRevisionItem,
    PromptTag,
    PromptVersion,
)
from app.db.seed import seed_prompt_lists
from app.domain_values import PROMPT_LANGUAGES, PromptLanguage
from app.prompt_content import (
    LIST_TAG_VOCABULARY,
    default_prompt_list_slug,
    prompt_match_key,
)
from app.prompts import letter_histogram
from app.repositories.interfaces import (
    BundledPromptDefinition,
    PromptPickTotals,
    PromptUsage,
)
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository

from tests.dbfixtures import create_test_db


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
        assert len(std_words) >= 1000
        assert "airplane" in std_words
        assert "accordion" in std_words

        ext_words = await repo.get_prompts_by_slugs(["english_extended"])
        assert len(ext_words) >= 1000
        assert "albatross" in ext_words

        # Extended sits beside Standard rather than repeating it.
        combined = await repo.resolve_selection(
            ["english_standard", "english_extended"]
        )
        assert len(combined.prompts) == len(std_words) + len(ext_words)
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


async def test_a_concept_in_two_selected_lists_is_one_prompt():
    """Equal text shares a concept only where the files repeat its id, and a
    concept a room selects twice is drawn as one prompt (R-PROMPT-03)."""
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        shared = str(uuid4())
        for slug, other in (("first", "otter"), ("second", "walrus")):
            await repo.upsert_bundled(
                slug=slug,
                name=slug,
                description="",
                language="en",
                prompts=[
                    BundledPromptDefinition(shared, "anchor"),
                    BundledPromptDefinition(str(uuid4()), other),
                ],
                version=1,
            )
        combined = await repo.resolve_selection(["first", "second"])
        assert sorted(combined.prompts) == ["anchor", "otter", "walrus"]
    finally:
        await engine.dispose()


async def test_every_supported_language_ships_its_three_lists():
    """A room may only be opened in a language that has content (R-PROMPT-01),
    so the eight supported languages and the bundled catalogue have to be the
    same set - and each language's three lists have to be playable together."""
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        seeded = await seed_prompt_lists(repo)
        slugs = {summary.slug for summary in seeded}
        assert len(slugs) == 3 * len(PROMPT_LANGUAGES)

        for language in PROMPT_LANGUAGES:
            stem = PromptLanguage(language).name.lower()
            lists = [f"{stem}_standard", f"{stem}_extended", f"{stem}_local"]
            assert set(lists) <= slugs, language
            assert default_prompt_list_slug(language) == lists[0]

            # All three at once is where a collision between the shared lists
            # and the local one would show up as a refusal rather than as a
            # bad prompt.
            combined = await repo.resolve_selection(lists)
            assert combined.language == language
            assert len(combined.revision_ids) == 3
            assert len(combined.prompts) > 2000

            keys = [
                prompt_match_key(answer, language) for answer in combined.prompts
            ]
            assert len(keys) == len(set(keys)), language
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
            selection.list_ids,
            PromptUsage(
                offers={apple_id: 1, banana_id: 1, robot_id: 1},
                sources={
                    version: selection.list_ids for version in (apple_id, banana_id, robot_id)
                },
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
            assert prompt.source_list_ids == pinned.list_ids

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


async def test_repeated_draws_reach_across_the_whole_pool():
    """The draw has to be random across the whole revision, not a stable prefix.

    Asserting *total* coverage would be asserting a coin lands heads enough
    times. Each draw takes a fifth of the list, so 40 of them leave any one
    prompt untouched with probability 0.8^40, about 1 in 7,500: the expected
    number missed is well under one for a list of a thousand, and the margin
    below is far outside anything sampling produces while still being nowhere
    near the one draw's worth a fixed prefix would reach.
    """
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await seed_prompt_lists(repo)
        pinned = await repo.authorize_selection(["english_standard"])
        revisions = list(pinned.revision_ids)
        draw = pinned.prompt_count // 5

        seen: set[str] = set()
        for _ in range(40):
            seen |= {
                prompt.answer
                for prompt in (
                    await repo.sample_prompts(revisions, limit=draw)
                ).prompts
            }

        assert len(seen) >= pinned.prompt_count - 20
        # A stable prefix would stop at one draw's worth however many we take.
        assert len(seen) > draw
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


async def test_a_reseeded_revision_counts_content_moderation_has_hidden():
    """Seeding reuses an existing version even when it is hidden.

    That makes a hidden version a member of a *newly written* revision, so a
    histogram built from "active at write time" would omit it - and omit it
    permanently, because restoring the version writes no new revision. The
    counts follow membership, which cannot change, instead.
    """
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        concepts = {name: str(uuid4()) for name in ("banjo", "kazoo", "fiddle")}

        def definition(answer: str) -> BundledPromptDefinition:
            return BundledPromptDefinition(
                concept_id=concepts[answer], answer=answer, prompt_version=1
            )

        await repo.upsert_bundled(
            slug="reseeded",
            name="Reseeded",
            description="",
            language="en",
            version=1,
            prompts=[definition("banjo"), definition("kazoo")],
        )
        async with factory() as session:
            async with session.begin():
                hidden = (
                    await session.execute(
                        select(PromptVersion).where(
                            PromptVersion.canonical_answer == "kazoo"
                        )
                    )
                ).scalars().one()
                hidden.moderation_state = "hidden"

        await repo.upsert_bundled(
            slug="reseeded",
            name="Reseeded",
            description="",
            language="en",
            version=2,
            prompts=[definition("banjo"), definition("kazoo"), definition("fiddle")],
        )

        async with factory() as session:
            revision = (
                await session.execute(
                    select(PromptListRevision)
                    .options(
                        selectinload(PromptListRevision.items).selectinload(
                            PromptListRevisionItem.prompt_version
                        )
                    )
                    .order_by(PromptListRevision.version.desc())
                )
            ).scalars().first()

        members = [item.prompt_version.canonical_answer for item in revision.items]
        assert sorted(members) == ["banjo", "fiddle", "kazoo"]
        assert any(
            item.prompt_version.moderation_state == "hidden"
            for item in revision.items
        )
        expected_counts, expected_total = letter_histogram(members)
        assert revision.letter_counts == expected_counts
        assert revision.letter_total == expected_total
    finally:
        await engine.dispose()


async def test_seeding_makes_the_tag_vocabulary_present_and_keeps_names_current():
    """The vocabulary is bundled content, and a rename changes the name only.

    A slug is referenced by every revision tagged with it, so renaming a tag
    means changing its display name; changing the slug would orphan the rows
    that already point at it (R-LIST-18).
    """
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await repo.seed_list_tags()
        await repo.seed_list_tags()

        async with factory() as session:
            rows = (
                await session.scalars(
                    select(PromptTag).where(
                        PromptTag.slug.in_([slug for slug, _ in LIST_TAG_VOCABULARY])
                    )
                )
            ).all()
        assert {row.slug for row in rows} == {
            slug for slug, _ in LIST_TAG_VOCABULARY
        }, "seeding twice is seeding once"
        assert dict((row.slug, row.name) for row in rows) == dict(LIST_TAG_VOCABULARY)

        async with factory() as session:
            async with session.begin():
                stale = await session.scalar(
                    select(PromptTag).where(PromptTag.slug == "animals")
                )
                stale.name = "Beasts"
                stale_id = stale.id
        await repo.seed_list_tags()
        async with factory() as session:
            renamed = await session.get(PromptTag, stale_id)
        assert renamed.name == "Animals"
        assert renamed.id == stale_id, "the row is the same row; only the name moved"
    finally:
        await engine.dispose()


async def test_seeding_analyzes_what_it_wrote():
    """A freshly seeded PostgreSQL database planned a thousand-prompt list's
    aliases as a nested loop over every alias - two million comparisons, and
    a statement timeout on a busy runner - until something analyzed it
    (#1367). Seeding analyzes what it wrote; elsewhere there is nothing to do.

    Counted rather than read off the estimates: the suite empties tables with
    DELETE, so an estimate from an earlier test survives into this one.
    """
    from sqlalchemy import text

    factory, engine = await create_test_db()
    try:
        if engine.dialect.name != "postgresql":
            await seed_prompt_lists(SqlAlchemyPromptListRepository(factory))
            return
        counted = text(
            "SELECT coalesce(sum(analyze_count), 0) FROM pg_stat_user_tables "
            "WHERE relname = 'prompt_aliases'"
        )

        async def analyzed() -> int:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT pg_stat_clear_snapshot()"))
                return int(await connection.scalar(counted))

        before = await analyzed()
        await seed_prompt_lists(SqlAlchemyPromptListRepository(factory))
        assert await analyzed() > before
    finally:
        await engine.dispose()
