"""Regenerate the official League of Legends prompt list (#1390).

Source: Riot's Data Dragon champion data (`cdn/<version>/data/<locale>/
champion.json` from https://ddragon.leagueoflegends.com), names only. A
champion's name is the same in nearly every supported language, and Riot
renames a few per locale (Spanish "Bardo", French "Maître Yi", "Nunu et
Willump"), so the list is a **name list** (#1399): English spellings as the
default, and each locale's own name as an override where it differs - what
that language's drawer is shown and its hints spell - with the English name
still accepted there as an alias.

    backend/.venv/bin/python scripts/prompt_lists/build_league_of_legends_list.py <dir>

`<dir>` holds `champion.json` (en_US) and `champion_<locale>.json` for any of
de_DE, es_ES, fr_FR, it_IT, pl_PL and pt_BR; Data Dragon has no Dutch locale,
so Dutch takes the English names. Concept ids and any raised `promptVersion`
are read back from the committed file, so a rerun only adds champions new to
the data; a new one needs the file's `version` raised by hand afterwards.
"""
from __future__ import annotations

import json
import re
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
# A champion named like another prompt of some language's official lists is
# left out: the word was there first, and a room picking both would be
# refused as ambiguous - northern lights (Aurora), Dutch fire (Brand), the
# Spanish bullseye (Diana), Portuguese honey (Mel), and Poppy and Talon.
EXCLUDED = {"Aurora", "Brand", "Diana", "Mel", "Poppy", "Talon"}
# Short forms players type for the long names, in every language.
SHORT = {"Nunu & Willump": ["Nunu", "Nunu and Willump"], "Jarvan IV": ["Jarvan", "Jarvan 4"],
         "Dr. Mundo": ["Mundo"], "Renata Glasc": ["Renata"], "Aurelion Sol": ["Aurelion"]}
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


def variants(name: str) -> list[str]:
    """What a guesser types without the punctuation the matcher keeps."""
    return sorted({
        " ".join(re.sub(r"[.':&]", "", name).split()),
        " ".join(re.sub(r"[.':&]", " ", name).split()),
    } - {name})


def aliases_for(answer: str, extra: list[str], language: str) -> list[str]:
    """One alias per spelling the language's fold tells apart, the answer's
    own excluded."""
    seen = {prompt_match_key(answer, language)}
    out = []
    for candidate in [*variants(answer), *extra]:
        folded = prompt_match_key(candidate, language)
        if folded not in seen:
            seen.add(folded)
            out.append(candidate)
    return sorted(out)


def main() -> None:
    source = Path(sys.argv[1])
    english = {
        key: champion["name"]
        for key, champion in json.loads((source / "champion.json").read_text(encoding="utf-8"))["data"].items()
    }
    localized: dict[str, dict[str, str]] = {language: {} for language in LOCALES}
    for language, locale in LOCALES.items():
        path = source / f"champion_{locale}.json"
        if path.exists():
            for key, champion in json.loads(path.read_text(encoding="utf-8"))["data"].items():
                if key in english:
                    localized[language][english[key]] = champion["name"]

    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"prompts": [], "version": 1}
    known = {entry["answer"]: entry["conceptId"] for entry in previous["prompts"]}
    versions: dict[tuple[str, str], int] = {}
    for expanded in (expand_name_list(previous) if is_name_list(previous) else [previous]):
        for entry in expanded["prompts"]:
            if "promptVersion" in entry:
                versions[(expanded.get("language", "en"), entry["conceptId"])] = entry["promptVersion"]

    prompts = []
    overriding: set[str] = set()
    for name in sorted(english.values()):
        if name in EXCLUDED:
            continue
        concept = known.get(name) or str(generate_uuid7())
        entry = {"conceptId": concept, "answer": name}
        aliases = aliases_for(name, SHORT.get(name, []), "en")
        if aliases:
            entry["aliases"] = aliases
        if ("en", concept) in versions:
            entry["promptVersion"] = versions[("en", concept)]
        overrides = {}
        for language in sorted(LOCALES, key=list(PROMPT_LANGUAGES).index):
            own = localized[language].get(name, name)
            if own == name:
                continue
            override = {"answer": own}
            own_aliases = aliases_for(own, [name, *variants(name), *SHORT.get(name, [])], language)
            if own_aliases:
                override["aliases"] = own_aliases
            if versions.get((language, concept), 1) != 1:
                override["promptVersion"] = versions[(language, concept)]
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
