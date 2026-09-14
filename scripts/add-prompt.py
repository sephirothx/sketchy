#!/usr/bin/env python3
"""Add a prompt to the bundled prompt lists without hand-minting its identity.

The bundled lists in backend/data/prompt_lists/ are JSON rather than one answer
per line because a prompt is a record, not a word: its identity is a UUIDv7
`conceptId` that links one concept across languages and that usage statistics
attach to, and it may carry aliases (docs/database.md, Seeding). The cost of
that is authoring - a new prompt needs a fresh UUIDv7, a membership change
needs a higher list `version`, and a duplicate only surfaces when seeding
fails. This script does those things, and writes each file back in the
checked-in layout (one prompt per line) so the diff stays a one-line diff.

The two kinds of list are added to differently, because R-PROMPT-01 shapes them
differently:

- An **Extended** list is natively authored, so its prompt gets a concept of its
  own and only that file changes.
- **Standard** is one concept set translated into every language, so a Standard
  prompt is added to all of them at once: name `english_standard` and give a
  `--translation` for every other language. The script refuses a Standard
  addition that would leave any language without the concept, and writes
  nothing until every list has validated.

Usage:
  backend/.venv/bin/python scripts/add-prompt.py german_extended Wolpertinger
  backend/.venv/bin/python scripts/add-prompt.py english_standard platypus \\
      --translation de=Schnabeltier --translation es=ornitorrinco \\
      --translation fr=ornithorynque --translation it=ornitorinco \\
      --translation nl=vogelbekdier --translation pt=ornitorrinco
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.seed import DEFAULT_PROMPT_LISTS_DIR
from app.domain_values import PromptLanguage
from app.identifiers import generate_uuid7
from app.prompt_content import (
    clean_prompt_aliases,
    normalize_prompt_answer,
)

HEADER_KEYS = ("slug", "name", "description", "language", "version")
SOURCE_STANDARD = "english_standard"


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


@dataclass
class Wording:
    answer: str
    aliases: list[str] = field(default_factory=list)


def entry_for(directory: Path, language: str, concept: str, wording: Wording) -> dict:
    answer = " ".join(wording.answer.split())
    aliases = list(clean_prompt_aliases(wording.aliases, canonical_answer=answer, language=language))
    taken = taken_keys(directory, language)
    for text in [answer, *aliases]:
        key = normalize_prompt_answer(text, language)
        if key in taken:
            raise SystemExit(f"{text!r} is already bundled in {language} ({taken[key]})")
    entry: dict = {"conceptId": concept, "answer": answer}
    if aliases:
        entry["aliases"] = aliases
    return entry


def bump(data: dict) -> None:
    # Membership changed, so the list needs a version the database has not seen.
    data["version"] = int(data.get("version", 1)) + 1


def add_extended(directory: Path, stem: str, wording: Wording) -> dict:
    path, data = load(directory, stem)
    entry = entry_for(directory, data["language"], str(generate_uuid7()), wording)
    data["prompts"].append(entry)
    bump(data)
    path.write_text(dumps_list(data), encoding="utf-8")
    return entry


def add_standard(directory: Path, wording: Wording, translations: dict[str, Wording]) -> dict:
    """Add one concept to every Standard list, at the same place in each."""
    source_path, source = load(directory, SOURCE_STANDARD)
    languages = {language.value for language in PromptLanguage} - {source["language"]}
    if missing := sorted(languages - translations.keys()):
        raise SystemExit(
            "Standard is one concept set in every language (R-PROMPT-01); "
            f"add --translation for: {', '.join(missing)}"
        )
    if unknown := sorted(translations.keys() - languages):
        raise SystemExit(f"no Standard list to translate into for: {', '.join(unknown)}")

    concept = str(generate_uuid7())
    entry = entry_for(directory, source["language"], concept, wording)
    # English Standard is alphabetized; each translation keeps the English order,
    # so every copy goes in right after the concept that precedes it in English.
    order = [prompt["answer"].casefold() for prompt in source["prompts"]]
    position = sum(1 for existing in order if existing <= entry["answer"].casefold())
    previous = source["prompts"][position - 1]["conceptId"] if position else None

    writes = [(source_path, source, entry, position)]
    for path in sorted(directory.glob("*_standard.json")):
        if path == source_path:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        translated = entry_for(directory, data["language"], concept, translations[data["language"]])
        ids = [prompt["conceptId"] for prompt in data["prompts"]]
        writes.append((path, data, translated, ids.index(previous) + 1 if previous else 0))

    for path, data, new, at in writes:
        data["prompts"].insert(at, new)
        bump(data)
        path.write_text(dumps_list(data), encoding="utf-8")
    return entry


def pairs(values: list[str], option: str) -> list[tuple[str, str]]:
    parsed = []
    for value in values:
        language, sep, text = value.partition("=")
        if not sep:
            raise SystemExit(f"{option} takes LANG=TEXT, e.g. de=Schnabeltier")
        parsed.append((language.strip(), text))
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("list", help=f"an *_extended list, or {SOURCE_STANDARD} for a Standard prompt")
    parser.add_argument("answer")
    parser.add_argument("--alias", action="append", default=[], help="repeatable")
    parser.add_argument(
        "--translation", action="append", default=[], metavar="LANG=ANSWER",
        help="Standard only: the answer in another language; one per language",
    )
    parser.add_argument(
        "--translation-alias", action="append", default=[], metavar="LANG=ALIAS",
        help="Standard only: an alias for a translation; repeatable",
    )
    parser.add_argument("--dir", type=Path, default=DEFAULT_PROMPT_LISTS_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    wording = Wording(args.answer, args.alias)
    try:
        if args.list.endswith("_extended"):
            if args.translation or args.translation_alias:
                raise SystemExit("an Extended list is native to its language; it takes no translations")
            entry = add_extended(args.dir, args.list, wording)
        elif args.list == SOURCE_STANDARD:
            translations: dict[str, Wording] = {}
            for language, text in pairs(args.translation, "--translation"):
                if language in translations:
                    raise SystemExit(f"two translations given for {language}")
                translations[language] = Wording(text)
            for language, text in pairs(args.translation_alias, "--translation-alias"):
                if language not in translations:
                    raise SystemExit(f"--translation-alias for {language} has no --translation")
                translations[language].aliases.append(text)
            entry = add_standard(args.dir, wording, translations)
        else:
            raise SystemExit(
                f"a Standard prompt is added to every language at once: run against "
                f"{SOURCE_STANDARD} with a --translation per language"
            )
    except ValueError as error:
        raise SystemExit(str(error)) from None
    print(f"added {entry['answer']!r} as {entry['conceptId']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
