"""Regenerate the official League of Legends prompt list (#1390).

Source: Riot's Data Dragon champion data (`cdn/<version>/data/<locale>/
champion.json` from https://ddragon.leagueoflegends.com), names only. A
champion's name is the same in nearly every supported language, and Riot
renames a few per locale (Spanish "Bardo", French "Maître Yi", "Nunu et
Willump"), so the list is a **name list** (#1399): English spellings as the
default, and each locale's own name as an override where it differs - what
that language's drawer is shown and its hints spell - with the English name
still accepted there, as the only alias (#1396). Portuguese is the exception
the other way round: Riot's Portuguese is Brazil's, so the English name is the
answer and Riot's the alias. An "&" is written as the
language's own "and" ("Nunu and Willump", "Nunu und Willump"); matching reads
a typed "&" the same way.

    backend/.venv/bin/python scripts/prompt_lists/build_league_of_legends_list.py <dir>

`<dir>` holds `champion.json` (en_US) and `champion_<locale>.json` for each of
de_DE, es_ES, fr_FR, it_IT, pl_PL and pt_BR - all six, or nothing is written;
Data Dragon has no Dutch locale, so Dutch takes the English names. Concept ids and any raised `promptVersion`
are read back from the committed file, so a rerun only adds champions new to
the data; a new one needs the file's `version` raised by hand afterwards.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
from app.db.name_lists import expand_name_list, is_name_list  # noqa: E402
from app.domain_values import PROMPT_LANGUAGES  # noqa: E402
from app.identifiers import generate_uuid7  # noqa: E402
from app.prompt_content import prompt_match_key  # noqa: E402

OUT = REPO / "backend" / "data" / "prompt_lists" / "league_of_legends.json"
LOCALES = {"de": "de_DE", "es": "es_ES", "fr": "fr_FR", "it": "it_IT", "pl": "pl_PL", "pt": "pt_BR"}
# "&" as each language writes it in a name (#1396).
AND = {"en": "and", "de": "und", "es": "y", "fr": "et", "it": "e", "nl": "en", "pl": "i", "pt": "e"}
# Languages whose players know the champions by their English names (#1396).
ENGLISH_FIRST = {"pt"}
DESCRIPTION = {
    "en": "Every League of Legends champion, by name.",
    "de": "Jeder Champion aus League of Legends, beim Namen.",
    "es": "Todos los campeones de League of Legends, por su nombre.",
    "fr": "Tous les champions de League of Legends, par leur nom.",
    "it": "Tutti i campioni di League of Legends, per nome.",
    "nl": "Elke kampioen uit League of Legends, bij naam.",
    "pl": "Wszyscy bohaterowie League of Legends, z imienia.",
    "pt": "Todos os campeões de League of Legends, pelo nome.",
}


def spelled(name: str, language: str) -> str:
    return " ".join(name.replace("&", f" {AND[language]} ").split())


def main() -> None:
    source = Path(sys.argv[1])
    english = {
        key: champion["name"]
        for key, champion in json.loads((source / "champion.json").read_text(encoding="utf-8"))["data"].items()
    }
    # Every locale, or nothing is written: a missing file would read as "no
    # champion is renamed there" and drop every override it held.
    missing = [f"champion_{locale}.json" for locale in LOCALES.values()
               if not (source / f"champion_{locale}.json").exists()]
    if missing:
        sys.exit(f"missing locale files in {source}: {', '.join(missing)}")
    localized: dict[str, dict[str, str]] = {language: {} for language in LOCALES}
    for language, locale in LOCALES.items():
        path = source / f"champion_{locale}.json"
        for key, champion in json.loads(path.read_text(encoding="utf-8"))["data"].items():
            if key in english:
                localized[language][english[key]] = champion["name"]

    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"prompts": [], "version": 1}
    known = {entry["answer"]: entry["conceptId"] for entry in previous["prompts"]}
    versions: dict[tuple[str, str], int] = {}
    for expanded in (expand_name_list(previous) if is_name_list(previous) else [previous]):
        # Every language's resolved version, the implicit 1 included: an
        # override that gives none is at 1, not at whatever the default is.
        for entry in expanded["prompts"]:
            versions[(expanded.get("language", "en"), entry["conceptId"])] = entry.get("promptVersion", 1)

    prompts = []
    overriding: set[str] = set()
    for name in sorted(english.values()):
        default = spelled(name, "en")
        concept = known.get(default) or str(generate_uuid7())
        entry = {"conceptId": concept, "answer": default}
        if versions.get(("en", concept), 1) != 1:
            entry["promptVersion"] = versions[("en", concept)]
        default_version = entry.get("promptVersion", 1)
        overrides = {}
        # Every language but the default's, Dutch included (no Data Dragon
        # locale, so English names): a language inherits only when its whole
        # entry - spelling, aliases and version - is the default's. One whose
        # version moved on its own keeps an override even when it spells the
        # name the English way, or a rerun would put it back to the default's
        # version under content it already holds (#1400 review).
        for language in [language for language in PROMPT_LANGUAGES if language != "en"]:
            riot = spelled(localized.get(language, {}).get(name, name), language)
            # Riot localizes Portuguese for Brazil only, and Sketchy's
            # Portuguese is Portugal's, where the English client is played:
            # the English name is the answer and Riot's the alias.
            own, other = (default, riot) if language in ENGLISH_FIRST else (riot, default)
            version = versions.get((language, concept), default_version)
            aliases = [other] if prompt_match_key(own, language) != prompt_match_key(other, language) else []
            if own == default and not aliases and version == default_version:
                continue
            override = {"answer": own}
            if aliases:
                override["aliases"] = aliases
            if version != 1:
                override["promptVersion"] = version
            overrides[language] = override
            overriding.add(language)
        if overrides:
            entry["overrides"] = overrides
        prompts.append(entry)

    order = list(PROMPT_LANGUAGES)
    body = {
        "slug": "league_of_legends",
        "name": "League of Legends",
        "description": DESCRIPTION["en"],
        "descriptions": {language: DESCRIPTION[language] for language in order if language != "en"},
        "version": previous["version"],
        "shelf": "video-games",
        "position": 10,
        "tags": ["video-games"],
        # Every supported language, each one checked: Dutch has no Data
        # Dragon locale and plays the English names.
        "languages": {
            "inherit": [language for language in order if language not in overriding],
            "override": [language for language in order if language in overriding],
        },
    }
    head = json.dumps(body, ensure_ascii=False, indent=2)[:-2]
    lines = ",\n".join("    " + json.dumps(p, ensure_ascii=False, separators=(",", ":")) for p in prompts)
    OUT.write_text(f"{head},\n  \"prompts\": [\n{lines}\n  ]\n}}\n", encoding="utf-8")
    print(f"wrote {len(prompts)} champions; overriding {sorted(overriding)}")


if __name__ == "__main__":
    main()
