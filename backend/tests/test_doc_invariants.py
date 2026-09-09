"""What the reference documents promise about their own names.

Three promises, all of them about a reader following a reference and landing
somewhere unambiguous, and none of them checked by anything until #726:

An **ID names one requirement.** The point of numbering them is that
`R-AUTH-17` in a commit message, a code comment or a review means one thing.
AGENTS.md says an ID is retired by marking it withdrawn and never reused;
nothing enforced it, and two IDs ended up naming two requirements each - a
newcomer taking a number already in use, twice, months apart.

A **cited ID exists.** `R-AUTH-20` cited a fourth `R-ROLE` requirement, of
which there have only ever been two: the number was invented in the prose that
cites it, so the reference sent a reader looking for a requirement nobody wrote.
This test reads every tracked file, so an example spelled out in full here would
be a citation like any other - which is the check working, and why the story
above names no number.

A **glossary term is defined once.** GLOSSARY.md is the vocabulary, and it
carried two entries for **Name color** - the original and a fuller one added
four hundred rows away, which is exactly how far apart two definitions have to
be for nobody to notice.

None of the three is catchable by reading a diff of a seven-hundred-row table,
which is what makes them tests rather than rules.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = REPO_ROOT / "docs" / "requirements.md"
GLOSSARY = REPO_ROOT / "GLOSSARY.md"

# Every requirement and non-goal is a table row whose first cell is the bolded
# ID and nothing else. Matching the row rather than the bare ID is what keeps a
# citation *inside* a requirement's prose - and there are many - from being read
# as a second declaration of it.
DECLARATION = re.compile(r"^\| \*\*((?:R-[A-Z]+|N)-\d+)\*\*", re.MULTILINE)

# Two digits, always, which is also what keeps `N-1` in a benchmark's arithmetic
# ("a room of N costs N-1 of them") from being read as a citation.
CITATION = re.compile(r"\b((?:R-[A-Z]+|N)-\d{2})\b")

# A glossary entry is a table row of the same shape, the term bolded in the
# first cell. The bold marks the term, so a term is what the row's first cell
# holds and nothing else on the line matters.
GLOSSARY_TERM = re.compile(r"^\| \*\*([^*|]+)\*\* \|", re.MULTILINE)

# Floors, not counts: they move with every change that adds a requirement or a
# term, and a test that had to be edited by everyone would be edited without
# being read. They exist only so that a parser which silently stops matching is
# caught, since a set of nothing is trivially unique.
FEWEST_REQUIREMENTS_WORTH_BELIEVING = 300
FEWEST_TERMS_WORTH_BELIEVING = 100

# Anything git tracks and Python can read as text: a citation is as likely to be
# in a comment, a test docstring or a stylesheet as in one of the documents.
SKIPPED_TREES = ("frontend/node_modules/",)

requires_git = pytest.mark.skipif(
    shutil.which("git") is None or not (REPO_ROOT / ".git").exists(),
    reason="needs a git work tree",
)


def declared_ids(text: str) -> list[str]:
    """The IDs declared by `text`, in the order the rows appear."""
    return DECLARATION.findall(text)


def duplicates(names: list[str]) -> list[str]:
    seen: set[str] = set()
    repeated: list[str] = []
    for name in names:
        if name in seen and name not in repeated:
            repeated.append(name)
        seen.add(name)
    return repeated


def tracked_text_files() -> list[Path]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        REPO_ROOT / name
        for name in listing.stdout.split("\0")
        if name and not name.startswith(SKIPPED_TREES)
    ]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # A picture, a font, a fixture of bytes - nothing that cites anything.
        return ""


def test_the_documents_are_still_being_parsed():
    ids = declared_ids(REQUIREMENTS.read_text(encoding="utf-8"))
    terms = GLOSSARY_TERM.findall(GLOSSARY.read_text(encoding="utf-8"))
    assert len(ids) >= FEWEST_REQUIREMENTS_WORTH_BELIEVING, (
        f"only {len(ids)} requirement rows matched - the table's shape changed "
        "and the checks below are now guarding nothing"
    )
    assert any(identifier.startswith("N-") for identifier in ids)
    assert len(terms) >= FEWEST_TERMS_WORTH_BELIEVING, (
        f"only {len(terms)} glossary rows matched - same problem, other document"
    )


def test_no_id_names_two_requirements():
    ids = declared_ids(REQUIREMENTS.read_text(encoding="utf-8"))
    repeated = duplicates(ids)
    assert not repeated, (
        "these IDs each name more than one requirement in "
        f"docs/requirements.md: {', '.join(repeated)}. An ID is never reused: "
        "give the newcomer the next free number in its family and leave the "
        "older one meaning what every citation of it already means."
    )


def test_no_term_is_defined_twice():
    terms = GLOSSARY_TERM.findall(GLOSSARY.read_text(encoding="utf-8"))
    repeated = duplicates(terms)
    assert not repeated, (
        "these terms are defined more than once in GLOSSARY.md: "
        f"{', '.join(repeated)}. One agreed name per concept means one entry "
        "per name; two definitions of a term are two answers to the question "
        "the glossary exists to settle."
    )


@requires_git
def test_every_cited_id_exists():
    declared = set(declared_ids(REQUIREMENTS.read_text(encoding="utf-8")))
    dangling: dict[str, list[str]] = {}
    for path in tracked_text_files():
        for cited in sorted(set(CITATION.findall(read_text(path)))):
            if cited not in declared:
                dangling.setdefault(cited, []).append(
                    str(path.relative_to(REPO_ROOT))
                )
    assert not dangling, (
        "these IDs are cited but declared by no row in docs/requirements.md: "
        + "; ".join(
            f"{cited} ({', '.join(where)})" for cited, where in sorted(dangling.items())
        )
        + ". A number invented in the prose that cites it sends a reader "
        "looking for a requirement nobody wrote."
    )


def test_a_reused_id_is_refused():
    """The failure paths, driven directly - a green tree never exercises them."""
    reused = declared_ids(
        "| **R-AUTH-17** | An origin policy. |\n"
        "| **R-AUTH-19** | A password floor. |\n"
        "| **R-AUTH-17** | A password change. |\n"
        "| **N-03** | A non-goal. |\n"
    )
    assert duplicates(reused) == ["R-AUTH-17"]


def test_a_term_defined_twice_is_refused():
    terms = GLOSSARY_TERM.findall(
        "| **Nickname** | The name a player plays under. | handle |\n"
        "| **Picture** | An uploaded avatar. | photo |\n"
        "| **Nickname** | Something else entirely. | - |\n"
    )
    assert duplicates(terms) == ["Nickname"]


def test_an_id_cited_inside_a_requirement_is_not_a_declaration():
    """Requirements cite each other constantly, and two rows citing the same
    third one must not read as that one being declared twice."""
    ids = declared_ids(
        "| **R-AUTH-03** | Bounded twice, see R-AUTH-20 and N-16. |\n"
        "| **R-AUTH-21** | Step-up, see R-AUTH-20. |\n"
    )
    assert ids == ["R-AUTH-03", "R-AUTH-21"]


def test_arithmetic_is_not_a_citation():
    """`benchmarks/live_drawing.py` counts `N-1` peers in a room of N."""
    assert CITATION.findall("a room of N costs N-1 of them") == []
    assert CITATION.findall("recorded in N-16, cited by R-AUTH-19") == [
        "N-16",
        "R-AUTH-19",
    ]
