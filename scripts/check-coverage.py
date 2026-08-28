#!/usr/bin/env python3
"""Refuse a change that lets a risk-critical module go untested.

A whole-suite percentage is a poor gate: this suite is large, so a module can
lose most of its coverage without moving the total more than a rounding error.
The audit's finding was exactly that - "high test counts can conceal unexecuted
branches" - so the floors here are per module, and they are set on the modules
where an unexecuted branch is a security or durability problem rather than a
cosmetic one.

The numbers are **branch** coverage, which is the half of that finding a
statement count cannot see: a statement measure marks an `if` executed as soon
as it is reached, whatever the condition did. Every module here reads lower
under branch coverage than under statements, and `auth/recovery.py` reads six
points lower - six points of conditions nothing exercises, which a statement
floor would have called covered.

Each floor sits a point or two under what the module measures today. That is
deliberate: the gate is a ratchet against regression, not a target to chase, and
a floor pinned to the exact current number turns every harmless refactor into a
failed build.

Run it after a coverage run:

    cd backend && .venv/bin/pytest -q --cov=app --cov-branch \
        --cov-report=json:coverage.json
    python3 ../scripts/check-coverage.py backend/coverage.json
"""
from __future__ import annotations

import json
from pathlib import Path
import sys


# The whole-suite floor. Broad, and deliberately not the headline number: it
# catches a change that deletes a lot of tests at once, and nothing subtler.
TOTAL_FLOOR = 86.0

# module -> floor. On this list because an unexercised branch here is a way in,
# a way to lose data, or a way to serve traffic that cannot be served.
MODULE_FLOORS: dict[str, float] = {
    # Authentication and session handling: the front door.
    "app/auth/rate_limit.py": 86.0,
    "app/auth/sessions.py": 88.0,
    "app/auth/tokens.py": 86.0,
    "app/auth/password.py": 90.0,
    "app/auth/middleware.py": 92.0,
    "app/auth/recovery.py": 82.0,
    "app/auth/bans.py": 84.0,
    "app/auth/blocks.py": 77.0,
    # Privacy: export and deletion have to be right the first time.
    "app/auth/account_data.py": 77.0,
    # Moderation is the safety surface, and its API is the staff-facing one.
    "app/api/moderation.py": 83.0,
    # Abuse ceilings and payload validation - the untrusted-traffic boundary.
    "app/request_limits.py": 94.0,
    "app/handlers/payloads.py": 89.0,
    # Durability of what players drew, and the rules that bound it.
    "app/canvas_storage.py": 93.0,
    "app/drawing_rules.py": 98.0,
    # Deployment invariants and the readiness contract an orchestrator acts on.
    "app/deployment.py": 98.0,
    "app/services/readiness.py": 96.0,
    "app/services/shutdown.py": 86.0,
    "app/db/__init__.py": 89.0,
    # Room-code allocation: a collision is two rooms sharing an identity.
    "app/services/room_codes.py": 89.0,
}


def main() -> int:
    report_path = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/coverage.json")
    if not report_path.exists():
        print(f"No coverage report at {report_path}.", file=sys.stderr)
        print(
            "Run: cd backend && .venv/bin/pytest -q --cov=app "
            "--cov-report=json:coverage.json",
            file=sys.stderr,
        )
        return 1

    report = json.loads(report_path.read_text())
    measured = {
        path.replace("\\", "/"): info["summary"]["percent_covered"]
        for path, info in report["files"].items()
    }

    failures: list[str] = []

    total = report["totals"]["percent_covered"]
    if total < TOTAL_FLOOR:
        failures.append(f"whole suite {total:.1f}% is below the {TOTAL_FLOOR:.0f}% floor")

    for module, floor in sorted(MODULE_FLOORS.items()):
        if module not in measured:
            # A rename must not silently retire a floor. If the module moved,
            # move its entry; if it is gone, delete the entry deliberately.
            failures.append(
                f"{module} is in the floor table but not in the coverage report "
                "- if it moved, move its entry too"
            )
            continue
        actual = measured[module]
        if actual < floor:
            failures.append(
                f"{module} {actual:.1f}% is below its {floor:.0f}% floor"
            )

    if failures:
        print("Coverage floors not met:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print(
            "\nAdd tests for the uncovered branches. Lower a floor only with a "
            "reason in the commit message.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Coverage floors met: whole suite {total:.1f}% "
        f"(floor {TOTAL_FLOOR:.0f}%), {len(MODULE_FLOORS)} risk-critical modules."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
