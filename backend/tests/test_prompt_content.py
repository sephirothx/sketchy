"""Stable prompt identity, localized versions, aliases, and editorial metadata."""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    PromptAlias,
    PromptConcept,
    PromptTag,
    PromptVersion,
    PromptVersionAlias,
    PromptVersionTag,
)
from app.game import Game, Phase
from app.prompt_content import (
    best_supported_prompt_locale,
    clean_prompt_aliases,
    clean_prompt_tags,
    normalize_prompt_answer,
    validate_prompt_language,
)

from tests.dbfixtures import create_test_db


def test_language_aware_match_keys_and_bounded_metadata():
    assert validate_prompt_language("en") == "en"
    assert validate_prompt_language("fr") == "fr"
    assert normalize_prompt_answer("  CAFÉ  ", "en") == "cafe"
    assert normalize_prompt_answer("  ÉLÉPHANT  ", "fr") == "elephant"
    assert best_supported_prompt_locale("de-CH,de;q=0.9,en;q=0.8") == "de"
    assert best_supported_prompt_locale("zh-CN,ja;q=0.9") == "en"
    assert clean_prompt_aliases(
        ["Ice-cream", " ice cream ", "ICE-CREAM"],
        canonical_answer="ice cream cone",
        language="en",
    ) == ("Ice-cream", "ice cream")
    assert clean_prompt_tags(["food", "cold-things", "food"]) == (
        "food",
        "cold-things",
    )

    for invalid in ("English", "en_US", "zh"):
        with pytest.raises(ValueError):
            validate_prompt_language(invalid)
    with pytest.raises(ValueError):
        clean_prompt_tags(["Not A Slug"])


def test_exact_version_aliases_are_accepted_and_drive_near_miss_hints():
    game = Game(
        turn_order=["drawer", "guesser"],
        prompt_pool=["airplane"],
        prompt_aliases={"airplane": ("aeroplane",)},
        prompt_language="en",
    )
    game.phase = Phase.DRAWING
    game.current_drawer = "drawer"
    game.prompt = "airplane"
    game.phase_deadline = None

    assert game.guess_hint("guesser", "aeroplan") == "close"
    assert game.submit_guess("guesser", "AÉROPLANE")[0] is True

    other_version = Game(
        turn_order=["drawer", "guesser"],
        prompt_pool=["airplane"],
        prompt_aliases={},
        prompt_language="en",
    )
    other_version.phase = Phase.DRAWING
    other_version.current_drawer = "drawer"
    other_version.prompt = "airplane"
    assert other_version.submit_guess("guesser", "aeroplane")[0] is False


@pytest.mark.asyncio
async def test_prompt_concepts_do_not_merge_by_equal_text_and_links_are_explicit():
    factory, engine = await create_test_db()
    try:
        async with factory() as session:
            async with session.begin():
                first = PromptConcept()
                second = PromptConcept()
                session.add_all([first, second])
                await session.flush()
                first_version = PromptVersion(
                    concept_id=first.id,
                    language="en",
                    version=1,
                    canonical_answer="bat",
                    match_key="bat",
                    editorial_difficulty="easy",
                    content_rating="everyone",
                )
                second_version = PromptVersion(
                    concept_id=second.id,
                    language="en",
                    version=1,
                    canonical_answer="bat",
                    match_key="bat",
                    editorial_difficulty="hard",
                    content_rating="teen",
                )
                session.add_all([first_version, second_version])
                alias = PromptAlias(
                    concept_id=first.id,
                    language="en",
                    answer="baseball bat",
                    match_key="baseball bat",
                )
                tag = PromptTag(slug="sports", name="Sports")
                session.add_all([alias, tag])
                await session.flush()
                session.add_all(
                    [
                        PromptVersionAlias(
                            prompt_version_id=first_version.id,
                            alias_id=alias.id,
                        ),
                        PromptVersionTag(
                            prompt_version_id=first_version.id,
                            tag_id=tag.id,
                        ),
                    ]
                )

        assert first.id != second.id
        assert first_version.id != second_version.id

        async with factory() as session:
            duplicate = PromptVersion(
                concept_id=first.id,
                language="en",
                version=1,
                canonical_answer="changed metadata only",
                match_key="changed metadata only",
            )
            session.add(duplicate)
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()
