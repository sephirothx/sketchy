"""The bundled prompt lists, read as content rather than seeded (#1367).

Seeding checks each file on its own - one conceptId and one answer key per
concept - and a room checks what it selected. Neither says whether the
catalogue is the one R-PROMPT-01 describes: that every language holds the same
Standard and Extended concepts, that there are enough of them to keep a regular
crowd from seeing the same words every evening, that Local stays its own
language's, and that a language's lists can be picked together. An alias that another concept answers to is not refused by the seed
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
from app.domain_values import AGNOSTIC_PROMPT_LANGUAGE, PROMPT_LANGUAGES, PromptLanguage
from app.prompt_content import MAX_PROMPT_LENGTH, PROMPT_SHELVES, prompt_match_key

#: Every Standard and Extended list holds at least this many concepts. A game
#: draws `rounds x players x 3` offers - up to 480 - so a list of a few hundred
#: repeats itself within an evening; a thousand does not.
FLOOR = 1000

#: The lists every language spells concept for concept: the families a mixed
#: room can pin (R-PROMPT-13). Local is the one that is not.
SHARED = ("standard", "extended")

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
    """Every bundled list a room in `language` can combine: its own, and the
    ones in no language (`zxx`, R-PROMPT-12), which every room may pick."""
    return sorted(
        path.stem
        for path in PROMPT_LIST_DIR.glob("*.json")
        if _list(path.stem)["language"] in (language, AGNOSTIC_PROMPT_LANGUAGE)
    )


def _stem(language: str) -> str:
    return PromptLanguage(language).name.lower()


def _concepts(slug: str) -> set[str]:
    return {entry["conceptId"] for entry in _list(slug)["prompts"]}


@pytest.mark.parametrize("tier", SHARED)
@pytest.mark.parametrize("language", PROMPT_LANGUAGES)
def test_the_shared_lists_are_large_enough(language, tier):
    prompts = _list(f"{_stem(language)}_{tier}")["prompts"]
    assert len(prompts) >= FLOOR


@pytest.mark.parametrize("tier", SHARED)
def test_a_shared_list_is_the_same_concepts_in_every_language(tier):
    """A mixed room pins Standard or Extended in every language at once
    (R-PROMPT-13), which it can only do when each language's list holds exactly
    the same concepts: one missing anywhere and the family stops being one."""
    english = _concepts(f"english_{tier}")
    for language in PROMPT_LANGUAGES:
        slug = f"{_stem(language)}_{tier}"
        concepts = _concepts(slug)
        assert concepts - english == set(), slug
        assert english - concepts == set(), slug


def test_standard_and_extended_share_no_concept():
    """Extended is the harder list beside Standard, not a superset of it: a room
    that picks both draws from both, and a concept in each would only be one
    prompt with two chances of being offered."""
    assert _concepts("english_standard") & _concepts("english_extended") == set()


@pytest.mark.parametrize("language", PROMPT_LANGUAGES)
def test_local_is_its_own_languages(language):
    """Local holds what does not travel, so none of it may be a concept another
    language spells - nor one of the shared lists, which every language does."""
    local = _concepts(f"{_stem(language)}_local")
    assert local
    elsewhere = set()
    for path in PROMPT_LIST_DIR.glob("*.json"):
        if path.stem != f"{_stem(language)}_local":
            elsewhere |= _concepts(path.stem)
    assert local & elsewhere == set()


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
    concepts. A concept deliberately repeated in two lists is one concept. A
    list in no language is keyed as a room in this one keys it - so "Müller"
    beside a German "Mueller" clashes here and nowhere else."""
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


def test_every_official_list_has_its_own_place_on_a_known_shelf():
    """The picker's tree (#1374) orders a shelf, or a series on it, by each
    list's position: two lists of one language in the same place would sort
    by whatever order the server happened to return."""
    places: dict[tuple, list[str]] = defaultdict(list)
    for path in PROMPT_LIST_DIR.glob("*.json"):
        body = _list(path.stem)
        assert body["shelf"] in PROMPT_SHELVES, path.stem
        places[
            (body["language"], body["shelf"], body.get("series"), body.get("position", 0))
        ].append(path.stem)
    assert {place: slugs for place, slugs in places.items() if len(slugs) > 1} == {}


def test_every_themed_official_list_is_a_family_or_in_no_language():
    """A themed official list ships translated into every language - the same
    concepts, so a mixed room can pin it whole - or as one list in no language
    (R-PROMPT-01, R-PROMPT-12, #1374). One that reached only some languages
    would be offered in some rooms and refused as a family in mixed ones."""
    by_language: dict[str, dict[frozenset, str]] = defaultdict(dict)
    themed = []
    for path in PROMPT_LIST_DIR.glob("*.json"):
        body = _list(path.stem)
        if body["language"] == AGNOSTIC_PROMPT_LANGUAGE or path.stem.endswith("_local"):
            continue
        concepts = frozenset(_concepts(path.stem))
        by_language[body["language"]][concepts] = path.stem
        if body["shelf"] != "everyday":
            themed.append((path.stem, concepts))
    for slug, concepts in themed:
        missing = [lang for lang in PROMPT_LANGUAGES if concepts not in by_language[lang]]
        assert missing == [], (slug, missing)


@pytest.mark.parametrize("language", PROMPT_LANGUAGES)
def test_a_series_is_one_list_per_place(language):
    """A series - the Pokémon generations - is ordered by position, and a
    concept belongs to one of its lists: a Pokémon in two generations would be
    offered twice as often to a room that chose the whole series."""
    seen: dict[str, str] = {}
    for slug in _slugs(language):
        body = _list(slug)
        if not body.get("series") or body["language"] != language:
            continue
        for concept in _concepts(slug):
            assert concept not in seen, (concept, seen.get(concept), slug)
            seen[concept] = slug
