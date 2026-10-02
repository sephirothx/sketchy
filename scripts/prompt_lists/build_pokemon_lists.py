"""Regenerate the official Pokémon prompt lists (#1389) from PokeAPI's data.

Source: PokeAPI's species tables, `data/v2/csv/pokemon_species.csv` (the
generation of each species) and `pokemon_species_names.csv` (its name per
language), from https://github.com/PokeAPI/pokeapi - BSD-3-Clause; the names
themselves are Nintendo's trademarks, and the lists carry the names alone.
French, German, Spanish and Italian take their own names, with the English
one as an alias where it differs; Dutch, Polish and Portuguese editions use
the English names, which PokeAPI does not repeat for them.

    backend/.venv/bin/python scripts/prompt_lists/build_pokemon_lists.py <csv dir>

Concept ids are read back from the committed English files, keyed by the
species' English name, so a rerun keeps every identity and only a species
new to the data is minted one. A changed spelling or alias needs its
`promptVersion` raised by hand afterwards (R-PROMPT-05), and a new species
its file's `version`.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
from app.identifiers import generate_uuid7  # noqa: E402

OUT = REPO / "backend" / "data" / "prompt_lists"
POKEAPI_LANGUAGES = {"9": "en", "5": "fr", "6": "de", "7": "es", "8": "it"}
LANGUAGES = ["en", "de", "es", "fr", "it", "nl", "pl", "pt"]
STEM = {"en": "english", "de": "german", "es": "spanish", "fr": "french",
        "it": "italian", "nl": "dutch", "pl": "polish", "pt": "portuguese"}
NAME = {"en": "Pokémon — Generation {n}", "de": "Pokémon — Generation {n}",
        "es": "Pokémon — Generación {n}", "fr": "Pokémon — Génération {n}",
        "it": "Pokémon — Generazione {n}", "nl": "Pokémon — Generatie {n}",
        "pl": "Pokémon — Generacja {n}", "pt": "Pokémon — Geração {n}"}
DESCRIPTION = {
    "en": "Every Pokémon first seen in generation {n}.",
    "de": "Alle Pokémon, die in Generation {n} erschienen sind.",
    "es": "Todos los Pokémon que aparecieron en la generación {n}.",
    "fr": "Tous les Pokémon apparus dans la génération {n}.",
    "it": "Tutti i Pokémon comparsi nella generazione {n}.",
    "nl": "Alle Pokémon die in generatie {n} verschenen.",
    "pl": "Wszystkie Pokémony, które pojawiły się w generacji {n}.",
    "pt": "Todos os Pokémon que apareceram na geração {n}.",
}
# No keyboard types ♀ or ♂: each Nidoran also answers to its sex in words.
EXTRA_ALIASES = {
    29: {"en": ["Nidoran female", "female Nidoran", "Nidoran F"], "de": ["Nidoran weiblich", "Nidoran W"],
         "es": ["Nidoran hembra"], "fr": ["Nidoran femelle"], "it": ["Nidoran femmina"],
         "nl": ["Nidoran vrouwtje"], "pl": ["Nidoran samica"], "pt": ["Nidoran fêmea"]},
    32: {"en": ["Nidoran male", "male Nidoran", "Nidoran M"], "de": ["Nidoran männlich", "Nidoran M"],
         "es": ["Nidoran macho"], "fr": ["Nidoran mâle"], "it": ["Nidoran maschio"],
         "nl": ["Nidoran mannetje"], "pl": ["Nidoran samiec"], "pt": ["Nidoran macho"]},
}


def variants(text: str) -> list[str]:
    """What a guesser types for a name with punctuation in it. Matching folds
    case and accents but keeps hyphens, periods, colons and apostrophes, so
    "Ho-Oh" would not take "ho oh". An apostrophe or period goes without a
    trace (Farfetchd, Mr Mime); a hyphen or colon goes, or becomes a space
    where both sides stand as words (Ho Oh, Type Null, Porygon Z - not Kommo o);
    a digit after letters may stand apart (Porygon 2)."""
    text = text.replace("’", "'")
    out = {text.replace(":", ""), text.replace(": ", ":")}
    base = re.sub(r"[.']", "", text)
    out.add(base)
    joined = " ".join(re.sub(r"[-:]", "", base).split())
    out.add(joined)
    # Until nothing changes: one pass consumes the word after each hyphen, so
    # "Roc-de-Fer" would stop at "Roc de-Fer".
    spaced, previous = base, None
    while spaced != previous:
        previous = spaced
        spaced = re.sub(r"(\w{2,})[-:]\s*([A-Z0-9]\w*|\w{2,})", r"\1 \2", spaced)
    out.add(" ".join(spaced.split()))
    out.add(re.sub(r"([A-Za-z])(\d)", r"\1 \2", base))
    return sorted(v for v in out if v and v.lower() != text.lower())


def main() -> None:
    csv_dir = Path(sys.argv[1])
    generation = {
        int(row["id"]): int(row["generation_id"])
        for row in csv.DictReader(open(csv_dir / "pokemon_species.csv", encoding="utf-8"))
    }
    names: dict[int, dict[str, str]] = defaultdict(dict)
    for row in csv.DictReader(open(csv_dir / "pokemon_species_names.csv", encoding="utf-8")):
        language = POKEAPI_LANGUAGES.get(row["local_language_id"])
        if language:
            names[int(row["pokemon_species_id"])][language] = row["name"].replace("’", "'")
    for by_language in names.values():
        for language in ("nl", "pl", "pt"):
            by_language[language] = by_language["en"]

    known: dict[str, str] = {}
    for path in OUT.glob("english_pokemon_gen*.json"):
        for entry in json.loads(path.read_text(encoding="utf-8"))["prompts"]:
            known[entry["answer"]] = entry["conceptId"]
    # A promptVersion raised by hand stays raised, per language and concept.
    versions: dict[tuple[str, str], int] = {}
    for path in OUT.glob("*_pokemon_gen*.json"):
        body = json.loads(path.read_text(encoding="utf-8"))
        for entry in body["prompts"]:
            if "promptVersion" in entry:
                versions[(body["language"], entry["conceptId"])] = entry["promptVersion"]
    concept = {species: known.get(names[species]["en"]) or str(generate_uuid7()) for species in generation}

    for n in range(1, 10):
        members = [species for species in sorted(generation) if generation[species] == n]
        for language in LANGUAGES:
            prompts = []
            for species in members:
                answer = names[species][language]
                english = names[species]["en"]
                aliases: list[str] = []
                candidates = [english] if english.lower() != answer.lower() else []
                candidates += variants(answer) + variants(english) + EXTRA_ALIASES.get(species, {}).get(language, [])
                for candidate in candidates:
                    if candidate.lower() != answer.lower() and candidate.lower() not in {a.lower() for a in aliases}:
                        aliases.append(candidate)
                entry = {"conceptId": concept[species], "answer": answer}
                if aliases:
                    entry["aliases"] = aliases
                if (language, concept[species]) in versions:
                    entry["promptVersion"] = versions[(language, concept[species])]
                prompts.append(entry)
            body = {
                "slug": f"{STEM[language]}_pokemon_gen{n}",
                "name": NAME[language].format(n=n),
                "description": DESCRIPTION[language].format(n=n),
                "language": language,
                "version": 1,
                "shelf": "video-games",
                "series": "pokemon",
                "position": n,
                "tags": ["video-games"],
            }
            path = OUT / f"{STEM[language]}_pokemon_gen{n}.json"
            # Keep a version a hand edit already raised.
            if path.exists():
                body["version"] = json.loads(path.read_text(encoding="utf-8"))["version"]
            head = json.dumps(body, ensure_ascii=False, indent=2)[:-2]
            lines = ",\n".join(
                "    " + json.dumps(p, ensure_ascii=False, separators=(",", ":")) for p in prompts
            )
            path.write_text(f"{head},\n  \"prompts\": [\n{lines}\n  ]\n}}\n", encoding="utf-8")
    print(f"wrote {9 * len(LANGUAGES)} lists, {len(generation)} species")


if __name__ == "__main__":
    main()
