"""Which test modules mean anything when the suite runs on PostgreSQL.

The PostgreSQL job exists to prove what only a real server can: native types,
server defaults, row locks, READ COMMITTED interleavings, and the constraints
Alembic actually built. A test that never opens a database - or that opens a
SQLite file by name, as the concurrency suites deliberately do - runs there
byte for byte as it ran on the SQLite job, and the second run says nothing the
first did not. That is three fifths of the suite - 1,513 of 2,409 tests when
this was written - and a third of the job's test time.

What decides it is the import graph, not a list somebody maintains: a module
is database-backed when its imports reach `tests.dbfixtures` - the one fixture
`TEST_DATABASE_URL` moves onto PostgreSQL - or when it reads that variable
itself, as `test_db_connection_budgets.py` does to build an engine of its own.
A new suite is therefore included by importing the fixture every database test
already imports, and there is nothing to remember.

The walk is over imports rather than over the text because several modules
*mention* the fixture in a comment without using it, and a text match would
select them silently and for good. Whether it can under-select is the question
worth asking, and `test_database_backed.py` asks it of the real tree: the only
way left to reach a database is to name a SQLite URL, which is engine-specific
by construction and was never what this job ran.
"""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

TESTS_PACKAGE = "tests"
BACKEND_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_MODULE = f"{TESTS_PACKAGE}.dbfixtures"
URL_VARIABLE = "TEST_DATABASE_URL"


def module_name(path: Path, root: Path = BACKEND_ROOT) -> str:
    """The dotted name of a test module, from its path under `root`."""
    return ".".join(path.resolve().relative_to(root).with_suffix("").parts)


@lru_cache(maxsize=None)
def _reads(module: str, root: Path) -> tuple[frozenset[str], bool]:
    """The `tests.*` modules `module` imports, and whether it names the URL.

    A module with no source to read - a namespace package, or one built at
    runtime - imports nothing and names nothing, leaving the decision to
    whatever imported it.
    """
    path = root / Path(*module.split(".")).with_suffix(".py")
    if not path.is_file():
        return frozenset(), False
    imported: set[str] = set()
    names_url = False
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            # `from tests import dbfixtures` imports a module, not a name, so
            # both the package and each name under it are worth following.
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Constant) and node.value == URL_VARIABLE:
            names_url = True
        elif isinstance(node, ast.Name) and node.id == URL_VARIABLE:
            names_url = True
    return frozenset(n for n in imported if n.startswith(f"{TESTS_PACKAGE}.")), names_url


@lru_cache(maxsize=None)
def is_database_backed(module: str, root: Path = BACKEND_ROOT) -> bool:
    """Whether running `module` against PostgreSQL proves anything extra."""
    seen: set[str] = set()
    pending = [module]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if current == FIXTURE_MODULE:
            return True
        imports, names_url = _reads(current, root)
        if names_url:
            return True
        pending.extend(imports - seen)
    return False
