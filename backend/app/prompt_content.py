"""Language-aware normalization and bounded metadata for prompt content."""
from __future__ import annotations

import re
import unicodedata

from app.domain_values import PROMPT_LANGUAGES, PromptLanguage
from app.prompts import MAX_PROMPT_LENGTH

MAX_PROMPT_ALIASES = 20
MAX_PROMPT_TAGS = 12
MAX_TAG_SLUG_LENGTH = 32
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
    return f"{PromptLanguage(validate_prompt_language(language)).name.lower()}_standard"


def _fold_accents(text: str) -> str:
    """Drop canonically decomposable diacritics: "è" reads as "e".

    Letters such as "ø" and "ł" survive, because NFD does not decompose them
    into an ASCII letter and a mark.
    """
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
}


def _transliterate(text: str, language: str) -> str:
    table = _TRANSLITERATIONS.get(language)
    if not table:
        return text
    return "".join(table.get(character, character) for character in text)


def prompt_match_key(answer: str, language: str = "en") -> str:
    """Build the canonical comparison key for a supported Latin-script language.

    Every supported language case-folds, collapses whitespace and folds
    canonically decomposable accents; a language may then add its own
    transliteration, applied *before* the accents are folded so that "ä"
    becomes "ae" rather than "a".

    This is one string, because it is also an identity: it backs the unique
    constraints on prompt versions and aliases. Matching a guess asks the wider
    question - see `prompt_match_variants`.
    """
    language = validate_prompt_language(language)
    collapsed = " ".join(answer.split()).casefold()
    return _fold_accents(_transliterate(collapsed, language))


def prompt_match_variants(answer: str, language: str = "en") -> frozenset[str]:
    """Every spelling of `answer` this language accepts as the same word.

    A language with transliterations has two of them - "Mädchen" is written
    "maedchen" and, by a writer who dropped the umlaut rather than expanding
    it, "madchen" - and one stored key cannot be both. A guess is accepted when
    its own variants meet the answer's, so both spellings land without either
    becoming the identity.
    """
    language = validate_prompt_language(language)
    collapsed = " ".join(answer.split()).casefold()
    return frozenset(
        {
            _fold_accents(_transliterate(collapsed, language)),
            _fold_accents(collapsed),
        }
    )


def normalize_prompt_answer(answer: str, language: str = "en") -> str:
    """Build the validated immutable match key for stored prompt content."""
    collapsed = " ".join(answer.split())
    if not collapsed or len(collapsed) > MAX_PROMPT_LENGTH:
        raise ValueError(f"answer must be 1-{MAX_PROMPT_LENGTH} characters")
    return prompt_match_key(collapsed, language)


def clean_prompt_aliases(
    aliases: list[str], *, canonical_answer: str, language: str
) -> tuple[str, ...]:
    """Validate and deduplicate aliases by their language-specific match key."""
    canonical_key = normalize_prompt_answer(canonical_answer, language)
    cleaned: list[str] = []
    seen = {canonical_key}
    if len(aliases) > MAX_PROMPT_ALIASES:
        raise ValueError(f"too many aliases (max {MAX_PROMPT_ALIASES})")
    for alias in aliases:
        display = " ".join(alias.split())
        key = normalize_prompt_answer(display, language)
        if key not in seen:
            seen.add(key)
            cleaned.append(display)
    return tuple(cleaned)


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
