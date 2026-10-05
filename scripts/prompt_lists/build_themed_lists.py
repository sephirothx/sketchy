"""Regenerate the themed official lists of #1401 - Superheroes, Movies and TV,
Landmarks - from their sources in `scripts/prompt_lists/sources/`.

    backend/.venv/bin/python scripts/prompt_lists/build_themed_lists.py

Each source is a JSON file: the list's slug, shelf, position, tags, names and
descriptions per language, and its prompts, each the English name and the name
every other language uses where it differs. Every list is written as a **name
list** (#1399): English as the default, and an override for each language that
spells the name its own way.

- Superheroes and Movies and TV are franchise names: a language that renames a
  character also accepts the English name, as its only alias, as Pokémon and
  League of Legends do (#1396).
- Landmarks are places, named in each language like the everyday lists, with
  no alias. A landmark Extended already holds is the same concept (an entry
  with `"extended": true`), copied here from each language's Extended entry -
  answer, aliases, version - because the seed holds one concept to one wording
  per language and version, and a room picking both lists draws it once.

Concept ids and any raised `promptVersion` are read back from the committed
files, keyed by the English name, so a rerun keeps every identity; a new
prompt is minted one. A changed spelling needs its `promptVersion` raised by
hand afterwards (R-PROMPT-05), and a changed list its file's `version`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
from app.db.name_lists import expand_name_list  # noqa: E402
from app.domain_values import PROMPT_LANGUAGES  # noqa: E402
from app.identifiers import generate_uuid7  # noqa: E402
from app.prompt_content import prompt_match_key  # noqa: E402

SOURCES = Path(__file__).resolve().parent / "sources"
OUT = REPO / "backend" / "data" / "prompt_lists"
STEM = {"en": "english", "de": "german", "es": "spanish", "fr": "french",
        "it": "italian", "nl": "dutch", "pl": "polish", "pt": "portuguese"}


def extended_entries() -> dict[str, dict[str, dict]]:
    """Each language's Extended entry, by the English answer of its concept."""
    by_concept: dict[str, dict[str, dict]] = {}
    for language, stem in STEM.items():
        for entry in json.loads((OUT / f"{stem}_extended.json").read_text(encoding="utf-8"))["prompts"]:
            by_concept.setdefault(entry["conceptId"], {})[language] = entry
    return {forms["en"]["answer"]: forms for forms in by_concept.values()}


def previous(slug: str) -> tuple[dict[str, str], dict[tuple[str, str], int], int]:
    """Identities, each language's resolved version, and the list version of
    the committed file, if there is one."""
    path = OUT / f"{slug}.json"
    if not path.exists():
        return {}, {}, 1
    body = json.loads(path.read_text(encoding="utf-8"))
    known = {entry["answer"]: entry["conceptId"] for entry in body["prompts"]}
    versions = {
        (expanded["language"], entry["conceptId"]): entry.get("promptVersion", 1)
        for expanded in expand_name_list(body)
        for entry in expanded["prompts"]
    }
    return known, versions, body.get("version", 1)


def build(source: dict, extended: dict[str, dict[str, dict]]) -> dict:
    known, versions, version = previous(source["slug"])
    franchise = source["kind"] == "franchise"
    prompts = []
    overriding: set[str] = set()
    for item in source["prompts"]:
        english = item["en"]
        if item.get("extended"):
            forms = extended[english]
            concept = forms["en"]["conceptId"]
            entry = {"conceptId": concept, "answer": english}
            if forms["en"].get("promptVersion", 1) != 1:
                entry["promptVersion"] = forms["en"]["promptVersion"]
            overrides = {}
            for language in PROMPT_LANGUAGES:
                if language == "en":
                    continue
                own = forms[language]
                if own["answer"] == english and own.get("promptVersion", 1) == entry.get("promptVersion", 1):
                    continue
                override = {"answer": own["answer"]}
                if own.get("aliases"):
                    override["aliases"] = list(own["aliases"])
                if own.get("promptVersion", 1) != 1:
                    override["promptVersion"] = own["promptVersion"]
                overrides[language] = override
        else:
            concept = known.get(english) or str(generate_uuid7())
            entry = {"conceptId": concept, "answer": english}
            default_version = versions.get(("en", concept), 1)
            if default_version != 1:
                entry["promptVersion"] = default_version
            overrides = {}
            for language in PROMPT_LANGUAGES:
                if language == "en":
                    continue
                own = item.get(language, english)
                version_here = versions.get((language, concept), default_version)
                if own == english and version_here == default_version:
                    continue
                override = {"answer": own}
                if franchise and prompt_match_key(own, language) != prompt_match_key(english, language):
                    override["aliases"] = [english]
                if version_here != 1:
                    override["promptVersion"] = version_here
                overrides[language] = override
        if overrides:
            entry["overrides"] = overrides
            overriding |= set(overrides)
        prompts.append(entry)
    order = list(PROMPT_LANGUAGES)
    return {
        "slug": source["slug"],
        "name": source["names"]["en"],
        "description": source["descriptions"]["en"],
        "names": {language: source["names"][language] for language in order if language != "en"},
        "descriptions": {language: source["descriptions"][language] for language in order if language != "en"},
        "version": version,
        "shelf": source["shelf"],
        "position": source["position"],
        "tags": source["tags"],
        "languages": {
            "inherit": [language for language in order if language not in overriding],
            "override": [language for language in order if language in overriding],
        },
        "prompts": prompts,
    }


def write(body: dict) -> None:
    head = json.dumps({k: v for k, v in body.items() if k != "prompts"}, ensure_ascii=False, indent=2)[:-2]
    lines = ",\n".join("    " + json.dumps(p, ensure_ascii=False, separators=(",", ":")) for p in body["prompts"])
    (OUT / f"{body['slug']}.json").write_text(f"{head},\n  \"prompts\": [\n{lines}\n  ]\n}}\n", encoding="utf-8")


def main() -> None:
    extended = extended_entries()
    for path in sorted(SOURCES.glob("*.json")):
        body = build(json.loads(path.read_text(encoding="utf-8")), extended)
        write(body)
        print(f"wrote {body['slug']}: {len(body['prompts'])} prompts")


if __name__ == "__main__":
    main()
