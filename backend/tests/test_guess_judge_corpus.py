"""The golden corpus both guess judges answer to (#1434).

A room judges a guess on the server (`app/guess_judge.py`); Solo will judge
one in the browser, with a TypeScript port. `fixtures/guess_judge_cases.json`
is the one list of what a guess is that holds both to the same answers. This
side checks the Python judge still gives every recorded verdict; the port's
own test will check it does.

A deliberate change to a rule regenerates the verdicts from this judge:

    SKETCHY_REGENERATE_GUESS_CORPUS=1 .venv/bin/pytest tests/test_guess_judge_corpus.py

then read the diff - every flipped case is a change players will see - and
make the same change on the TypeScript side.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import pytest

from app.guess_judge import AnswerForm, JudgeTarget, judge

CORPUS_PATH = Path(__file__).resolve().parent.parent.parent / "fixtures" / "guess_judge_cases.json"
CORPUS = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
VERDICTS = ("correct", "close", "partial", "another_language", "held", None)
LANGUAGES = ("en", "de", "es", "fr", "it", "nl", "pl", "pt")


def target_of(raw: dict) -> JudgeTarget:
    return JudgeTarget(
        language=raw["language"],
        own=AnswerForm(raw["own"]["answer"], tuple(raw["own"]["aliases"])),
        others={
            language: AnswerForm(form["answer"], tuple(form["aliases"]))
            for language, form in raw["others"].items()
        },
        taken=frozenset(raw["taken"]),
    )


def test_regenerate_when_asked() -> None:
    if not os.environ.get("SKETCHY_REGENERATE_GUESS_CORPUS"):
        pytest.skip("set SKETCHY_REGENERATE_GUESS_CORPUS=1 to rewrite the verdicts")
    for case in CORPUS["cases"]:
        case["expected"] = judge(case["text"], target_of(case["target"]))
    CORPUS_PATH.write_text(json.dumps(CORPUS, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    "case", CORPUS["cases"], ids=[f"{i}-{c['text'][:24]}" for i, c in enumerate(CORPUS["cases"])]
)
def test_the_python_judge_gives_every_recorded_verdict(case: dict) -> None:
    assert judge(case["text"], target_of(case["target"])) == case["expected"], case["note"]


def test_the_corpus_reaches_every_verdict_and_every_language() -> None:
    # A corpus with no "partial" case would let the port drop the rule unseen.
    verdicts = Counter(case["expected"] for case in CORPUS["cases"])
    assert set(VERDICTS) <= set(verdicts)
    languages = {case["target"]["language"] for case in CORPUS["cases"]}
    assert set(LANGUAGES) <= languages
    assert any(case["target"]["others"] for case in CORPUS["cases"])
    assert any(case["target"]["taken"] for case in CORPUS["cases"])
