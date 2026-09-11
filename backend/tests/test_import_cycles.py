"""Every module imports on its own, in a process that imported nothing first.

R-ENG-18.

A circular import is not a broken program. It is a program whose correctness
depends on which module the interpreter reached first, and a test suite hides
that by construction: `pytest` collects `tests/` alphabetically, something
early imports `app.handlers`, and from then on every cycle in the package is
already resolved in a working order. The suite passes. `python -c "import
app.api.admin_controls"` does not, and neither does running that one test
module by itself - which is how #788 was found, and how it stayed invisible
for as long as it did.

So the check has to be one fresh interpreter per module. Importing them all
into *this* process would prove nothing: the first import warms the graph for
every import after it, which is the very effect being tested for. Subprocesses
are the point, not an implementation detail, and they are why this file is the
slowest structural test in the suite (a few seconds for ~140 modules, run
concurrently because each one spends its time blocked on the interpreter
starting).

The cycle #788 fixed was a misplaced import: `app/services/shutdown.py` named
`ErrorCode` from `app.handlers.refusals`, when the vocabulary has lived in
`app.refusals` since #760 precisely so that `app/api` and `app/handlers` -
siblings - can both raise it without either owning it. The one still standing
is a layering inversion rather than a typo, and is tracked separately.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"

# Modules known to still fail on their own, each with the issue that will fix
# it. These are asserted to *keep* failing rather than skipped, so that the
# change which untangles one is told to delete its entry here - an allowlist
# nobody is forced to revisit rots into a list of things that were fixed years
# ago and a test that no longer checks them.
KNOWN_CYCLES = {
    "app.services.game_flow": "#789",
}


def _module_names() -> list[str]:
    """Every importable module under `app/`, as a dotted name."""
    names = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        parts = list(path.relative_to(BACKEND_ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        names.append(".".join(parts))
    return names


def _import_in_fresh_process(module: str) -> tuple[str, int, str]:
    """Import `module` first in an interpreter that has imported nothing else."""
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return module, result.returncode, result.stderr.strip()


def _sweep() -> dict[str, str]:
    """Import every module in its own process; return the stderr of each failure."""
    modules = _module_names()
    assert len(modules) > 50, f"module discovery found only {len(modules)}"
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(_import_in_fresh_process, modules))
    return {module: stderr for module, code, stderr in results if code != 0}


@pytest.fixture(scope="module")
def failures() -> dict[str, str]:
    return _sweep()


def test_every_module_imports_on_its_own(failures: dict[str, str]) -> None:
    """No module depends on another having been imported first."""
    unexpected = {
        module: stderr for module, stderr in failures.items() if module not in KNOWN_CYCLES
    }
    assert not unexpected, "modules that do not import on their own:\n\n" + "\n\n".join(
        f"{module}:\n{stderr}" for module, stderr in sorted(unexpected.items())
    )


def test_known_cycles_are_still_cycles(failures: dict[str, str]) -> None:
    """An allowlisted cycle that now imports cleanly has to leave the allowlist."""
    fixed = sorted(module for module in KNOWN_CYCLES if module not in failures)
    assert not fixed, "these now import on their own; remove them from KNOWN_CYCLES: " + ", ".join(
        f"{module} ({KNOWN_CYCLES[module]})" for module in fixed
    )
