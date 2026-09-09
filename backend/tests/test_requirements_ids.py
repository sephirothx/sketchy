"""A requirement ID must name exactly one requirement.

The point of numbering them is that `R-AUTH-17` in a commit message, a code
comment or a review means one thing, and that following a citation into
`docs/requirements.md` lands on the row that was meant. AGENTS.md says an ID is
retired by marking it withdrawn and never reused; nothing enforced it, and two
IDs ended up naming two requirements each (#726) - a newcomer taking a number
that was already in use, twice, months apart. Neither reviewer could reasonably
have spotted it by reading a diff of a 700-row table, which is what makes this a
test rather than a rule.

Non-goals (`N-nn`) live in the same table and carry the same promise, so they
are parsed and checked the same way.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = REPO_ROOT / "docs" / "requirements.md"

# Every requirement and non-goal is a table row whose first cell is the bolded
# ID and nothing else. Matching the row rather than the bare ID is what keeps a
# citation *inside* a requirement's prose - and there are many - from being read
# as a second declaration of it.
ROW = re.compile(r"^\| \*\*((?:R-[A-Z]+|N)-\d+)\*\*", re.MULTILINE)

# A floor, not a count: it moves with every change that adds a requirement, and
# a test that had to be edited by everyone would be edited without being read.
# It exists only so that a parser which silently stops matching is caught, since
# a set of nothing is trivially unique.
FEWEST_ROWS_WORTH_BELIEVING = 300


def declared_ids(text: str) -> list[str]:
    """The IDs declared by `text`, in the order the rows appear."""
    return ROW.findall(text)


def duplicates(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    repeated: list[str] = []
    for identifier in ids:
        if identifier in seen and identifier not in repeated:
            repeated.append(identifier)
        seen.add(identifier)
    return repeated


def test_the_document_is_still_being_parsed():
    ids = declared_ids(REQUIREMENTS.read_text(encoding="utf-8"))
    assert len(ids) >= FEWEST_ROWS_WORTH_BELIEVING, (
        f"only {len(ids)} rows matched - the table's shape changed and the "
        "uniqueness check below is now guarding nothing"
    )
    assert any(identifier.startswith("N-") for identifier in ids)


def test_no_id_names_two_requirements():
    ids = declared_ids(REQUIREMENTS.read_text(encoding="utf-8"))
    repeated = duplicates(ids)
    assert not repeated, (
        "these IDs each name more than one requirement in "
        f"docs/requirements.md: {', '.join(repeated)}. An ID is never reused: "
        "give the newcomer the next free number in its family and leave the "
        "older one meaning what every citation of it already means."
    )


def test_a_reused_id_is_refused():
    """The failure path, driven directly - a green table never exercises it."""
    reused = declared_ids(
        "| **R-AUTH-17** | An origin policy. |\n"
        "| **R-AUTH-19** | A password floor. |\n"
        "| **R-AUTH-17** | A password change. |\n"
        "| **N-03** | A non-goal. |\n"
    )
    assert duplicates(reused) == ["R-AUTH-17"]


def test_an_id_cited_inside_a_requirement_is_not_a_declaration():
    """Requirements cite each other constantly, and two rows citing the same
    third one must not read as that one being declared twice."""
    ids = declared_ids(
        "| **R-AUTH-03** | Bounded twice, see R-AUTH-20 and N-16. |\n"
        "| **R-AUTH-21** | Step-up, see R-AUTH-20. |\n"
    )
    assert ids == ["R-AUTH-03", "R-AUTH-21"]
