"""The CI gates that live in `scripts/` must fail when they are supposed to.

A gate is only worth its runtime if its failure paths work, and those paths are
exactly the ones a green build never exercises: running the licence checker
against today's dependencies proves only that today's dependencies pass. These
tests drive the refusals directly, the way `test_repo_artifacts.py` does for
the artifact scan.
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
LICENCE_GATE = REPO_ROOT / "scripts" / "check-licenses.py"


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


def _coverage_report(tmp_path: Path, files: dict[str, float], total: float) -> Path:
    report = {
        "totals": {"percent_covered": total},
        "files": {
            name: {"summary": {"percent_covered": pct}} for name, pct in files.items()
        },
    }
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(report))
    return path


def _every_floor_met(tmp_path: Path, **overrides: float) -> Path:
    """A report where every gated module sits comfortably above its floor."""
    gate = load_gate(COVERAGE_GATE)
    files = {module: 100.0 for module in gate.MODULE_FLOORS}
    files.update(overrides)
    return _coverage_report(tmp_path, files, total=100.0)


def test_a_passing_report_passes(tmp_path):
    result = run_gate(COVERAGE_GATE, str(_every_floor_met(tmp_path)))
    assert result.returncode == 0, result.stderr


def test_a_module_below_its_floor_fails(tmp_path):
    report = _every_floor_met(tmp_path, **{"app/auth/rate_limit.py": 40.0})
    result = run_gate(COVERAGE_GATE, str(report))
    assert result.returncode == 1
    assert "app/auth/rate_limit.py" in result.stderr
    assert "below its" in result.stderr


def test_a_renamed_module_fails_rather_than_retiring_its_floor(tmp_path):
    """Otherwise `git mv` is a way to delete a gate without saying so."""
    gate = load_gate(COVERAGE_GATE)
    files = {module: 100.0 for module in gate.MODULE_FLOORS}
    files["app/auth/rate_limiter.py"] = files.pop("app/auth/rate_limit.py")
    report = _coverage_report(tmp_path, files, total=100.0)

    result = run_gate(COVERAGE_GATE, str(report))
    assert result.returncode == 1
    assert "not in the coverage report" in result.stderr


def test_a_whole_suite_collapse_fails(tmp_path):
    gate = load_gate(COVERAGE_GATE)
    files = {module: 100.0 for module in gate.MODULE_FLOORS}
    report = _coverage_report(tmp_path, files, total=12.0)

    result = run_gate(COVERAGE_GATE, str(report))
    assert result.returncode == 1
    assert "whole suite" in result.stderr


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
    for module, floor in gate.MODULE_FLOORS.items():
        assert 0 < floor <= 100, f"{module} has an impossible floor"


# --- licence policy ---------------------------------------------------------


def _sbom(tmp_path: Path, components: list[dict], name: str = "sbom.json") -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": components}
        )
    )
    return path


def _with_licence(**entry) -> dict:
    return {"name": "some-package", "licenses": [entry]}


@pytest.mark.parametrize(
    "identifier",
    ["MIT", "MIT-0", "Apache-2.0", "BSD-3-Clause", "MPL-2.0", "OFL-1.1", "ISC"],
)
def test_a_permissive_licence_passes(identifier, tmp_path):
    sbom = _sbom(tmp_path, [_with_licence(license={"id": identifier})])
    assert run_gate(LICENCE_GATE, str(sbom)).returncode == 0


@pytest.mark.parametrize(
    "identifier",
    [
        "AGPL-3.0-only",
        "GPL-3.0-or-later",
        "GPL-2.0",
        "SSPL-1.0",
        "BUSL-1.1",
        # Source-available, and on no denylist anybody would think to write.
        # This is the case an allowlist exists for.
        "Elastic-2.0",
        "PolyForm-Noncommercial-1.0.0",
    ],
)
def test_a_licence_this_project_cannot_ship_fails(identifier, tmp_path):
    sbom = _sbom(tmp_path, [_with_licence(license={"id": identifier})])
    result = run_gate(LICENCE_GATE, str(sbom))
    assert result.returncode == 1, f"{identifier} was allowed"
    assert identifier in result.stderr


@pytest.mark.parametrize(
    "identifier",
    ["LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-2.1+"],
)
def test_weak_copyleft_is_allowed(identifier, tmp_path):
    """Used unmodified and dynamically, which is what the exception is for."""
    sbom = _sbom(tmp_path, [_with_licence(license={"id": identifier})])
    assert run_gate(LICENCE_GATE, str(sbom)).returncode == 0, identifier


@pytest.mark.parametrize(
    ("expression", "shippable"),
    [
        ("MIT OR GPL-3.0-only", True),
        ("GPL-3.0-only OR MIT", True),
        ("MIT AND PSF-2.0", True),
        ("MIT AND GPL-3.0-only", False),
        # Every way of taking this one still lands on SSPL.
        ("(MIT OR GPL-3.0-only) AND SSPL-1.0", False),
        ("(MIT OR GPL-3.0-only) AND Apache-2.0", True),
        ("SSPL-1.0 OR (MIT AND Apache-2.0)", True),
        ("Apache-2.0 WITH LLVM-exception", True),
        ("GPL-3.0-only WITH Classpath-exception-2.0", False),
    ],
)
def test_an_spdx_expression_is_evaluated_rather_than_pattern_matched(
    expression, shippable, tmp_path
):
    sbom = _sbom(tmp_path, [_with_licence(expression=expression)])
    result = run_gate(LICENCE_GATE, str(sbom))
    assert (result.returncode == 0) is shippable, f"{expression}: {result.stderr}"


def test_an_undeclared_licence_fails(tmp_path):
    sbom = _sbom(tmp_path, [{"name": "mystery", "licenses": []}])
    result = run_gate(LICENCE_GATE, str(sbom))
    assert result.returncode == 1
    assert "no declared licence" in result.stderr


def test_an_unparseable_expression_fails_closed(tmp_path):
    sbom = _sbom(tmp_path, [_with_licence(expression="MIT AND (Apache-2.0")])
    result = run_gate(LICENCE_GATE, str(sbom))
    assert result.returncode == 1


def test_a_classifier_spelling_is_understood(tmp_path):
    """cyclonedx-py emits Trove classifiers for packages without an SPDX id."""
    sbom = _sbom(
        tmp_path,
        [_with_licence(license={"name": "License :: OSI Approved :: MIT License"})],
    )
    assert run_gate(LICENCE_GATE, str(sbom)).returncode == 0


def test_a_missing_sbom_fails_rather_than_passing_vacuously(tmp_path):
    result = run_gate(LICENCE_GATE, str(tmp_path / "absent.json"))
    assert result.returncode == 1
    assert "No SBOM" in result.stderr


def test_several_sboms_are_all_checked(tmp_path):
    good = _sbom(tmp_path, [_with_licence(license={"id": "MIT"})], "good.json")
    bad = _sbom(tmp_path, [_with_licence(license={"id": "AGPL-3.0-only"})], "bad.json")
    result = run_gate(LICENCE_GATE, str(good), str(bad))
    assert result.returncode == 1
    assert "AGPL" in result.stderr
