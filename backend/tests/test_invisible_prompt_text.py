"""Prompt-list text may not carry characters that draw nothing (#1245).

Two texts that differ only by a zero-width space, a soft hyphen or a word
joiner look identical and keyed differently: a moderator's takedown of
"badword" came back active as "bad<ZWSP>word", one list held "cat" three
times over, and a U+202E in a list's name turned the rest of the line around.
"""
from __future__ import annotations

import unicodedata

import pytest

from app.db.models import User, generate_uuid
from app.game import _normalize as normalize_guess_text
from app.prompt_content import (
    INVISIBLE_CHARACTER,
    MAX_COMBINING_MARKS,
    normalize_prompt_answer,
    prompt_match_key,
    prompt_match_variants,
)
from app.repositories.interfaces import PromptListEntryInput, PromptListMutationError
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository

from tests.dbfixtures import create_test_db

INVISIBLE = {
    "zero-width space": "​",
    "zero-width non-joiner": "‌",
    "zero-width joiner": "‍",
    "word joiner": "⁠",
    "soft hyphen": "­",
    "right-to-left override": "‮",
    "byte-order mark": "﻿",
    "variation selector": "️",
    "tag letter": "\U000e0041",
    "hangul filler": "ㅤ",
    "reserved default-ignorable": "\ufff0",
}

# Unicode 17's Default_Ignorable_Code_Point, from DerivedCoreProperties.txt
# (the list the client's `\p{Default_Ignorable_Code_Point}` reads). Reserved
# code points are in it on purpose: whatever they are assigned, they will
# draw nothing.
DEFAULT_IGNORABLE = (
    (0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160),
    (0x17B4, 0x17B5), (0x180B, 0x180F), (0x200B, 0x200F), (0x202A, 0x202E),
    (0x2060, 0x206F), (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)


def test_the_written_out_class_covers_every_default_ignorable_code_point():
    missing = [
        f"U+{point:04X}"
        for low, high in DEFAULT_IGNORABLE
        for point in range(low, high + 1)
        if not INVISIBLE_CHARACTER.match(chr(point))
    ]
    assert missing == []


def test_the_written_out_class_covers_every_format_character_this_python_knows():
    """Written out for speed, so checked against the Unicode data here: a
    newer Unicode adding a format character fails this, not a takedown."""
    missing = [
        f"U+{point:04X}"
        for point in range(0x110000)
        if unicodedata.category(chr(point)) == "Cf" and not INVISIBLE_CHARACTER.match(chr(point))
    ]
    assert missing == []
    # And nothing a word is written with.
    assert INVISIBLE_CHARACTER.search("abc\u00e9\u00fc\u00df\u0301\u4e00\u0416 ") is None


@pytest.mark.parametrize("character", INVISIBLE.values(), ids=INVISIBLE.keys())
def test_a_prompt_or_alias_carrying_one_is_refused(character):
    with pytest.raises(ValueError, match="invisible"):
        normalize_prompt_answer(f"bad{character}word")


@pytest.mark.parametrize("character", INVISIBLE.values(), ids=INVISIBLE.keys())
def test_it_keys_as_the_word_without_it(character):
    """So a hidden word stays hidden however it is respelled, and a guess
    pasted with one still lands."""
    assert prompt_match_key(f"bad{character}word") == prompt_match_key("badword")
    assert prompt_match_key(f"bad{character}word", "de") == prompt_match_key("badword", "de")
    assert prompt_match_variants(f"Mü{character}ller", "de") == prompt_match_variants("Müller", "de")


def test_a_guess_with_one_matches_the_answer():
    assert normalize_guess_text("c​at", "en") == normalize_guess_text("cat", "en")


@pytest.mark.parametrize("text", ["café", "café", "Müller", "ệ", "ệ", "naïve"])
def test_letters_and_their_accents_are_not_invisible(text):
    normalize_prompt_answer(text)


def test_marks_may_stack_only_so_high():
    normalize_prompt_answer("e" + "́" * MAX_COMBINING_MARKS)
    with pytest.raises(ValueError, match="marks"):
        normalize_prompt_answer("e" + "́" * (MAX_COMBINING_MARKS + 1))
    # Counted decomposed: a precomposed letter brings its own mark.
    assert len(unicodedata.normalize("NFD", "é")) == 2
    with pytest.raises(ValueError, match="marks"):
        normalize_prompt_answer("é" + "́" * MAX_COMBINING_MARKS)


# --- through the repository ------------------------------------------------------------


@pytest.fixture
async def owned():
    factory, engine = await create_test_db()
    owner = generate_uuid()
    async with factory() as session, session.begin():
        session.add(User(
            id=owner, username="lister", password_hash="hash", display_name="Lister",
            is_anonymous=False, state="registered",
        ))
    try:
        yield SqlAlchemyPromptListRepository(factory), str(owner)
    finally:
        await engine.dispose()


async def create(repo, owner, *, name="List", description="", prompts=("cat",), aliases=()):
    return await repo.create_owned(
        owner, name=name, description=description, language="en",
        prompts=[
            PromptListEntryInput(answer=answer, aliases=tuple(aliases) if index == 0 else ())
            for index, answer in enumerate(prompts)
        ],
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"name": "‮evil list"},
        {"name": "Lis​t"},
        {"description": "fine­words"},
        {"prompts": ("cat", "c​at")},
        {"prompts": ("cat",), "aliases": ("kit⁠ty",)},
    ],
    ids=["override-in-name", "zwsp-in-name", "shy-in-description", "zwsp-in-prompt", "wj-in-alias"],
)
async def test_the_repository_refuses_it_in_every_field(owned, fields):
    repo, owner = owned
    with pytest.raises(PromptListMutationError, match="invisible"):
        await create(repo, owner, **fields)


async def test_a_title_may_still_carry_an_emoji_built_with_a_joiner(owned):
    repo, owner = owned
    cook = "\U0001f9d1‍\U0001f373"
    created = await create(repo, owner, name=f"{cook} Kitchen", description=f"For every {cook}")
    assert created.name == f"{cook} Kitchen"
