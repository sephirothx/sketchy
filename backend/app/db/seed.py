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
    clean_list_tags,
    clean_prompt_aliases,
    clean_prompt_tags,
    normalize_prompt_answer,
    validate_prompt_list_language,
    validate_shelf_placement,
)
from app.db.name_lists import expand_name_list, is_name_list
from app.repositories.interfaces import (
    BundledPromptDefinition,
    PromptListRepository,
    PromptListSummary,
)

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_LISTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "prompt_lists"


def bundled_list_bodies(directory: Path | None = None) -> list[tuple[Path, dict]]:
    """Every official list the seed files stand for, name lists expanded, with
    the file each came from. What startup seeds and what the content tests
    read, so the two can never disagree about the catalogue."""
    target_dir = directory or DEFAULT_PROMPT_LISTS_DIR
    bodies: list[tuple[Path, dict]] = []
    seen: dict[str, Path] = {}
    for file_path in sorted(target_dir.glob("*.json")):
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            expanded = expand_name_list(data) if is_name_list(data) else [data]
        except Exception as error:
            # Named, since a JSON error says only a line and a column.
            raise ValueError(f"{file_path.name}: {error!r}") from error
        for body in expanded:
            slug = str(body.get("slug", ""))
            # Two files standing for one list - an old per-language copy
            # beside its name list - would be one entry to whoever reads a
            # dict of these and two upserts to the seed.
            if slug in seen:
                raise ValueError(f"{file_path.name} and {seen[slug].name} both define {slug}")
            seen[slug] = file_path
            bodies.append((file_path, body))
    return bodies


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
    # The list-tag vocabulary is bundled content as much as the lists are
    # (R-LIST-18), and it is seeded here rather than beside this call so that
    # startup has one place that makes bundled content present.
    await repo.seed_list_tags()
    target_dir = directory or DEFAULT_PROMPT_LISTS_DIR
    if not target_dir.is_dir():
        logger.warning("Prompt lists directory not found at %s", target_dir)
        return []

    seeded: list[PromptListSummary] = []
    try:
        bodies = await asyncio.to_thread(bundled_list_bodies, target_dir)
    except Exception:
        logger.exception("Failed to read the prompt lists in %s", target_dir)
        raise
    for file_path, data in bodies:
        try:
            slug = str(data["slug"]).strip()
            name = str(data["name"]).strip()
            description = str(data.get("description", "")).strip()
            # A list in no language (`zxx`, R-PROMPT-12) is official content
            # too: the names that are the same in every language (#1374).
            language = validate_prompt_list_language(str(
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
            # Every official list stands somewhere in the picker's tree
            # (#1374); one that named no shelf would be on none.
            raw_series = data.get("series")
            shelf, series, position = validate_shelf_placement(
                str(data["shelf"]).strip(),
                None if raw_series is None else str(raw_series).strip(),
                int(data.get("position", 0)),
            )
            tags = clean_list_tags([str(tag) for tag in data.get("tags", [])])

            summary = await repo.upsert_bundled(
                slug=slug,
                name=name,
                description=description,
                language=language,
                prompts=prompts,
                version=version,
                shelf=shelf,
                series=series,
                shelf_position=position,
                tags=tags,
            )
            seeded.append(summary)
            logger.info("Seeded bundled prompt list '%s' (v%d, %d prompts)", slug, version, len(prompts))
        except Exception:
            logger.exception("Failed to seed prompt list from %s", file_path)
            raise

    await repo.refresh_planner_statistics()
    return seeded
