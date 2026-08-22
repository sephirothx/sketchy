import asyncio
import json
import logging
from pathlib import Path
from uuid import UUID

from app.domain_values import (
    PROMPT_CONTENT_RATINGS,
    PROMPT_EDITORIAL_DIFFICULTIES,
    PromptLanguage,
)
from app.prompt_content import (
    clean_prompt_aliases,
    clean_prompt_tags,
    normalize_prompt_answer,
    validate_prompt_language,
)
from app.repositories.interfaces import (
    BundledPromptDefinition,
    PromptListRepository,
    PromptListSummary,
)

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_LISTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "prompt_lists"


def _bundled_prompt(raw: object, *, language: str) -> BundledPromptDefinition:
    if not isinstance(raw, dict):
        raise ValueError("bundled prompts must be objects with stable conceptId values")
    concept_id = UUID(str(raw.get("conceptId", "")))
    if concept_id.version != 7:
        raise ValueError("bundled prompt conceptId must be a UUIDv7")
    answer = " ".join(str(raw.get("answer", "")).split())
    normalize_prompt_answer(answer, language)
    prompt_version = int(raw.get("promptVersion", 1))
    if prompt_version < 1:
        raise ValueError("promptVersion must be positive")
    aliases = clean_prompt_aliases(
        [str(alias) for alias in raw.get("aliases", [])],
        canonical_answer=answer,
        language=language,
    )
    difficulty = str(raw.get("difficulty", "unspecified"))
    if difficulty not in PROMPT_EDITORIAL_DIFFICULTIES:
        raise ValueError("unsupported prompt difficulty")
    content_rating = str(raw.get("contentRating", "everyone"))
    if content_rating not in PROMPT_CONTENT_RATINGS:
        raise ValueError("unsupported prompt content rating")
    tags = clean_prompt_tags([str(tag) for tag in raw.get("tags", [])])
    return BundledPromptDefinition(
        concept_id=str(concept_id),
        answer=answer,
        prompt_version=prompt_version,
        aliases=aliases,
        editorial_difficulty=difficulty,
        content_rating=content_rating,
        tags=tags,
    )


async def seed_prompt_lists(
    repo: PromptListRepository,
    directory: Path | None = None,
) -> list[PromptListSummary]:
    """Scan and upsert all bundled prompt list JSON definitions into the database."""
    target_dir = directory or DEFAULT_PROMPT_LISTS_DIR
    if not target_dir.is_dir():
        logger.warning("Prompt lists directory not found at %s", target_dir)
        return []

    seeded: list[PromptListSummary] = []
    for file_path in sorted(target_dir.glob("*.json")):
        try:
            content = await asyncio.to_thread(file_path.read_text, encoding="utf-8")
            data = json.loads(content)
            slug = str(data["slug"]).strip()
            name = str(data["name"]).strip()
            description = str(data.get("description", "")).strip()
            language = validate_prompt_language(str(
                data.get("language", PromptLanguage.ENGLISH.value)
            ).strip())
            version = int(data.get("version", 1))
            if version < 1:
                raise ValueError("bundled list version must be positive")
            prompts = [
                _bundled_prompt(prompt, language=language)
                for prompt in data.get("prompts", [])
            ]
            if not prompts:
                raise ValueError("bundled prompt list must not be empty")

            summary = await repo.upsert_bundled(
                slug=slug,
                name=name,
                description=description,
                language=language,
                prompts=prompts,
                version=version,
            )
            seeded.append(summary)
            logger.info("Seeded bundled prompt list '%s' (v%d, %d prompts)", slug, version, len(prompts))
        except Exception:
            logger.exception("Failed to seed prompt list from %s", file_path)
            raise

    return seeded
