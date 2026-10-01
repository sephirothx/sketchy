"""The bundled prompt lists, read as content rather than seeded (#1367).

Seeding checks each file on its own - one conceptId and one answer key per
concept - and a room checks what it selected. Neither says whether the
catalogue is the one R-PROMPT-01 describes: that every language holds the same
Standard concepts, that there are enough of them to keep a regular crowd from
seeing the same words every evening, and that a language's lists can be picked
together. An alias that another concept answers to is not refused by the seed
at all; the first host to select both lists would meet it as a refusal. These
tests read the files directly, so a gap in the content fails here, by name,
instead of in a room.
"""
from __future__ import annotations

import json
from collections import defaultdict
from functools import cache

import pytest

from app.api.prompt_lists import MAX_PAGE_SIZE
from app.db.seed import DEFAULT_PROMPT_LISTS_DIR as PROMPT_LIST_DIR
from app.domain_values import PROMPT_LANGUAGES, PromptLanguage
from app.prompt_content import MAX_PROMPT_LENGTH, prompt_match_key

#: Every Standard list holds at least this many concepts. A game draws
#: `rounds x players x 3` offers - up to 480 - so a list of a few hundred
#: repeats itself within an evening; a thousand does not.
STANDARD_FLOOR = 1000

#: Standard is mostly single words: it is the list a room opens on, and one
#: word is what a new player expects to type. A share rather than a ban,
#: because a language spells some things with a preposition where English
#: and German compound them - "machine à laver", "balão de ar quente" - and
#: the concept should not be dropped for the grammar of one language.
STANDARD_SINGLE_WORD_SHARE = 0.80
STANDARD_MAX_WORDS = 4


@cache
def _list(slug: str) -> dict:
    return json.loads((PROMPT_LIST_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def _slugs(language: str) -> list[str]:
    """Every bundled list in `language`: the lists a room in it can combine."""
    return sorted(
        path.stem
        for path in PROMPT_LIST_DIR.glob("*.json")
        if _list(path.stem)["language"] == language
    )


def _stem(language: str) -> str:
    return PromptLanguage(language).name.lower()


def _concepts(slug: str) -> set[str]:
    return {entry["conceptId"] for entry in _list(slug)["prompts"]}


@pytest.mark.parametrize("language", PROMPT_LANGUAGES)
def test_standard_is_large_enough(language):
    prompts = _list(f"{_stem(language)}_standard")["prompts"]
    assert len(prompts) >= STANDARD_FLOOR


def test_standard_is_the_same_concepts_in_every_language():
    """A mixed room pins Standard in every language at once (R-PROMPT-13),
    which it can only do when each language's list holds exactly the same
    concepts: one missing anywhere and the family stops being one."""
    english = _concepts("english_standard")
    for language in PROMPT_LANGUAGES:
        slug = f"{_stem(language)}_standard"
        concepts = _concepts(slug)
        assert concepts - english == set(), slug
        assert english - concepts == set(), slug


@pytest.mark.parametrize("language", PROMPT_LANGUAGES)
def test_standard_is_mostly_single_words(language):
    answers = [entry["answer"] for entry in _list(f"{_stem(language)}_standard")["prompts"]]
    too_long = [answer for answer in answers if len(answer.split()) > STANDARD_MAX_WORDS]
    assert too_long == []
    single = sum(1 for answer in answers if len(answer.split()) == 1)
    assert single / len(answers) >= STANDARD_SINGLE_WORD_SHARE, single / len(answers)


@pytest.mark.parametrize("language", PROMPT_LANGUAGES)
def test_no_concept_appears_twice_in_a_list(language):
    for slug in _slugs(language):
        ids = [entry["conceptId"] for entry in _list(slug)["prompts"]]
        duplicates = {concept for concept in ids if ids.count(concept) > 1}
        assert duplicates == set(), slug


@pytest.mark.parametrize("language", PROMPT_LANGUAGES)
def test_every_answer_fits(language):
    for slug in _slugs(language):
        for entry in _list(slug)["prompts"]:
            for text in (entry["answer"], *entry.get("aliases", ())):
                assert len(" ".join(text.split())) <= MAX_PROMPT_LENGTH, (slug, text)


@pytest.mark.parametrize("language", PROMPT_LANGUAGES)
def test_a_languages_lists_can_be_picked_together(language):
    """No two concepts may answer to the same key across a language's lists,
    answers and aliases alike: a room that selects both would be refused as
    ambiguous (R-PROMPT-01), and the seed never looks at aliases across
    concepts. A concept deliberately repeated in two lists is one concept."""
    owners: dict[str, set[str]] = defaultdict(set)
    where: dict[str, set[str]] = defaultdict(set)
    for slug in _slugs(language):
        for entry in _list(slug)["prompts"]:
            for text in (entry["answer"], *entry.get("aliases", ())):
                key = prompt_match_key(text, language)
                owners[key].add(entry["conceptId"])
                where[key].add(f"{slug}:{text}")
    clashes = {key: sorted(where[key]) for key, concepts in owners.items() if len(concepts) > 1}
    assert clashes == {}


def test_the_stats_page_reads_every_bundled_list_whole():
    """The stats page asks for a list in one page of at most `MAX_PAGE_SIZE`;
    a bundled list longer than that would be cut short without a word."""
    for path in PROMPT_LIST_DIR.glob("*.json"):
        assert len(_list(path.stem)["prompts"]) <= MAX_PAGE_SIZE, path.stem
