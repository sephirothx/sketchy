"""Regenerate the official League of Legends prompt list (#1390).

Source: Riot's Data Dragon champion data (`cdn/<version>/data/en_US/
champion.json` from https://ddragon.leagueoflegends.com), names only. A
champion's name is the same in every supported language, so the list is in
no language (`zxx`, R-PROMPT-12) and a room of any language plays it.

    backend/.venv/bin/python scripts/prompt_lists/build_league_of_legends_list.py <champion.json>

Concept ids and any raised `promptVersion` are read back from the committed
file, so a rerun only adds champions that are new to the data; a new one
needs the file's `version` raised by hand afterwards.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
from app.identifiers import generate_uuid7  # noqa: E402

OUT = REPO / "backend" / "data" / "prompt_lists" / "league_of_legends.json"
# A champion named like an everyday word of some language's official lists
# is left out: the word was there first, and a room picking both would be
# refused as ambiguous - northern lights (Aurora), Dutch fire (Brand), the
# Spanish bullseye (Diana), Portuguese honey (Mel), and Poppy and Talon.
EXCLUDED = {"Aurora", "Brand", "Diana", "Mel", "Poppy", "Talon"}
# Short forms players type for the long names.
SHORT = {"Nunu & Willump": ["Nunu", "Nunu and Willump"], "Jarvan IV": ["Jarvan", "Jarvan 4"],
         "Dr. Mundo": ["Mundo"], "Renata Glasc": ["Renata"], "Aurelion Sol": ["Aurelion"]}


def main() -> None:
    champions = sorted(
        champion["name"]
        for champion in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["data"].values()
    )
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"prompts": [], "version": 1}
    known = {entry["answer"]: entry for entry in previous["prompts"]}
    prompts = []
    for name in champions:
        if name in EXCLUDED:
            continue
        aliases = sorted({
            " ".join(re.sub(r"[.':&]", "", name).split()),
            " ".join(re.sub(r"[.':&]", " ", name).split()),
        } - {name})
        aliases += [alias for alias in SHORT.get(name, []) if alias not in aliases]
        entry = {"conceptId": known.get(name, {}).get("conceptId") or str(generate_uuid7()), "answer": name}
        if aliases:
            entry["aliases"] = sorted(aliases)
        if "promptVersion" in known.get(name, {}):
            entry["promptVersion"] = known[name]["promptVersion"]
        prompts.append(entry)
    body = {"slug": "league_of_legends", "name": "League of Legends",
            "description": "Every League of Legends champion, by name.",
            "language": "zxx", "version": previous["version"], "shelf": "video-games",
            "position": 10, "tags": ["video-games"]}
    head = json.dumps(body, ensure_ascii=False, indent=2)[:-2]
    lines = ",\n".join("    " + json.dumps(p, ensure_ascii=False, separators=(",", ":")) for p in prompts)
    OUT.write_text(f"{head},\n  \"prompts\": [\n{lines}\n  ]\n}}\n", encoding="utf-8")
    print(f"wrote {len(prompts)} champions")


if __name__ == "__main__":
    main()
