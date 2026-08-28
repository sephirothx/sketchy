"""The coverage gate must fail when it is supposed to.

A gate is only worth its runtime if its failure paths work, and those are
exactly the paths a green build never exercises: running it against today's
passing report proves only that today's report passes. These tests drive the
refusals directly, the way `test_repo_artifacts.py` does for the artifact scan.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
COVERAGE_GATE = REPO_ROOT / "scripts" / "check-coverage.py"


def load_gate(path: Path):
    """Import a gate script by path, to read the table it enforces."""
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_gate(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


# --- coverage floors --------------------------------------------------------


def _coverage_report(
    tmp_path: Path,
    files: dict[str, tuple[float, float]],
    total: tuple[float, float] = (100.0, 100.0),
    *,
    with_branches: bool = True,
) -> Path:
    def summary(statements: float, branches: float) -> dict:
        # percent_covered is coverage.py's *combined* ratio under --cov-branch.
        # Deliberately set high here: a gate reading it instead of the two
        # fields apart would pass these fixtures.
        block = {"percent_covered": 99.0, "percent_statements_covered": statements}
        if with_branches:
            block["percent_branches_covered"] = branches
        return block

    report = {
        "totals": summary(*total),
        "files": {name: {"summary": summary(*pair)} for name, pair in files.items()},
    }
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(report))
    return path


def _every_floor_met(
    tmp_path: Path, overrides: dict[str, tuple[float, float]] | None = None, **kwargs
) -> Path:
    """A report where every gated module sits comfortably above both floors."""
    gate = load_gate(COVERAGE_GATE)
    files = {module: (100.0, 100.0) for module in gate.MODULE_FLOORS}
    files.update(overrides or {})
    return _coverage_report(tmp_path, files, **kwargs)


def test_a_passing_report_passes(tmp_path):
    result = run_gate(COVERAGE_GATE, str(_every_floor_met(tmp_path)))
    assert result.returncode == 0, result.stderr


def test_a_module_below_its_statement_floor_fails(tmp_path):
    report = _every_floor_met(tmp_path, {"app/auth/rate_limit.py": (40.0, 100.0)})
    result = run_gate(COVERAGE_GATE, str(report))
    assert result.returncode == 1
    assert "app/auth/rate_limit.py" in result.stderr
    assert "of statements is below" in result.stderr


def test_a_module_below_only_its_branch_floor_fails(tmp_path):
    """The case the combined ratio hides: statements fine, conditions not.

    `percent_covered` in the fixture is 99%, so a gate reading that field
    instead of the two apart would call this green.
    """
    report = _every_floor_met(tmp_path, {"app/auth/recovery.py": (100.0, 20.0)})
    result = run_gate(COVERAGE_GATE, str(report))
    assert result.returncode == 1
    assert "app/auth/recovery.py" in result.stderr
    assert "of branches is below" in result.stderr


def test_a_report_without_branch_measurement_fails(tmp_path):
    """A report from a plain --cov run must not be checked as if it had them."""
    report = _every_floor_met(tmp_path, with_branches=False)
    result = run_gate(COVERAGE_GATE, str(report))
    assert result.returncode != 0
    assert "--cov-branch" in result.stderr


def test_a_renamed_module_fails_rather_than_retiring_its_floor(tmp_path):
    """Otherwise `git mv` is a way to delete a gate without saying so."""
    gate = load_gate(COVERAGE_GATE)
    files = {module: (100.0, 100.0) for module in gate.MODULE_FLOORS}
    files["app/auth/rate_limiter.py"] = files.pop("app/auth/rate_limit.py")
    report = _coverage_report(tmp_path, files)

    result = run_gate(COVERAGE_GATE, str(report))
    assert result.returncode == 1
    assert "not in the coverage report" in result.stderr


@pytest.mark.parametrize(
    ("total", "expected"),
    [((12.0, 100.0), "of statements"), ((100.0, 12.0), "of branches")],
)
def test_a_whole_suite_collapse_fails(total, expected, tmp_path):
    gate = load_gate(COVERAGE_GATE)
    files = {module: (100.0, 100.0) for module in gate.MODULE_FLOORS}
    report = _coverage_report(tmp_path, files, total=total)

    result = run_gate(COVERAGE_GATE, str(report))
    assert result.returncode == 1
    assert "whole suite" in result.stderr
    assert expected in result.stderr


def test_a_missing_report_fails_rather_than_passing_vacuously(tmp_path):
    """A gate that treats "no data" as "no problem" is worse than no gate."""
    result = run_gate(COVERAGE_GATE, str(tmp_path / "absent.json"))
    assert result.returncode == 1
    assert "No coverage report" in result.stderr


def test_the_floors_are_a_ratchet_not_a_wish():
    """Every floor must sit at or under what the module measures today.

    A floor above current coverage is a build that cannot go green, and one
    far below it is a gate that cannot catch anything.
    """
    gate = load_gate(COVERAGE_GATE)
    assert gate.MODULE_FLOORS, "the floor table must not be empty"
    for module, floors in gate.MODULE_FLOORS.items():
        assert len(floors) == 2, f"{module} needs a statement and a branch floor"
        for floor in floors:
            assert 0 < floor <= 100, f"{module} has an impossible floor"
