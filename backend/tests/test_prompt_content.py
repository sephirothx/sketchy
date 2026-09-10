"""Stable prompt identity, localized versions, aliases, and editorial metadata."""
from __future__ import annotations

import unicodedata

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
    prompt_match_key,
    prompt_match_variants,
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


def test_a_language_folds_the_way_it_is_written_rather_than_the_way_english_is():
    """German writes an unavailable umlaut out, so "ae" is a spelling of "ä"
    and not a typo. The shared accent fold alone gives "madchen", which nobody
    writes, and would tell a German player they were wrong."""
    assert prompt_match_key("Mädchen", "de") == "maedchen"
    assert prompt_match_variants("Mädchen", "de") == {"maedchen", "madchen"}
    assert prompt_match_variants("Maedchen", "de") == {"maedchen"}
    assert prompt_match_variants("Madchen", "de") == {"madchen"}
    # ß needs no rule of its own: case-folding already writes it out.
    assert prompt_match_key("Fußball", "de") == "fussball"
    assert prompt_match_key("Fussball", "de") == "fussball"
    # French ligatures are letters rather than letters with a mark, so the
    # accent fold never reaches them; "coeur" is how the word is typed.
    assert prompt_match_key("cœur", "fr") == "coeur"
    assert prompt_match_variants("cœur", "fr") == {"coeur", "cœur"}
    assert prompt_match_variants("coeur", "fr") == {"coeur"}
    # The Dutch digraph's single codepoint is the two letters everyone types.
    assert prompt_match_key("ĳsbeer", "nl") == "ijsbeer"

    # The other five are unchanged: one canonical spelling, accents folded.
    for language, written, folded in (
        ("en", "Café", "cafe"),
        ("fr", "Éléphant", "elephant"),
        ("es", "Año", "ano"),
        ("it", "Città", "citta"),
        ("pt", "Coração", "coracao"),
    ):
        assert prompt_match_key(written, language) == folded
        assert prompt_match_variants(written, language) == {folded}
    # An umlaut in an English room still folds the shared way: the rule
    # belongs to the room's language, not to the character.
    assert prompt_match_key("Mädchen", "en") == "madchen"

    # Both Unicode spellings of the same word fold to one key. A macOS
    # filename or an IME hands over the decomposed form, where the umlaut is
    # a letter and a combining mark rather than the letter the German table
    # is written in - and the two are canonically equivalent, so a key that
    # told them apart would be an identity that depends on how the text was
    # typed.
    for written, language in (
        ("Mädchen", "de"), ("Fußball", "de"), ("café", "fr"), ("Città", "it"),
    ):
        decomposed = unicodedata.normalize("NFD", written)
        assert decomposed != written or "ß" in written
        assert prompt_match_key(decomposed, language) == prompt_match_key(
            written, language
        ), written
        assert prompt_match_variants(decomposed, language) == prompt_match_variants(
            written, language
        ), written
    assert "maedchen" in prompt_match_variants(
        unicodedata.normalize("NFD", "Mädchen"), "de"
    )


def test_a_german_room_accepts_both_spellings_without_widening_near_misses():
    game = Game(
        turn_order=["drawer", "guesser"],
        prompt_pool=["Mädchen"],
        prompt_language="de",
    )
    game.phase = Phase.DRAWING
    game.current_drawer = "drawer"
    game.prompt = "Mädchen"
    game.phase_deadline = None

    assert game.submit_guess("guesser", "Maedchen")[0] is True

    for written in ("Mädchen", "Madchen", "mädchen"):
        room = Game(
            turn_order=["drawer", "guesser"],
            prompt_pool=["Mädchen"],
            prompt_language="de",
        )
        room.phase = Phase.DRAWING
        room.current_drawer = "drawer"
        room.prompt = "Mädchen"
        room.phase_deadline = None
        assert room.submit_guess("guesser", written)[0] is True, written

    # Wider acceptance, not wider anything else: a different word is still
    # wrong, and a near miss is still measured on the canonical spelling.
    missed = Game(
        turn_order=["drawer", "guesser"],
        prompt_pool=["Mädchen"],
        prompt_language="de",
    )
    missed.phase = Phase.DRAWING
    missed.current_drawer = "drawer"
    missed.prompt = "Mädchen"
    missed.phase_deadline = None
    assert missed.submit_guess("guesser", "Männchen")[0] is False
    assert missed.guess_hint("guesser", "Maedche") == "close"


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
