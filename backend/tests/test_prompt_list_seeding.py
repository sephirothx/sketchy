"""Unit tests for prompt list seeding, REST API, selection, and usage metrics."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import (
    Prompt,
    PromptList,
    PromptTag,
    PromptVersion,
)
from app.db.seed import seed_prompt_lists
from app.domain_values import PROMPT_LANGUAGES, PromptLanguage
from app.prompt_content import (
    LIST_TAG_VOCABULARY,
    MAX_PLAYER_PROMPT_LISTS,
    PROMPT_SHELVES,
    default_prompt_list_slug,
    prompt_match_key,
)
from app.prompts import letter_histogram
from app.repositories.interfaces import (
    BundledPromptDefinition,
    PromptListEntryInput,
    PromptPickTotals,
    PromptSeedConflictError,
    PromptUsage,
    TooManyPlayerListsError,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)

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
        assert len(combined.list_ids) == 2

        first_list_ids = combined.list_ids
        await seed_prompt_lists(repo)
        assert (
            await repo.resolve_selection(
                ["english_standard", "english_extended"]
            )
        ).list_ids == first_list_ids
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
    so every supported language ships its Standard, Extended and Local - and
    each language's three lists have to be playable together. Themed official
    lists stand beside them (#1374), so the catalogue is not counted."""
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        seeded = await seed_prompt_lists(repo)
        slugs = {summary.slug for summary in seeded}
        assert {summary.language for summary in seeded} <= {
            *PROMPT_LANGUAGES,
            "zxx",
        }

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
            assert len(combined.list_ids) == 3
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


async def test_seeded_lists_carry_the_letter_histogram_of_their_prompts():
    """A list's stored tallies must equal counting its answers directly.

    This is the substitution wheel pricing depends on: summing these instead of
    walking a resident pool has to produce the same distribution, or letters are
    priced against content the game is not drawing from.
    """
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await seed_prompt_lists(repo)

        async with factory() as session:
            lists = (
                await session.execute(
                    select(PromptList).options(
                        selectinload(PromptList.prompts).selectinload(Prompt.prompt_version)
                    )
                )
            ).scalars().all()

            assert lists
            for seeded in lists:
                answers = [row.prompt_version.canonical_answer for row in seeded.prompts]
                expected_counts, expected_total = letter_histogram(answers)
                assert seeded.letter_counts == expected_counts
                assert seeded.letter_total == expected_total
                assert seeded.letter_total > 0
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
        assert pinned.list_ids == resolved.list_ids
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
        revisions = list(pinned.list_ids)

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
        revisions = list(pinned.list_ids)

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
        revisions = list(pinned.list_ids)
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
        revisions = list(pinned.list_ids)

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
            reseeded = (
                await session.execute(
                    select(PromptList)
                    .where(PromptList.slug == "reseeded")
                    .options(
                        selectinload(PromptList.prompts).selectinload(Prompt.prompt_version)
                    )
                )
            ).scalars().one()

        members = [row.prompt_version.canonical_answer for row in reseeded.prompts]
        assert sorted(members) == ["banjo", "fiddle", "kazoo"]
        assert any(
            row.prompt_version.moderation_state == "hidden" for row in reseeded.prompts
        )
        expected_counts, expected_total = letter_histogram(members)
        assert reseeded.letter_counts == expected_counts
        assert reseeded.letter_total == expected_total
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

    Autovacuum is switched off on the seeded tables first. Earlier tests'
    seeding leaves them for autovacuum to visit, and while it holds a table
    `ANALYZE (SKIP_LOCKED)` skips it - as it should, autovacuum being the
    fallback - so the count did not move in two of four parallel runs. The
    ALTER waits for (and cancels) a visit already under way.
    """
    import os

    from sqlalchemy import bindparam, text

    from app.db.roles import SEEDED_TABLES
    from tests.dbfixtures import create_test_engine

    factory, engine = await create_test_db()
    try:
        if engine.dialect.name != "postgresql":
            await seed_prompt_lists(SqlAlchemyPromptListRepository(factory))
            return
        owner_url = os.environ.get("TEST_OWNER_DATABASE_URL")
        owner = create_test_engine(owner_url) if owner_url else engine
        counted = text(
            "SELECT relname, analyze_count FROM pg_stat_user_tables "
            "WHERE relname IN :tables"
        ).bindparams(bindparam("tables", expanding=True))

        async def analyzed() -> dict[str, int]:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT pg_stat_clear_snapshot()"))
                rows = await connection.execute(counted, {"tables": list(SEEDED_TABLES)})
                return {name: int(count) for name, count in rows}

        async def autovacuum(enabled: bool) -> None:
            setting = "RESET (autovacuum_enabled)" if enabled else "SET (autovacuum_enabled = off)"
            async with owner.begin() as connection:
                for table in SEEDED_TABLES:
                    await connection.execute(text(f"ALTER TABLE {table} {setting}"))

        await autovacuum(False)
        try:
            before = await analyzed()
            await seed_prompt_lists(SqlAlchemyPromptListRepository(factory))
            after = await analyzed()
        finally:
            await autovacuum(True)
            if owner is not engine:
                await owner.dispose()
        assert set(before) == set(SEEDED_TABLES)
        assert [t for t in SEEDED_TABLES if after[t] <= before[t]] == []
    finally:
        await engine.dispose()


def _write_list(directory, slug: str, **fields) -> None:
    """One official list file, as `backend/data/prompt_lists` holds them."""
    body = {
        "slug": slug,
        "name": slug.title(),
        "language": "en",
        "version": 1,
        "shelf": "everyday",
        "position": 0,
        "prompts": [
            {"conceptId": "01a0f467-2040-7733-9e34-000000000001", "answer": "otter"},
            {"conceptId": "01a0f467-2040-7733-9e34-000000000002", "answer": "walrus"},
        ],
        **fields,
    }
    (directory / f"{slug}.json").write_text(json.dumps(body), encoding="utf-8")


async def test_official_lists_stand_on_shelves_and_name_their_family():
    """Every official list stands on a shelf the picker knows, in its place
    there, and a list every language translates names the family a mixed room
    plays it in - the same name on every copy (#1374)."""
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await seed_prompt_lists(repo)
        catalogue = {summary.slug: summary for summary in await repo.list_all()}

        assert all(summary.shelf in PROMPT_SHELVES for summary in catalogue.values())
        for language in PROMPT_LANGUAGES:
            stem = PromptLanguage(language).name.lower()
            standard = catalogue[f"{stem}_standard"]
            extended = catalogue[f"{stem}_extended"]
            local = catalogue[f"{stem}_local"]
            assert (standard.shelf, standard.shelf_position) == ("everyday", 0)
            assert (extended.shelf_position, local.shelf_position) == (1, 2)
            assert standard.family == "english_standard"
            assert extended.family == "english_extended"
            # Local is one language's own, so it is in no family.
            assert local.family is None
    finally:
        await engine.dispose()


async def test_an_official_list_moves_shelf_without_a_new_version(tmp_path):
    """Shelf, series, place and tags are navigation: a file that changes them
    and keeps its version seeds, where changed prompts would fail startup."""
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        _write_list(tmp_path, "critters")
        await seed_prompt_lists(repo, directory=tmp_path)
        first = await repo.get_by_slug("critters")
        assert first is not None
        assert (first.shelf, first.series, first.shelf_position, first.tags) == (
            "everyday",
            None,
            0,
            (),
        )

        _write_list(
            tmp_path,
            "critters",
            series="sea-life",
            position=4,
            tags=["nature", "animals"],
        )
        await seed_prompt_lists(repo, directory=tmp_path)
        moved = await repo.get_by_slug("critters")
        assert moved is not None
        assert moved.version == first.version
        assert (moved.series, moved.shelf_position) == ("sea-life", 4)
        # In the vocabulary's order, whatever order the file wrote them in.
        assert moved.tags == ("animals", "nature")

        _write_list(tmp_path, "critters", tags=[])
        await seed_prompt_lists(repo, directory=tmp_path)
        cleared = await repo.get_by_slug("critters")
        assert cleared is not None
        assert (cleared.series, cleared.tags) == (None, ())
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("fields", "complaint"),
    [
        ({"shelf": "nowhere"}, "Unknown shelf"),
        ({"series": "Not A Slug"}, "series"),
        ({"tags": ["not-a-tag"]}, "Unknown tag"),
    ],
)
async def test_an_official_list_in_no_known_place_fails_startup(
    tmp_path, fields, complaint
):
    """A typo in a seed file stops the server rather than opening a shelf of
    one, the way different content under a seen version does (R-PROMPT-06)."""
    factory, engine = await create_test_db()
    try:
        _write_list(tmp_path, "critters", **fields)
        with pytest.raises(ValueError, match=complaint):
            await seed_prompt_lists(
                SqlAlchemyPromptListRepository(factory), directory=tmp_path
            )
    finally:
        await engine.dispose()


async def test_an_official_list_must_name_a_shelf(tmp_path):
    factory, engine = await create_test_db()
    try:
        _write_list(tmp_path, "critters")
        body = json.loads((tmp_path / "critters.json").read_text(encoding="utf-8"))
        del body["shelf"]
        (tmp_path / "critters.json").write_text(json.dumps(body), encoding="utf-8")
        with pytest.raises(KeyError):
            await seed_prompt_lists(
                SqlAlchemyPromptListRepository(factory), directory=tmp_path
            )
    finally:
        await engine.dispose()


async def test_an_official_list_in_no_language_seeds_and_plays_anywhere(tmp_path):
    """The names that are the same in every language ship as one official list
    in none (`zxx`, R-PROMPT-12), which every room language may pick (#1374)."""
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        _write_list(tmp_path, "champions", language="zxx")
        await seed_prompt_lists(repo, directory=tmp_path)

        assert "champions" in {
            summary.slug for summary in await repo.list_all(language="de")
        }
        summary = await repo.get_by_slug("champions")
        assert summary is not None
        assert (summary.language, summary.family) == ("zxx", None)
        pinned = await repo.authorize_selection(
            ["champions"], expected_language="de"
        )
        assert pinned.prompt_count == 2
    finally:
        await engine.dispose()


async def test_a_room_may_hold_forty_lists_but_twenty_of_players(tmp_path):
    """The room-wide cap is forty so a whole series fits (#1374), but a
    player's list is where a selection's worst case lives, so no more than
    twenty of those - the ceiling #1237 measured."""
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        users = SqlAlchemyUserRepository(factory)
        guest = await users.create_anonymous("Owner")
        owner = await users.claim_account(guest.id, "Owner", "test-hash")
        owned = [
            (
                await repo.create_owned(
                    owner.id,
                    name=f"Mine {index}",
                    description="",
                    language="en",
                    prompts=(PromptListEntryInput(answer=f"otter{index}"),),
                )
            ).slug
            for index in range(MAX_PLAYER_PROMPT_LISTS + 1)
        ]
        allowed = await repo.authorize_selection(
            owned[:MAX_PLAYER_PROMPT_LISTS],
            requesting_user_id=owner.id,
            expected_language="en",
        )
        assert len(allowed.list_ids) == MAX_PLAYER_PROMPT_LISTS
        with pytest.raises(TooManyPlayerListsError):
            await repo.authorize_selection(
                owned, requesting_user_id=owner.id, expected_language="en"
            )
    finally:
        await engine.dispose()


async def test_an_official_list_tag_outside_the_vocabulary_is_a_seed_conflict():
    factory, engine = await create_test_db()
    try:
        with pytest.raises(PromptSeedConflictError):
            await SqlAlchemyPromptListRepository(factory).upsert_bundled(
                slug="critters",
                name="Critters",
                description="",
                language="en",
                prompts=[BundledPromptDefinition(str(uuid4()), "otter")],
                version=1,
                shelf="everyday",
                shelf_position=0,
                tags=["not-a-tag"],
            )
    finally:
        await engine.dispose()


async def test_the_pokemon_generations_are_families_a_mixed_room_plays():
    """Every Pokémon, one official list per generation in each of the eight
    languages (#1389): nine families on the Video games shelf, one series,
    pinned whole by a mixed room and combinable with each language's own lists
    without a collision."""
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await seed_prompt_lists(repo)
        catalogue = await repo.list_all()
        pokemon = [summary for summary in catalogue if summary.series == "pokemon"]
        assert len(pokemon) == 9 * len(PROMPT_LANGUAGES)
        assert {summary.shelf for summary in pokemon} == {"video-games"}
        assert {summary.family for summary in pokemon} == {
            f"english_pokemon_gen{n}" for n in range(1, 10)
        }
        assert sum(
            summary.prompt_count for summary in pokemon if summary.language == "en"
        ) == 1025

        generations = [f"german_pokemon_gen{n}" for n in range(1, 10)]
        mixed = await repo.authorize_selection(generations, expected_language="mul")
        assert len(mixed.list_ids) == 9 * len(PROMPT_LANGUAGES)
        assert mixed.prompt_count == 1025
        german = await repo.authorize_selection(
            ["german_standard", "german_extended", "german_local", *generations],
            expected_language="de",
        )
        assert german.prompt_count > 3000
    finally:
        await engine.dispose()


async def test_league_of_legends_plays_anywhere_and_the_icons_are_a_family():
    """The second video-game wave (#1390): every League of Legends champion as
    one official list in no language, which every room and a mixed one plays
    as it is, and video-game icons translated into all eight, a family."""
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await seed_prompt_lists(repo)
        champions = await repo.get_by_slug("league_of_legends")
        assert champions is not None
        assert (champions.language, champions.shelf, champions.family) == ("zxx", "video-games", None)
        icons = [
            summary for summary in await repo.list_all()
            if summary.slug.endswith("_video_game_icons")
        ]
        assert {summary.language for summary in icons} == set(PROMPT_LANGUAGES)
        assert {summary.family for summary in icons} == {"english_video_game_icons"}

        for language in PROMPT_LANGUAGES:
            stem = PromptLanguage(language).name.lower()
            pinned = await repo.authorize_selection(
                [f"{stem}_standard", f"{stem}_video_game_icons", "league_of_legends"],
                expected_language=language,
            )
            assert pinned.prompt_count == (
                (await repo.get_by_slug(f"{stem}_standard")).prompt_count
                + icons[0].prompt_count
                + champions.prompt_count
            ), language
        mixed = await repo.authorize_selection(
            ["polish_video_game_icons", "league_of_legends"], expected_language="mul"
        )
        assert len(mixed.list_ids) == len(PROMPT_LANGUAGES) + 1
    finally:
        await engine.dispose()
