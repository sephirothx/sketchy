"""scripts/add-prompt.py: the authoring path for bundled prompt lists (#798).

The lists stay JSON because a prompt's identity is its `conceptId`, not its text
(docs/database.md, Seeding). What the script owes an author is that the file it
writes is still the checked-in layout, still seeds, and never reuses a key.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from app.db.seed import DEFAULT_PROMPT_LISTS_DIR, seed_prompt_lists
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository

from tests.dbfixtures import create_test_db

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "add-prompt.py"


def run(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--dir", str(directory), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def lists(tmp_path: Path) -> Path:
    directory = tmp_path / "prompt_lists"
    shutil.copytree(DEFAULT_PROMPT_LISTS_DIR, directory)
    return directory


def prompts(directory: Path, stem: str) -> dict:
    return json.loads((directory / f"{stem}.json").read_text(encoding="utf-8"))


async def test_an_added_prompt_is_a_one_line_change_that_still_seeds(tmp_path):
    directory = lists(tmp_path)
    before = (directory / "german_extended.json").read_text(encoding="utf-8").splitlines()

    result = run(directory, "german_extended", "Probeskizze", "--alias", "Testskizze")

    assert result.returncode == 0, result.stderr
    after_text = (directory / "german_extended.json").read_text(encoding="utf-8")
    after = after_text.splitlines()
    # The version line and the previous last prompt (which gains a comma) change,
    # and the new prompt is added; nothing else is rewritten.
    changed = [line for line in after if line not in before]
    assert len(changed) == 3, changed
    data = json.loads(after_text)
    assert data["version"] == 2
    added = data["prompts"][-1]
    assert added["answer"] == "Probeskizze" and added["aliases"] == ["Testskizze"]
    assert UUID(added["conceptId"]).version == 7

    factory, engine = await create_test_db()
    try:
        await seed_prompt_lists(SqlAlchemyPromptListRepository(factory), directory=directory)
    finally:
        await engine.dispose()


PLATYPUS = [
    "english_standard", "platypus",
    "--translation", "de=Schnabeltier", "--translation", "es=ornitorrinco",
    "--translation", "fr=ornithorynque", "--translation", "it=ornitorinco",
    "--translation", "nl=vogelbekdier", "--translation", "pt=ornitorrinco",
]


def snapshot(directory: Path) -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.json"))}


async def test_a_standard_prompt_lands_in_every_language_at_the_same_place(tmp_path):
    """Standard is one concept set translated into every language (R-PROMPT-01),
    so a Standard addition is one concept written to all seven lists."""
    directory = lists(tmp_path)

    result = run(directory, *PLATYPUS, "--translation-alias", "de=Platypus")

    assert result.returncode == 0, result.stderr
    standard = {path.stem: prompts(directory, path.stem) for path in directory.glob("*_standard.json")}
    orders = {stem: [p["conceptId"] for p in data["prompts"]] for stem, data in standard.items()}
    assert all(order == orders["english_standard"] for order in orders.values())
    assert {data["version"] for data in standard.values()} == {2}
    english = [p["answer"].casefold() for p in standard["english_standard"]["prompts"]]
    assert english == sorted(english)
    german = next(p for p in standard["german_standard"]["prompts"] if p["answer"] == "Schnabeltier")
    assert german["aliases"] == ["Platypus"]

    factory, engine = await create_test_db()
    try:
        await seed_prompt_lists(SqlAlchemyPromptListRepository(factory), directory=directory)
    finally:
        await engine.dispose()


def test_a_standard_prompt_missing_a_language_is_refused(tmp_path):
    directory = lists(tmp_path)
    before = snapshot(directory)

    result = run(directory, *PLATYPUS[:-2])

    assert result.returncode != 0
    assert "pt" in result.stderr
    assert snapshot(directory) == before


def test_a_single_standard_translation_is_refused(tmp_path):
    directory = lists(tmp_path)
    before = snapshot(directory)

    result = run(directory, "german_standard", "Schnabeltier")

    assert result.returncode != 0
    assert "english_standard" in result.stderr
    assert snapshot(directory) == before


def test_a_key_already_bundled_in_the_language_is_refused_before_anything_is_written(tmp_path):
    directory = lists(tmp_path)
    before = snapshot(directory)
    # "Brezel" is in German Extended; Standard and Extended are played together,
    # and the match key folds case, so a lowercase German translation collides -
    # and English Standard, validated first, must not have been written either.
    args = [arg if arg != "de=Schnabeltier" else "de=brezel" for arg in PLATYPUS]

    result = run(directory, *args)

    assert result.returncode != 0
    assert "german_extended" in result.stderr
    assert snapshot(directory) == before
