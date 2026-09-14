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


def test_a_translation_reuses_the_concept_it_translates(tmp_path):
    directory = lists(tmp_path)
    english = {p["answer"]: p["conceptId"] for p in prompts(directory, "english_extended")["prompts"]}
    source = next(answer for answer in english if " " not in answer)

    result = run(directory, "german_extended", "Übersetzungstest", "--same-as", f"english_extended:{source}")

    assert result.returncode == 0, result.stderr
    assert prompts(directory, "german_extended")["prompts"][-1]["conceptId"] == english[source]


def test_an_alphabetized_list_stays_alphabetized(tmp_path):
    directory = lists(tmp_path)

    assert run(directory, "english_standard", "Aardvark test").returncode == 0

    answers = [p["answer"].casefold() for p in prompts(directory, "english_standard")["prompts"]]
    assert answers == sorted(answers)


def test_a_key_already_bundled_in_the_language_is_refused(tmp_path):
    directory = lists(tmp_path)
    original = (directory / "german_standard.json").read_text(encoding="utf-8")
    # "Brezel" is in German Extended; Standard and Extended are played together,
    # and the match key folds case, so a lowercase copy in Standard collides.
    result = run(directory, "german_standard", "brezel")

    assert result.returncode != 0
    assert "german_extended" in result.stderr
    assert (directory / "german_standard.json").read_text(encoding="utf-8") == original
