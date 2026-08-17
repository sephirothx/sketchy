"""Startup data seeder for bundled curated word lists."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.repositories.interfaces import WordListRepository, WordListSummary

logger = logging.getLogger(__name__)

DEFAULT_WORD_LISTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "word_lists"


async def seed_word_lists(
    repo: WordListRepository,
    directory: Path | None = None,
) -> list[WordListSummary]:
    """Scan and upsert all bundled word list JSON definitions into the database."""
    target_dir = directory or DEFAULT_WORD_LISTS_DIR
    if not target_dir.is_dir():
        logger.warning("Word lists directory not found at %s", target_dir)
        return []

    seeded: list[WordListSummary] = []
    for file_path in sorted(target_dir.glob("*.json")):
        try:
            content = file_path.read_text(encoding="utf-8")
            data = json.loads(content)
            slug = str(data["slug"]).strip()
            name = str(data["name"]).strip()
            description = str(data.get("description", "")).strip()
            language = str(data.get("language", "en")).strip()
            version = int(data.get("version", 1))
            words = [str(w) for w in data.get("words", []) if str(w).strip()]

            summary = await repo.upsert_bundled(
                slug=slug,
                name=name,
                description=description,
                language=language,
                words=words,
                version=version,
            )
            seeded.append(summary)
            logger.info("Seeded bundled word list '%s' (v%d, %d words)", slug, version, len(words))
        except Exception:
            logger.exception("Failed to seed word list from %s", file_path)

    return seeded
