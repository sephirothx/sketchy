import asyncio
import json
import logging
from pathlib import Path

from app.repositories.interfaces import PromptListRepository, PromptListSummary

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_LISTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "prompt_lists"


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
            language = str(data.get("language", "en")).strip()
            version = int(data.get("version", 1))
            prompts = [str(w) for w in data.get("prompts", []) if str(w).strip()]

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

    return seeded
