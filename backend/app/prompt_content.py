"""Language-aware normalization and bounded metadata for prompt content."""
from __future__ import annotations

import re
import unicodedata

from app.domain_values import PROMPT_LANGUAGES
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


def prompt_match_key(answer: str, language: str = "en") -> str:
    """Build a comparison key for a supported Latin-script language.

    The initial registry deliberately contains only languages whose answers can
    use the same case-folding, whitespace, and canonical-accent rules. A future
    language with materially different tokenization must add its own strategy
    before it can be stored.
    """
    language = validate_prompt_language(language)
    collapsed = " ".join(answer.split()).casefold()
    if language in PROMPT_LANGUAGES:
        decomposed = unicodedata.normalize("NFD", collapsed)
        return "".join(
            character
            for character in decomposed
            if not unicodedata.combining(character)
        )
    raise AssertionError(f"missing matching strategy for supported language {language}")


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
