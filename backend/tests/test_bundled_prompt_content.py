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
from app.db.name_lists import is_name_list
from app.db.seed import DEFAULT_PROMPT_LISTS_DIR, bundled_list_bodies
from app.domain_values import AGNOSTIC_PROMPT_LANGUAGE, PROMPT_LANGUAGES, PromptLanguage
from app.prompt_content import MAX_PROMPT_LENGTH, PROMPT_SHELVES, AnswerOwners, prompt_match_key

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
def _bodies() -> dict[str, dict]:
    """Every official list, read the way startup seeds them: a name list
    expanded into a list per language (#1399), so these tests judge what is
    played rather than how it is written."""
    return {body["slug"]: body for _, body in bundled_list_bodies()}


def _list(slug: str) -> dict:
    return _bodies()[slug]


def _slugs(language: str) -> list[str]:
    """Every bundled list a room in `language` can combine: its own, and the
    ones in no language (`zxx`, R-PROMPT-12), which every room may pick."""
    return sorted(
        slug
        for slug in _bodies()
        if _list(slug)["language"] in (language, AGNOSTIC_PROMPT_LANGUAGE)
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
    for slug in _bodies():
        if slug != f"{_stem(language)}_local":
            elsewhere |= _concepts(slug)
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
    """No guess may win two concepts across a language's lists, answers and
    aliases alike: a room that selects both would be refused as ambiguous
    (R-PROMPT-01), and the seed never looks at aliases across concepts. A
    concept deliberately repeated in two lists is one concept. A list in no
    language is keyed as a room in this one keys it - so "Müller" beside a
    German "Mueller" clashes here and nowhere else.

    Every spelling a guess is accepted under counts, not only the stored key:
    German "Spüle" (sink) keys as "spuele", but is also won by "Spule", which
    was the spool's alias (#1396)."""
    owners = AnswerOwners(language)
    clashes = [
        f"{slug}:{text}"
        for slug in _slugs(language)
        for entry in _list(slug)["prompts"]
        for text in (entry["answer"], *entry.get("aliases", ()))
        if not owners.claim(entry["conceptId"], text)
    ]
    assert clashes == []


def test_the_stats_page_reads_every_bundled_list_whole():
    """The stats page asks for a list in one page of at most `MAX_PAGE_SIZE`;
    a bundled list longer than that would be cut short without a word."""
    for slug in _bodies():
        assert len(_list(slug)["prompts"]) <= MAX_PAGE_SIZE, slug


def test_every_official_list_has_its_own_place_on_a_known_shelf():
    """The picker's tree (#1374) orders a shelf, or a series on it, by each
    list's position: two lists of one language in the same place would sort
    by whatever order the server happened to return."""
    places: dict[tuple, list[str]] = defaultdict(list)
    for slug in _bodies():
        body = _list(slug)
        assert body["shelf"] in PROMPT_SHELVES, slug
        places[
            (body["language"], body["shelf"], body.get("series"), body.get("position", 0))
        ].append(slug)
    assert {place: slugs for place, slugs in places.items() if len(slugs) > 1} == {}


def test_every_themed_official_list_is_a_family_or_in_no_language():
    """A themed official list ships translated into every language - the same
    concepts, so a mixed room can pin it whole - or as one list in no language
    (R-PROMPT-01, R-PROMPT-12, #1374). One that reached only some languages
    would be offered in some rooms and refused as a family in mixed ones."""
    by_language: dict[str, dict[frozenset, str]] = defaultdict(dict)
    themed = []
    for slug in _bodies():
        body = _list(slug)
        if body["language"] == AGNOSTIC_PROMPT_LANGUAGE or slug.endswith("_local"):
            continue
        concepts = frozenset(_concepts(slug))
        by_language[body["language"]][concepts] = slug
        if body["shelf"] != "everyday":
            themed.append((slug, concepts))
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


def test_a_name_list_declares_every_supported_language():
    """A name list is written once and expanded into every supported language
    (#1399), so a language added to the registry gets it without a copy - and
    without anybody having looked. Each file therefore says, for every
    supported language, whether that language takes the default spellings or
    overrides some: adding a language fails here until somebody has decided,
    which is a line in each file rather than a silent inheritance."""
    import json

    for path in sorted(DEFAULT_PROMPT_LISTS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not is_name_list(data):
            continue
        declared = data["languages"].get("inherit", []) + data["languages"].get("override", [])
        assert sorted(declared) == sorted(PROMPT_LANGUAGES), path.name


def test_the_german_sink_and_spool_answer_to_their_own_words():
    """"Spule" was the spool's alias and the sink's dropped umlaut, so either
    word scored for the spool (#1396). Umlaut tolerance stays; the alias went,
    and later every alias of the everyday lists with it."""
    from app.game import _accepted_spellings

    def accepts(answer: str) -> frozenset[str]:
        entry = next(
            entry
            for slug in _slugs("de")
            for entry in _list(slug)["prompts"]
            if entry["answer"] == answer
        )
        return frozenset().union(
            *(_accepted_spellings(text, "de") for text in (entry["answer"], *entry.get("aliases", ())))
        )

    sink, spool = accepts("Spüle"), accepts("Garnrolle")
    for guess in ("Spule", "Spüle", "Spuele"):
        assert not _accepted_spellings(guess, "de").isdisjoint(sink), guess
        assert _accepted_spellings(guess, "de").isdisjoint(spool), guess
    assert not _accepted_spellings("Garnrolle", "de").isdisjoint(spool)


#: The articles a word can start with, per language - definite and
#: indefinite, and the inflected German forms - for R-PROMPT-10. Polish has
#: none.
LEADING_ARTICLES = {
    "en": ("the", "a", "an"),
    "de": ("der", "die", "das", "dem", "den", "des", "ein", "eine"),
    "es": ("el", "la", "los", "las", "un", "una"),
    "fr": ("le", "la", "les", "l'", "un", "une", "des"),
    "it": ("il", "lo", "la", "i", "gli", "le", "l'", "un", "uno", "una", "un'"),
    "nl": ("de", "het", "een", "'t"),
    "pt": ("o", "a", "os", "as", "um", "uma"),
    "pl": (),
}

#: Spellings that start like an article and are not one: Portuguese "a
#: carregar" is the preposition, "loading".
NOT_ARTICLES = frozenset({("pt", "a carregar")})

#: Titles of works that keep their official article in some language
#: (R-PROMPT-10): "Der gestiefelte Kater", "Il brutto anatroccolo". Chosen
#: title by title and language by language in #1396.
WORK_TITLES = frozenset({
    "01a0f49a-74d4-7018-8699-68704bb168db",  # Beauty and the Beast
    "01a0f49a-74d4-7018-8699-6860c4ba03e5",  # Creation of Adam
    "01a0f467-2041-71b2-9e85-06d794fff3d2",  # fox and the grapes
    "01a02b7b-b554-7663-856a-0de9677be967",  # frog prince
    "01a0f467-2041-71b2-9e85-0740aae26c7f",  # lion and the mouse
    "01a0f467-2041-71b2-9e85-07427318d531",  # Little Red Riding Hood
    "01a0f467-2041-71b2-9e85-0767676d00b6",  # Mona Lisa
    "01a0f49a-74d4-7018-8699-685876665dfd",  # Pied Piper
    "01a0f467-2042-7235-b88e-1a85954e5d15",  # princess and the pea
    "01a0f467-2042-7235-b88e-1a92058ea37a",  # Puss in Boots
    "01a0f49a-74d4-7018-8699-68614ffb1099",  # Rodin's Thinker
    "01a0f49a-74d4-7018-8699-6859d9347ac3",  # Sleeping Beauty
    "01a0f467-2042-7235-b88e-1b21b42a9797",  # three little pigs
    "01a0f467-2042-7235-b88e-1b33cb326b89",  # tortoise and the hare
    "01a0f467-2042-7235-b88e-1b47cbc30b95",  # ugly duckling
})


def _article(text: str, language: str) -> str | None:
    lowered = text.casefold()
    for article in LEADING_ARTICLES[language]:
        if lowered.startswith(article if article.endswith("'") else article + " "):
            return article
    return None


@pytest.mark.parametrize("language", PROMPT_LANGUAGES)
def test_articles_are_not_aliases(language):
    """An article form is no alias (R-PROMPT-10): matching does not drop the
    article (N-20), and the lists keep to the fewest spellings that are fair
    (#1396), so "der Hund" does not score for "Hund"."""
    found = [
        f"{slug}:{alias}"
        for slug in _slugs(language)
        for entry in _list(slug)["prompts"]
        for alias in entry.get("aliases", ())
        if _article(alias, language) and (language, alias) not in NOT_ARTICLES
    ]
    assert found == []


@pytest.mark.parametrize("language", PROMPT_LANGUAGES)
def test_only_a_work_s_title_starts_with_an_article(language):
    found = [
        f"{slug}:{entry['answer']}"
        for slug in _slugs(language)
        for entry in _list(slug)["prompts"]
        if _article(entry["answer"], language) and entry["conceptId"] not in WORK_TITLES
    ]
    assert found == []


#: The aliases an everyday list keeps (#1396): a brand that is the everyday
#: word for the thing, chosen one by one. Everything else - synonyms, regional
#: names, spellings, plurals - was dropped, so each concept has one answer and
#: matching folds what is only punctuation (R-GUESS-01).
EVERYDAY_ALIASES = frozenset({
    ("en", "band-aid"),
    ("en", "scotch tape"),
    ("en", "memory stick"),
    ("fr", "scotch"),
    ("fr", "photomaton"),
    ("it", "scotch"),
    ("it", "cotton fioc"),
    ("it", "phon"),
})


@pytest.mark.parametrize("language", PROMPT_LANGUAGES)
def test_an_everyday_list_names_each_concept_once(language):
    """R-PROMPT-10: Standard, Extended and Local accept the answer itself."""
    found = [
        f"{slug}:{alias}"
        for slug in _slugs(language)
        if slug.endswith(("_standard", "_extended", "_local"))
        for entry in _list(slug)["prompts"]
        for alias in entry.get("aliases", ())
        if (language, alias) not in EVERYDAY_ALIASES
    ]
    assert found == []


def test_a_franchise_name_list_accepts_only_the_english_name_beside_its_own():
    """Pokémon and League of Legends: a language that renames a character also
    accepts the English name, and nothing else (#1396)."""
    for path in DEFAULT_PROMPT_LISTS_DIR.glob("*.json"):
        if not path.stem.startswith(("pokemon_gen", "league_of_legends")):
            continue
        for entry in json.loads(path.read_text(encoding="utf-8"))["prompts"]:
            assert "aliases" not in entry, (path.stem, entry["answer"])
            for language, own in entry.get("overrides", {}).items():
                assert own.get("aliases", [entry["answer"]]) == [entry["answer"]], (path.stem, language, own)


@pytest.mark.parametrize("language", PROMPT_LANGUAGES)
def test_a_title_that_keeps_its_article_is_not_accepted_without_it(language):
    """R-PROMPT-10: "Der Löwe und die Maus" is accepted only as written, so
    "Löwe und die Maus" is no alias of it (#1396)."""
    found = []
    for slug in _slugs(language):
        for entry in _list(slug)["prompts"]:
            article = _article(entry["answer"], language)
            if entry["conceptId"] not in WORK_TITLES or not article:
                continue
            bare = entry["answer"][len(article):].lstrip()
            found += [
                f"{slug}:{alias}"
                for alias in entry.get("aliases", ())
                if prompt_match_key(alias, language) == prompt_match_key(bare, language)
            ]
    assert found == []
