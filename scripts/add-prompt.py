#!/usr/bin/env python3
"""Add a prompt to a bundled prompt list without hand-minting its identity.

The bundled lists in backend/data/prompt_lists/ are JSON rather than one answer
per line because a prompt is a record, not a word: its identity is a UUIDv7
`conceptId` that links one concept across languages and that usage statistics
attach to, and it may carry aliases (docs/database.md, Seeding). The cost of
that is authoring - a new prompt needs a fresh UUIDv7, a membership change
needs a higher list `version`, and a duplicate only surfaces when seeding
fails. This script does those three things, and writes the file back in the
checked-in layout (one prompt per line) so the diff stays a one-line diff.

A translation reuses the concept it translates: `--same-as english_standard:anchor`
takes that prompt's `conceptId` instead of minting one.

Usage:
  backend/.venv/bin/python scripts/add-prompt.py german_extended Schultüte
  backend/.venv/bin/python scripts/add-prompt.py german_standard Anker --same-as english_standard:anchor
  backend/.venv/bin/python scripts/add-prompt.py spanish_standard perro --alias "el perro"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.seed import DEFAULT_PROMPT_LISTS_DIR
from app.identifiers import generate_uuid7
from app.prompt_content import (
    clean_prompt_aliases,
    normalize_prompt_answer,
)

HEADER_KEYS = ("slug", "name", "description", "language", "version")


def dumps_list(data: dict) -> str:
    """Serialize a list in the checked-in layout: indented header, one prompt per line."""
    lines = ["{"]
    for key in HEADER_KEYS:
        if key in data:
            lines.append(f"  {json.dumps(key)}: {json.dumps(data[key], ensure_ascii=False)},")
    lines.append('  "prompts": [')
    prompts = [
        "    " + json.dumps(prompt, ensure_ascii=False, separators=(",", ":"))
        for prompt in data["prompts"]
    ]
    lines.append(",\n".join(prompts))
    lines.append("  ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def load(directory: Path, stem: str) -> tuple[Path, dict]:
    path = directory / f"{stem}.json"
    if not path.is_file():
        raise SystemExit(f"no bundled list named {stem!r} in {directory}")
    return path, json.loads(path.read_text(encoding="utf-8"))


def taken_keys(directory: Path, language: str) -> dict[str, str]:
    """Match keys of every answer and alias already bundled in `language`.

    Standard and Extended are played together, so a key in either list is taken.
    """
    taken: dict[str, str] = {}
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("language") != language:
            continue
        for prompt in data["prompts"]:
            for text in [prompt["answer"], *prompt.get("aliases", [])]:
                taken.setdefault(normalize_prompt_answer(text, language), f"{path.stem}: {prompt['answer']}")
    return taken


def concept_of(directory: Path, reference: str) -> UUID:
    stem, sep, answer = reference.partition(":")
    if not sep:
        raise SystemExit("--same-as takes LIST:ANSWER, e.g. english_standard:anchor")
    _, data = load(directory, stem)
    key = normalize_prompt_answer(answer, data["language"])
    for prompt in data["prompts"]:
        if normalize_prompt_answer(prompt["answer"], data["language"]) == key:
            return UUID(prompt["conceptId"])
    raise SystemExit(f"{stem} has no prompt {answer!r}")


def add_prompt(
    directory: Path,
    stem: str,
    answer: str,
    *,
    aliases: list[str],
    same_as: str | None = None,
) -> dict:
    path, data = load(directory, stem)
    language = data["language"]
    answer = " ".join(answer.split())
    cleaned_aliases = list(clean_prompt_aliases(aliases, canonical_answer=answer, language=language))

    taken = taken_keys(directory, language)
    for text in [answer, *cleaned_aliases]:
        key = normalize_prompt_answer(text, language)
        if key in taken:
            raise SystemExit(f"{text!r} is already bundled in {language} ({taken[key]})")

    concept = concept_of(directory, same_as) if same_as else generate_uuid7()
    if any(prompt["conceptId"] == str(concept) for prompt in data["prompts"]):
        raise SystemExit(f"{stem} already holds concept {concept}")

    entry: dict = {"conceptId": str(concept), "answer": answer}
    if cleaned_aliases:
        entry["aliases"] = cleaned_aliases
    prompts = data["prompts"]
    order = [prompt["answer"].casefold() for prompt in prompts]
    # Keep an alphabetized list alphabetized; a translation follows its source's
    # order instead, so anything else is appended.
    if order == sorted(order):
        position = sum(1 for existing in order if existing <= answer.casefold())
        prompts.insert(position, entry)
    else:
        prompts.append(entry)
    # Membership changed, so the list needs a version the database has not seen.
    data["version"] = int(data.get("version", 1)) + 1
    path.write_text(dumps_list(data), encoding="utf-8")
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("list", help="list file stem, e.g. german_extended")
    parser.add_argument("answer")
    parser.add_argument("--alias", action="append", default=[], help="repeatable")
    parser.add_argument("--same-as", metavar="LIST:ANSWER", help="reuse that prompt's conceptId (a translation)")
    parser.add_argument("--dir", type=Path, default=DEFAULT_PROMPT_LISTS_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        entry = add_prompt(args.dir, args.list, args.answer, aliases=args.alias, same_as=args.same_as)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    print(f"added {entry['answer']!r} to {args.list} as {entry['conceptId']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
