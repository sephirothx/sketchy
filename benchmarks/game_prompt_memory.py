#!/usr/bin/env python3
"""What a mixed-language game holds in memory for the prompts it drew (#1483).

A game draws every prompt it can need when it starts - rounds x seats x three
choices - and keeps them, each spelled in every room language, until it ends.
This seeds one official family (Standard by default: eight lists, one per
language), pins it the way a mixed room does, runs the real draw
(`GameFlowService._draw_mixed_prompt_sample`) and builds the `Game`, then
measures what the game holds: every object reached from its prompt fields,
counted once however many fields share it, by `sys.getsizeof`. The false
friends are left out: they are the repository's cache, shared by every room
playing the same lists.

Measured for #1483 at 3 rounds x 8 seats (72 concepts x 8 languages):
283 KB before; the spellings (`prompt_translations`) were 241 KB of it.

  backend/.venv/bin/python benchmarks/game_prompt_memory.py
  backend/.venv/bin/python benchmarks/game_prompt_memory.py --family landmarks --rounds 1 --seats 2

Runs on whatever `TEST_DATABASE_URL` names, or an in-memory SQLite database;
a database it is pointed at has its tables emptied first.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
from collections.abc import Mapping
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from sqlalchemy import select  # noqa: E402

from app.db.models import PromptList  # noqa: E402
from app.db.seed import DEFAULT_PROMPT_LISTS_DIR, seed_prompt_lists  # noqa: E402
from app.domain_values import MIXED_PROMPT_LANGUAGE, PROMPT_LANGUAGES  # noqa: E402
from app.game import PROMPT_CHOICES_PER_TURN, Game  # noqa: E402
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository  # noqa: E402
from app.services.game_flow import GameFlowService  # noqa: E402
from tests.dbfixtures import create_test_db  # noqa: E402

FIELDS = (
    "prompt_translations",
    "prompt_source_list_ids_by_key",
    "letter_counts_by_language",
    "prompt_version_ids",
    "prompt_pool",
    "prompt_answers",
    "prompt_aliases",
    "prompt_source_list_ids",
    "letter_total_by_language",
    "seat_languages",
    "turn_order",
)


def held(obj, seen: set[int]) -> int:
    """Bytes `obj` and everything it reaches hold, each object once."""
    if id(obj) in seen or obj is None or isinstance(obj, (bool, int, float)):
        return 0
    seen.add(id(obj))
    size = sys.getsizeof(obj)
    if isinstance(obj, (str, bytes)):
        return size
    if isinstance(obj, Mapping):
        return size + sum(held(key, seen) + held(value, seen) for key, value in obj.items())
    if isinstance(obj, (list, tuple, set, frozenset)):
        return size + sum(held(item, seen) for item in obj)
    if dataclasses.is_dataclass(obj):
        if hasattr(obj, "__dict__"):
            size += sys.getsizeof(obj.__dict__)
        return size + sum(held(getattr(obj, f.name), seen) for f in dataclasses.fields(obj))
    return size


def family_files(family: str) -> list[Path]:
    """The bundled files that make up one family: a themed list is one file
    spelling every language; Standard, Extended and Local are one per
    language (`english_standard.json` ...)."""
    files = sorted(
        path
        for path in DEFAULT_PROMPT_LISTS_DIR.glob("*.json")
        if path.stem == family or path.stem.endswith(f"_{family}")
    )
    if not files:
        raise SystemExit(f"no bundled list makes up a family called {family!r}")
    return files


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", default="standard")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--seats", type=int, default=8)
    parser.add_argument("--json-output")
    args = parser.parse_args()

    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        with tempfile.TemporaryDirectory() as directory:
            for path in family_files(args.family):
                shutil.copy(path, Path(directory) / path.name)
            await seed_prompt_lists(repo, Path(directory))
        async with factory() as session:
            english = await session.scalar(
                select(PromptList.slug).where(
                    PromptList.is_bundled.is_(True), PromptList.language == PROMPT_LANGUAGES[0]
                )
            )
        selection = await repo.authorize_selection([english], expected_language=MIXED_PROMPT_LANGUAGE)
        room = SimpleNamespace(
            id="benchmark",
            prompt_list_ids=list(selection.list_ids),
            prompt_list_versions=dict(selection.list_versions),
            prompt_edition_ids=dict(selection.edition_ids),
            prompt_letter_counts_by_language=dict(selection.letter_counts_by_language),
            prompt_letter_total_by_language=dict(selection.letter_total_by_language),
        )
        needed = args.rounds * args.seats * PROMPT_CHOICES_PER_TURN
        flow = SimpleNamespace(_ctx=SimpleNamespace(prompt_list_repo=repo))
        draw = await GameFlowService._draw_mixed_prompt_sample(flow, room, needed)
        seats = [f"seat-{index}" for index in range(args.seats)]
        game = Game(
            turn_order=seats,
            rounds_total=args.rounds,
            max_players=args.seats,
            prompt_pool=draw.pool,
            prompt_answers=draw.answers,
            prompt_aliases=draw.aliases,
            prompt_language=MIXED_PROMPT_LANGUAGE,
            prompt_source_list_ids=draw.source_list_ids,
            prompt_version_ids=draw.version_ids,
            prompt_source_list_ids_by_key=draw.source_list_ids_by_key,
            prompt_translations=draw.translations,
            letter_counts_by_language=draw.letter_counts_by_language,
            letter_total_by_language=draw.letter_total_by_language,
            false_friends=draw.false_friends,
            seat_languages={
                seat: PROMPT_LANGUAGES[index % len(PROMPT_LANGUAGES)]
                for index, seat in enumerate(seats)
            },
        )
        # The false friends are the repository's, shared by every room.
        seen = {id(game.false_friends)}
        sizes = {name: held(getattr(game, name), seen) for name in FIELDS}
        forms = sum(len(spelled) for spelled in game.prompt_translations.values())
        result = {
            "family": args.family,
            "rounds": args.rounds,
            "seats": args.seats,
            "concepts": len(game.prompt_pool or []),
            "forms": forms,
            "bytes": sizes,
            "total_bytes": sum(sizes.values()),
        }
        print(
            f"{args.family}: {result['concepts']} concepts, {forms} spellings "
            f"({args.rounds} rounds x {args.seats} seats)"
        )
        for name, size in sizes.items():
            print(f"  {name:32} {size:>9,} B")
        print(f"  {'prompt data held by the game':32} {result['total_bytes']:>9,} B")
        if args.json_output:
            await asyncio.to_thread(
                Path(args.json_output).write_text, json.dumps(result, indent=2) + "\n"
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
