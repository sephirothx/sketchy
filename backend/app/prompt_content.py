"""Language-aware normalization and bounded metadata for prompt content."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.domain_values import (
    AGNOSTIC_PROMPT_LANGUAGE,
    MIXED_PROMPT_LANGUAGE,
    PROMPT_LANGUAGES,
    PromptLanguage,
)
from app.prompts import MAX_PROMPT_LENGTH

# The width of `prompt_versions.match_key` and `prompt_aliases.match_key`.
MAX_MATCH_KEY_LENGTH = 64

MAX_PROMPT_ALIASES = 20
MAX_PROMPT_TAGS = 12
MAX_TAG_SLUG_LENGTH = 32

# How many tags one list may carry. Lower than MAX_PROMPT_TAGS on purpose: a
# prompt's tags describe one word and can afford to be exhaustive, while a
# list's are how somebody finds it in the community catalogue, and a list
# wearing twelve of them is answering every filter rather than the right one.
MAX_LIST_TAGS = 5

# The vocabulary a list owner chooses from (R-LIST-18). It is a fixed set
# rather than free text because a tag is player-authored copy displayed in a
# discovery surface, and the one thing a discovery feature must not do is
# introduce a second kind of content to moderate. Staff extend this tuple;
# nothing a request carries can add to it.
#
# Slugs are forever - `prompt_tags.slug` is unique and revisions reference the
# row - so a tag is renamed by changing its display name here, never its slug.
LIST_TAG_VOCABULARY: tuple[tuple[str, str], ...] = (
    ("animals", "Animals"),
    ("food-and-drink", "Food and drink"),
    ("objects", "Objects"),
    ("nature", "Nature"),
    ("places", "Places"),
    ("people", "People"),
    ("actions", "Actions"),
    ("sports-and-games", "Sports and games"),
    ("transport", "Transport"),
    ("entertainment", "Entertainment"),
    ("video-games", "Video games"),
    ("science-and-technology", "Science and technology"),
    ("history-and-culture", "History and culture"),
    ("holidays", "Holidays"),
    ("fantasy", "Fantasy"),
    ("abstract", "Abstract"),
)

LIST_TAG_SLUGS = frozenset(slug for slug, _ in LIST_TAG_VOCABULARY)
# The vocabulary's order, which is the order a list's tags are shown and stored in.
LIST_TAG_SLUG_ORDER = tuple(slug for slug, _ in LIST_TAG_VOCABULARY)

# How many of a room's lists may be players' own or published ones (#1374).
# What a selection costs to authorize grows with its answers and aliases, and
# a player's list is where the worst case lives - 500 prompts of 20 aliases
# each (R-LIST-04): twenty of them, agnostic in a mixed room, folded cold cost
# 1.5 s of CPU off the loop on PostgreSQL (`benchmarks/authorize_selection.py`,
# measured for #1374 on the #1237 benchmark). Official lists are reviewed content and alias
# sparingly, so the room-wide cap rose to forty (`MAX_PROMPT_LISTS`) to hold a
# whole series, while this one keeps the worst case where it was measured.
MAX_PLAYER_PROMPT_LISTS = 20

# The shelves the official lists stand on (#1374), in the order the room
# picker shows them. A shelf is navigation, not content: every official list
# names one, and a **series** within it (a franchise's generations, say) is
# optional.
# Only slugs live here - what a player reads is in the frontend catalogue, in
# every interface language - and a shelf is added here before a list names it,
# so a typo in a seed file fails startup instead of opening a shelf of one.
PROMPT_SHELVES: tuple[str, ...] = ("everyday", "video-games")


def validate_shelf_placement(
    shelf: str, series: str | None, position: int
) -> tuple[str, str | None, int]:
    """Check where an official list stands in the picker's tree, or refuse it."""
    if shelf not in PROMPT_SHELVES:
        raise ValueError(f"Unknown shelf: {shelf}")
    if series is not None and (
        len(series) > MAX_TAG_SLUG_LENGTH or not _TAG_SLUG.fullmatch(series)
    ):
        raise ValueError(f"A series must be a lowercase slug: {series}")
    if position < 0:
        raise ValueError("A shelf position must not be negative")
    return shelf, series, position


class UnknownListTag(ValueError):
    """A tag the curated vocabulary does not hold, kept so a refusal can name it.

    The slug travels as a value (`params.tag`), never inside a sentence: the
    client writes the sentence in the reader's language (R-I18N-01).
    """

    def __init__(self, tag: str) -> None:
        super().__init__(f"Unknown tag: {tag}")
        self.tag = tag


def clean_list_tags(tags: list[str]) -> tuple[str, ...]:
    """Validate list tags against the curated vocabulary, order preserved.

    Separate from `clean_prompt_tags`, which takes any well-formed slug
    because bundled prompt content is authored in the repository and reviewed
    as code. These arrive in a request.
    """
    if len(tags) > MAX_LIST_TAGS:
        raise ValueError(f"A list may carry at most {MAX_LIST_TAGS} tags.")
    cleaned: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        slug = tag.strip().lower()
        if slug not in LIST_TAG_SLUGS:
            # Named rather than dropped, for R-LIST-01's reason: a save that
            # silently discards part of what was sent is worse than one that
            # refuses.
            raise UnknownListTag(tag.strip() or tag)
        if slug not in seen:
            seen.add(slug)
            cleaned.append(slug)
    return tuple(cleaned)

_BCP47 = re.compile(
    r"^[A-Za-z]{2,3}(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?"
    r"(?:-[A-Za-z0-9]{5,8})*$"
)
_TAG_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_prompt_language(language: str) -> str:
    """Return the canonical supported BCP-47 tag or reject it.

    The syntax check keeps future values well shaped; the supported-language
    allowlist prevents content from claiming matching semantics the server has
    not implemented yet.
    """
    normalized = language.strip()
    if not _BCP47.fullmatch(normalized):
        raise ValueError("language must be a BCP-47 tag")
    canonical = normalized.lower()
    if canonical not in PROMPT_LANGUAGES:
        raise ValueError("prompt language is not supported")
    return canonical


_CANONICAL_LIST_LANGUAGES = frozenset((*PROMPT_LANGUAGES, AGNOSTIC_PROMPT_LANGUAGE))


def validate_prompt_list_language(language: str) -> str:
    """Return the canonical tag a prompt list may declare, or reject it.

    A list may be in one of the room languages or in none (`zxx`, #821). The
    difference from `validate_prompt_language` is deliberate and one-way: a
    room still has to declare a language its guesses can be folded under, so
    `zxx` is refused there.

    A tag already in its canonical form is answered by one set lookup: this
    runs once per text on every fold, 210,000 times for a selection at its
    ceiling (#1237), and the regular expression was a fifth of that fold.
    """
    if language in _CANONICAL_LIST_LANGUAGES:
        return language
    normalized = language.strip()
    if normalized.lower() == AGNOSTIC_PROMPT_LANGUAGE:
        return AGNOSTIC_PROMPT_LANGUAGE
    return validate_prompt_language(normalized)


def languages_sharing_words(language: str) -> tuple[str, ...]:
    """The content languages whose hidden words a list in `language` asks about.

    A moderator's decision on a word follows it into the owner's other lists
    (#1091), but only where the word is the same word: `pain` in an English
    list and in a French one are not. A list in no language (#821) is played
    in every room, so it shares its words with every language, and every
    language shares its words with it - otherwise a hidden word retyped into
    an Any-language list would be born active, in the one list every room
    can play. Which fold the two are then compared in is the caller's
    question: the one room language where both are played.
    """
    if language == AGNOSTIC_PROMPT_LANGUAGE:
        return (*PROMPT_LANGUAGES, AGNOSTIC_PROMPT_LANGUAGE)
    return (language, AGNOSTIC_PROMPT_LANGUAGE)


def validate_room_language(language: str) -> str:
    """Return the canonical tag a room may declare, or reject it.

    One of the room languages, or several (`mul`, #1182): a room whose seats
    each play in the language they joined with. Never `zxx`, which names no
    language to fold a guess under.
    """
    normalized = language.strip()
    if normalized.lower() == MIXED_PROMPT_LANGUAGE:
        return MIXED_PROMPT_LANGUAGE
    return validate_prompt_language(normalized)


def best_supported_prompt_locale(accept_language: str | None) -> str:
    """Choose the first supported base locale from an Accept-Language value."""
    for preference in (accept_language or "").split(","):
        tag = preference.split(";", 1)[0].strip().lower()
        if not tag:
            continue
        if tag in PROMPT_LANGUAGES:
            return tag
        base = tag.split("-", 1)[0]
        if base in PROMPT_LANGUAGES:
            return base
    return "en"


def default_prompt_list_slug(language: str) -> str:
    """The official Standard list a room in `language` starts from.

    Bundled slugs are named for the language written out - `english_standard`,
    `german_standard` - which is exactly what the enum member is called, so the
    convention lives in one place instead of a second table that can disagree
    with it. A language whose content has not shipped yet resolves to a slug
    that is simply not found, which is a visible refusal rather than a room
    quietly opening on English prompts.
    """
    if language == MIXED_PROMPT_LANGUAGE:
        # Any language's Standard names the whole family, which a mixed room
        # pins in every language (#1182); English's is as good as any.
        language = PromptLanguage.ENGLISH.value
    return f"{PromptLanguage(validate_prompt_language(language)).name.lower()}_standard"


# Every mark a keyboard writes for the apostrophe in "feu d'artifice" (#1011):
# the typographic right quote iOS Smart Punctuation substitutes on its own
# (and Word, and most phones), the modifier letter, the left quote a
# smart-quote engine picks at the start of a word, the reversed one, the
# prime, the spacing acute accent, the backtick some layouts put on the key,
# and the fullwidth form a CJK input method emits. NFC leaves all of them
# alone - none is canonically equivalent to U+0027, and only NFKC would fold
# the fullwidth one - so without this fold the bundled French and Italian
# answers written with an apostrophe were unguessable from an iPhone, and
# the player was told "very close" for the rest of the turn.
_APOSTROPHES = str.maketrans(
    {mark: "'" for mark in "\u2019\u02bc\u2018\u201b\u2032\u00b4\u0060\uff07"}
)


# Code points that draw nothing (#1245): every format character (Unicode
# category Cf - the zero-width space and joiners, the word joiner, the soft
# hyphen, the byte-order mark, the bidirectional overrides) and the rest of
# Unicode's Default_Ignorable_Code_Point set - variation selectors, fillers,
# tags. Two texts that differ only by them look the same and keyed
# differently, so a moderator's takedown of "badword" came back as
# "bad<ZWSP>word", a list could hold "cat" three times over, and a U+202E in
# a name turned the rest of the line around.
#
# Written out rather than derived from `unicodedata` at import, which would
# walk all 1.1 million code points in every process; one class, because
# testing a character against a list of ranges in Python made keying a
# non-ASCII answer six times slower. `unicodedata` has no default-ignorable
# property to derive it from anyway: `test_invisible_prompt_text` checks the
# class against Unicode's list of them, reserved code points included
# (U+FFF0-FFF8 were missing, #1303 review), and every Cf character the
# running Python knows.
_INVISIBLE = (
    "\u00ad\u034f\u0600-\u0605\u061c\u06dd\u070f\u0890\u0891\u08e2"
    "\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e"
    "\u2060-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufffb"
    "\U000110bd\U000110cd\U00013430-\U0001343f\U0001bca0-\U0001bca3"
    "\U0001d173-\U0001d17a\U000e0000-\U000e0fff"
)
INVISIBLE_CHARACTER = re.compile(f"[{_INVISIBLE}]")
# The joiner that builds one emoji out of several ("cook" is person, ZWJ,
# frying pan) is left out of this one: a name or description may carry it,
# since emoji are how plenty of people title a list; an answer may not, being
# a word to guess.
_INVISIBLE_BUT_THE_JOINER = re.compile(f"(?!\u200d)[{_INVISIBLE}]")

# The most marks one letter may carry, counted decomposed so a precomposed
# letter counts its own: Vietnamese stacks two ("ệ"), and nothing a language
# writes needs more than four. A pile of them is text that paints over the
# lines around it.
MAX_COMBINING_MARKS = 4

_LONG_NON_ASCII_RUN = re.compile(f"[^\\x00-\\x7f]{{{MAX_COMBINING_MARKS + 1},}}")

INVISIBLE_CHARACTER_MESSAGE = "must not contain invisible or formatting characters"
STACKED_MARKS_MESSAGE = f"must not stack more than {MAX_COMBINING_MARKS} marks on one letter"


def visible_text_problem(text: str, *, emoji_joiner: bool = False) -> str | None:
    """Why `text` may not be stored as prompt-list content, or None.

    `emoji_joiner` admits the zero-width joiner, for a name or description.
    ASCII has neither problem, and most of a list is ASCII.
    """
    if text.isascii():
        return None
    pattern = _INVISIBLE_BUT_THE_JOINER if emoji_joiner else INVISIBLE_CHARACTER
    if pattern.search(text) is not None:
        return INVISIBLE_CHARACTER_MESSAGE
    decomposed = unicodedata.normalize("NFD", text)
    # A mark is never ASCII, so a stack too high is at least that many
    # non-ASCII characters in a row - which a decomposed Latin word never has
    # ("Mu" + diaeresis + "ller"), and so is not walked character by character.
    if _LONG_NON_ASCII_RUN.search(decomposed) is None:
        return None
    run = 0
    for character in decomposed:
        run = run + 1 if unicodedata.category(character)[0] == "M" else 0
        if run > MAX_COMBINING_MARKS:
            return STACKED_MARKS_MESSAGE
    return None


def _without_invisible(text: str) -> str:
    return text if text.isascii() else INVISIBLE_CHARACTER.sub("", text)


def _collapsed(answer: str) -> str:
    """Whitespace collapsed, case folded, *composed*, apostrophes made plain.

    NFC before anything language-specific, because a transliteration table is
    written in letters: "ä" as one codepoint is in it, and "a" followed by a
    combining diaeresis is not. Text arrives both ways - a macOS filename or
    an IME can hand over the decomposed form - and the two are canonically
    equivalent, so they have to fold to one key. The apostrophe fold runs on
    both the stored key and the guess, so a list written with typographic
    quotes matches a plain-keyboard guess as well as the other way round.

    Invisible characters are dropped first (#1245): stored content refuses
    them, but a key is also what a guess and a moderator's hidden word are
    compared by, and "bad<ZWSP>word" is the same word as "badword".
    """
    composed = unicodedata.normalize(
        "NFC", " ".join(_without_invisible(answer).split()).casefold()
    )
    return composed.translate(_APOSTROPHES)


def _fold_accents(text: str) -> str:
    """Drop canonically decomposable diacritics: "è" reads as "e".

    Letters such as "ø" and "ł" survive, because NFD does not decompose them
    into an ASCII letter and a mark.

    ASCII has nothing to decompose and no marks, so it is returned as it is:
    the per-character walk below is what folding a whole prompt list costs,
    and most of a list is ASCII (#1236, #1237).
    """
    if text.isascii():
        return text
    return "".join(
        character
        for character in unicodedata.normalize("NFD", text)
        if not unicodedata.combining(character)
    )


# What a language writes when the keyboard - or the writer - has no diacritic.
# These are spellings of the same word, not near misses: a German who types
# "Maedchen" has written "Mädchen". Folding the accent away instead
# (R-GUESS-01's shared rule) gives "madchen", which nobody writes.
#
# ß is absent deliberately: case-folding already turns it into "ss", so
# "Fußball" and "Fussball" have met before any of this runs.
_TRANSLITERATIONS: dict[str, dict[str, str]] = {
    "de": {"ä": "ae", "ö": "oe", "ü": "ue"},
    # French ligatures. NFD leaves both alone - they are letters, not letters
    # with a mark - so "coeur" would otherwise never reach "cœur", which is
    # how almost everyone types it.
    "fr": {"œ": "oe", "æ": "ae"},
    # The Dutch digraph has a single-codepoint form that NFD leaves alone;
    # everyone types the two letters.
    "nl": {"ĳ": "ij"},
    # The one Polish letter NFD leaves whole: "ł" is not "l" with a mark, so
    # the shared rule keeps it, and "lodz" - how "łódź" is typed on a
    # keyboard without Polish letters - would never meet the answer. Every
    # other Polish diacritic (ą ć ę ń ó ś ź ż) decomposes and folds already.
    "pl": {"ł": "l"},
}


def _transliterate(text: str, language: str) -> str:
    table = _TRANSLITERATIONS.get(language)
    if not table:
        return text
    return "".join(table.get(character, character) for character in text)


# "&" is read as the language's own "and" (#1396): "Nunu & Willump" and "Nunu
# and Willump" are one name, as German "&" and "und" are. A list in no language
# keeps the sign, since its key must not depend on the room.
_AMPERSAND_WORDS = {
    "en": "and", "de": "und", "es": "y", "fr": "et",
    "it": "e", "nl": "en", "pl": "i", "pt": "e",
}


def _spelled_out(text: str, language: str) -> str:
    word = _AMPERSAND_WORDS.get(language)
    if not word or "&" not in text:
        return text
    return " ".join(text.replace("&", f" {word} ").split())


# Spaces, hyphens, dots and apostrophes: what a word is written with or
# without and still the same word - "hang glider", "hang-glider", "hangglider";
# "Dr. Robotnik" and "Dr Robotnik"; "Farfetch'd" and "Farfetchd". Matching
# drops them rather than official lists listing every way (#1396). Apostrophes
# arrive here as the plain one (`_APOSTROPHES`), and the dashes a keyboard or
# an autocorrect writes for a hyphen go with it.
_SEPARATORS = re.compile(r"[\s\-\u2010-\u2015\u2212.']+")


_WORD_MARKS = re.compile(r"[.']+")


def _without_separators(text: str) -> str:
    return _SEPARATORS.sub("", text)


def prompt_match_key(answer: str, language: str = "en") -> str:
    """Build the canonical comparison key for a supported Latin-script language.

    Every supported language case-folds, folds canonically decomposable
    accents and drops the separators a word is written with or without
    (`_without_separators`); a language may then add its own transliteration,
    applied *before* the accents are folded so that "ä" becomes "ae" rather
    than "a".

    This is one string, because it is also an identity: it backs the unique
    constraints on prompt versions and aliases. Matching a guess asks the wider
    question - see `prompt_match_variants`.

    A language-agnostic list (`zxx`) keys with the shared rule alone: no
    transliteration, because the key must not depend on which room plays it.
    The room's own transliteration still reaches it at guess time, since
    acceptance folds the answer's *text* under the room's language.
    """
    language = validate_prompt_list_language(language)
    collapsed = _spelled_out(_collapsed(answer), language)
    return _without_separators(_fold_accents(_transliterate(collapsed, language)))


def prompt_match_words(answer: str, language: str = "en") -> str:
    """`prompt_match_key` with its words kept apart: each run of separators
    is one space instead of none. What a near miss is measured on, since
    "partly right" counts the words a guess got (`game._near_miss`)."""
    language = validate_prompt_list_language(language)
    folded = _fold_accents(_transliterate(_spelled_out(_collapsed(answer), language), language))
    # A dot or an apostrophe sits inside a word ("keeper's", "U.S.");
    # a hyphen or a space is between two.
    return " ".join(_SEPARATORS.sub(" ", _WORD_MARKS.sub("", folded)).split())


def prompt_match_variants(answer: str, language: str = "en") -> frozenset[str]:
    """Every spelling of `answer` this language accepts as the same word.

    A language with transliterations has two of them - "Mädchen" is written
    "maedchen" and, by a writer who dropped the umlaut rather than expanding
    it, "madchen" - and one stored key cannot be both. A guess is accepted when
    its own variants meet the answer's, so both spellings land without either
    becoming the identity.
    """
    language = validate_prompt_list_language(language)
    collapsed = _spelled_out(_collapsed(answer), language)
    return frozenset(
        {
            _without_separators(_fold_accents(_transliterate(collapsed, language))),
            _without_separators(_fold_accents(collapsed)),
        }
    )


def prompt_match_variants_by_language(
    answer: str, languages: Iterable[str]
) -> dict[str, frozenset[str]]:
    """`prompt_match_variants` under each of `languages`, folded once per
    transliteration rather than once per language: the languages without one
    all spell a text alike, so a list in no language checked under all eight
    costs five folds, not eight (#1236) - unless the text has an "&", which
    each language reads as its own "and"."""
    shared: frozenset[str] | None = None
    variants: dict[str, frozenset[str]] = {}
    # "&" is each language's own word (`_spelled_out`), so a text holding one
    # folds differently even where no transliteration does (review of #1406).
    alone = "&" in answer
    for language in languages:
        if alone or _TRANSLITERATIONS.get(validate_prompt_list_language(language)):
            variants[language] = prompt_match_variants(answer, language)
        else:
            if shared is None:
                shared = prompt_match_variants(answer, language)
            variants[language] = shared
    return variants


# The transliterations whose plain spelling loses the letter: German "ü" is
# "ue" one way and "u" the other, where French "œ" is "oe" or itself. Only these
# let one guess reach two spellings no answer shares - see `AnswerOwners`.
_LOSSY_DIGRAPHS: dict[str, dict[str, str]] = {
    language: lossy
    for language, table in _TRANSLITERATIONS.items()
    if (
        lossy := {
            expanded: _fold_accents(letter)
            for letter, expanded in table.items()
            if _fold_accents(letter) != letter
        }
    )
}


def _collapse_digraphs(spelling: str, digraphs: dict[str, str]) -> str:
    """Every digraph collapsed, until none is left: "auee" to "au".

    Repeated because a collapse can make a new one ("uee" is "ue" once), and
    the group two spellings meet in has to be the same however many of their
    digraphs each collapsed. German's are all a vowel and an "e", so the end
    is the same whichever order they go in.
    """
    pattern = "|".join(map(re.escape, digraphs))
    while True:
        collapsed = re.sub(pattern, lambda found: digraphs[found[0]], spelling)
        if collapsed == spelling:
            return collapsed
        spelling = collapsed


def _drops_digraphs(longer: str, shorter: str, digraphs: dict[str, str]) -> bool:
    """Whether `shorter` is `longer` with one or more of its digraphs written as
    the letter the diacritic leaves when it is dropped: "spule" from "spuele".

    One guess then reaches both - "Spüle" is "spuele" transliterated and
    "spule" folded - so two answers spelled this way answer to the same word.
    Each collapse shortens the spelling by one, so a walk that ends level has
    made at least one when the lengths differ.
    """
    if len(longer) <= len(shorter):
        return False
    states = {(0, 0)}
    while states:
        advanced: set[tuple[int, int]] = set()
        for position, matched in states:
            if position == len(longer) or matched == len(shorter):
                if (position, matched) == (len(longer), len(shorter)):
                    return True
                continue
            pair = longer[position : position + 2]
            if digraphs.get(pair) == shorter[matched]:
                advanced.add((position + 2, matched + 1))
            if longer[position] == shorter[matched]:
                advanced.add((position + 1, matched + 1))
        states = advanced
    return False


class AnswerOwners:
    """Who answers to what, in one language: the check that no guess can win
    two prompts of a selection (R-PROMPT-01, R-GUESS-01).

    Comparing the stored keys is not enough. A guess wins when *any* of its
    spellings meets any of an answer's (`prompt_match_variants`), so German
    "Spüle" (sink) and "Spule" (spool) - two keys - are both won by "Spule",
    and by "Spüle". Where the plain spelling drops the letter a transliteration
    expands, two answers that share no spelling at all can still be won by one
    guess: "Spuele" and "Spule" by "Spüle". Those are found by grouping each
    spelling under all of its digraphs collapsed, and walking the few that
    share a group.

    An owner is whatever the caller tells concepts apart by - a concept id, a
    prompt version. A group holding more than `MAX_LOOKALIKES` spellings of
    other owners is refused outright: nothing a person writes needs that many
    words one dropped diacritic apart, and it bounds the walk on a list built
    to need it.
    """

    MAX_LOOKALIKES = 16

    def __init__(self, language: str) -> None:
        self.language = language
        self._owner: dict[str, object] = {}
        self._digraphs = _LOSSY_DIGRAPHS.get(language, {})
        self._groups: dict[str, list[str]] = {}

    def claim(
        self, owner: object, text: str, spellings: frozenset[str] | None = None
    ) -> bool:
        """Record `text` as one of `owner`'s answers; False when a guess could
        win both it and another owner's. `spellings`, when the caller already
        folded them, are `prompt_match_variants(text, self.language)`."""
        if spellings is None:
            spellings = prompt_match_variants(text, self.language)
        for spelling in spellings:
            if self._owner.setdefault(spelling, owner) != owner:
                return False
        if not self._digraphs:
            return True
        for spelling in spellings:
            group = self._groups.setdefault(
                _collapse_digraphs(spelling, self._digraphs), []
            )
            others = [other for other in group if self._owner[other] != owner]
            if len(others) > self.MAX_LOOKALIKES:
                return False
            for other in others:
                if _drops_digraphs(spelling, other, self._digraphs) or _drops_digraphs(
                    other, spelling, self._digraphs
                ):
                    return False
            if spelling not in group:
                group.append(spelling)
        return True


def normalize_prompt_answer(answer: str, language: str = "en") -> str:
    """Build the validated immutable match key for stored prompt content."""
    collapsed = " ".join(answer.split())
    if not collapsed or len(collapsed) > MAX_PROMPT_LENGTH:
        raise ValueError(f"answer must be 1-{MAX_PROMPT_LENGTH} characters")
    problem = visible_text_problem(collapsed)
    if problem is not None:
        raise ValueError(f"answer {problem}")
    key = prompt_match_key(collapsed, language)
    if not key:
        # Nothing but separators: "-" or "..." would key as the empty string,
        # which every other such answer shares.
        raise ValueError("answer must contain a letter or a digit")
    # Bounded after folding, not only before: case-folding expands some
    # characters (`ﬃ` to "ffi", `ß` to "ss"), so 32 characters in could be 96
    # out, and the key column is 64 wide. PostgreSQL refused the write -
    # a 500 where the input was the thing wrong; SQLite never checks
    # (#1017). Refused here like any other answer that is too long.
    if len(key) > MAX_MATCH_KEY_LENGTH:
        raise ValueError(
            f"answer must be at most {MAX_MATCH_KEY_LENGTH} characters once normalized"
        )
    return key


def clean_prompt_aliases(
    aliases: list[str], *, canonical_answer: str, language: str
) -> tuple[str, ...]:
    """Validate and deduplicate aliases by their language-specific match key."""
    cleaned, _ = clean_prompt_aliases_keyed(
        aliases,
        canonical_key=normalize_prompt_answer(canonical_answer, language),
        language=language,
    )
    return cleaned


def clean_prompt_aliases_keyed(
    aliases: list[str], *, canonical_key: str, language: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """`clean_prompt_aliases`, for a caller that already holds the answer's key,
    returning each kept alias's key beside it so nothing is folded twice."""
    cleaned: list[str] = []
    keys: list[str] = []
    seen = {canonical_key}
    if len(aliases) > MAX_PROMPT_ALIASES:
        raise ValueError(f"too many aliases (max {MAX_PROMPT_ALIASES})")
    for alias in aliases:
        display = " ".join(alias.split())
        key = normalize_prompt_answer(display, language)
        if key not in seen:
            seen.add(key)
            cleaned.append(display)
            keys.append(key)
    return tuple(cleaned), tuple(keys)


def clean_prompt_tags(tags: list[str]) -> tuple[str, ...]:
    """Return bounded canonical tag slugs, preserving first-seen order."""
    if len(tags) > MAX_PROMPT_TAGS:
        raise ValueError(f"too many tags (max {MAX_PROMPT_TAGS})")
    cleaned: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        slug = tag.strip().lower()
        if len(slug) > MAX_TAG_SLUG_LENGTH or not _TAG_SLUG.fullmatch(slug):
            raise ValueError("tags must be lowercase hyphenated slugs")
        if slug not in seen:
            seen.add(slug)
            cleaned.append(slug)
    return tuple(cleaned)
