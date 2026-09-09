"""What `--database-backed-only` may and may not leave out.

The flag exists to stop the PostgreSQL job re-running tests that already ran,
unchanged, on the SQLite job (`tests/database_backed.py`). Its whole risk is
under-selection: a test that *does* mean something on PostgreSQL and is left
out fails nowhere and is missed by nobody, which is the failure this file is
here to make loud.

So the last test asks the real tree, not a fixture: every module that reaches
for the shared fixture must be selected. The rest pin the classifier's shape -
that it follows imports through a helper, that it reads an import graph rather
than the text, and that naming the URL is enough on its own.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.database_backed import BACKEND_ROOT, is_database_backed, module_name

pytest_plugins = ["pytester"]

FIXTURE_CALLS = {"create_test_db", "create_test_engine"}


def tree(root: Path, **modules: str) -> Path:
    """A `tests` package under `root` holding the sources given."""
    package = root / "tests"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "dbfixtures.py").write_text("def create_test_db(): ...\n")
    for name, source in modules.items():
        (package / f"{name}.py").write_text(source)
    return root


def test_a_module_importing_the_fixture_is_selected(tmp_path):
    root = tree(tmp_path, test_rows="from tests.dbfixtures import create_test_db\n")
    assert is_database_backed("tests.test_rows", root)


def test_the_fixture_is_followed_through_a_helper(tmp_path):
    """Most suites reach it through `staffauth` or a sibling, not directly."""
    root = tree(
        tmp_path,
        helper="from tests.dbfixtures import create_test_db\n",
        test_rows="from tests.helper import create_test_db\n",
    )
    assert is_database_backed("tests.test_rows", root)


def test_naming_the_url_is_enough_without_the_fixture(tmp_path):
    """`test_db_connection_budgets.py` builds its own engine from it."""
    root = tree(tmp_path, test_budgets='import os\nURL = os.environ["TEST_DATABASE_URL"]\n')
    assert is_database_backed("tests.test_budgets", root)


def test_a_module_that_only_mentions_the_fixture_is_not_selected(tmp_path):
    """The reason the walk is over imports: a comment is not a use.

    `tests/conftest.py` and half a dozen suites explain the fixture without
    touching it, and a text match would send every one of them to PostgreSQL
    for good.
    """
    root = tree(
        tmp_path,
        test_pure="# Changing only dbfixtures is too late; see TEST_DATABASE_URL.\n",
    )
    assert not is_database_backed("tests.test_pure", root)


def test_pure_logic_is_not_selected(tmp_path):
    root = tree(tmp_path, test_scoring="def test_a_round_scores(): assert True\n")
    assert not is_database_backed("tests.test_scoring", root)


def test_the_flag_deselects_and_leaves_the_rest_running(pytester):
    """End to end, through the option the PostgreSQL job actually passes."""
    pytester.makefile(".ini", pytest="[pytest]\npythonpath = .\n")
    pytester.makeconftest((BACKEND_ROOT / "tests" / "conftest.py").read_text())
    package = pytester.path / "tests"
    package.mkdir()
    (package / "__init__.py").write_text("")
    # Only the names the conftest's own imports need: this stands in for the
    # fixture, it does not have to be one.
    (package / "dbfixtures.py").write_text(
        "def create_test_db(): ...\n\n\ndef assert_disposable(url): ...\n"
    )
    for name in ("database_backed", "parallel_databases"):
        (package / f"{name}.py").write_text((BACKEND_ROOT / "tests" / f"{name}.py").read_text())
    (package / "test_rows.py").write_text(
        "from tests.dbfixtures import create_test_db\n\n\ndef test_a_row_lands(): pass\n"
    )
    (package / "test_scoring.py").write_text("def test_a_round_scores(): pass\n")

    # A subprocess, not this process: the real `tests` package is already in
    # `sys.modules` here, and an in-process run would resolve the fixture
    # module against it rather than against the tree just built.
    everything = pytester.runpytest_subprocess("-q")
    everything.assert_outcomes(passed=2)

    selected = pytester.runpytest_subprocess("-q", "--database-backed-only")
    selected.assert_outcomes(passed=1, deselected=1)


def modules_reaching_for_the_fixture() -> list[str]:
    """Every test module in the tree that calls the shared fixture by name."""
    reaching = []
    for path in sorted((BACKEND_ROOT / "tests").rglob("test_*.py")):
        called = {
            node.func.id
            for node in ast.walk(ast.parse(path.read_text(), filename=str(path)))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        if called & FIXTURE_CALLS:
            reaching.append(module_name(path))
    return reaching


def test_every_module_calling_the_fixture_is_selected():
    """The invariant the flag is only safe under, asked of the real tree.

    A module left out here is a suite that stops being proven on PostgreSQL
    while every job stays green.
    """
    reaching = modules_reaching_for_the_fixture()
    assert len(reaching) > 40, "the scan stopped finding callers; it is the check"
    missed = [module for module in reaching if not is_database_backed(module)]
    assert missed == []


@pytest.mark.parametrize("module", ["tests.test_game", "tests.test_rooms"])
def test_the_pure_logic_suites_stay_out(module):
    """`game.py` and `rooms.py` do no I/O, so neither do their suites."""
    assert not is_database_backed(module)
