#!/usr/bin/env python3
"""Refuse a change that lets a risk-critical module go untested.

A whole-suite percentage is a poor gate: this suite is large, so a module can
lose most of its coverage without moving the total more than a rounding error.
The audit's finding was exactly that - "high test counts can conceal unexecuted
branches" - so the floors here are per module, and they are set on the modules
where an unexecuted branch is a security or durability problem rather than a
cosmetic one.

Each module carries **two** floors, on statements and on branches, because
either alone can be satisfied by a suite that is not exercising the code. A
statement measure marks an `if` executed as soon as it is reached, whatever the
condition did; `auth/blocks.py` reads 82% by statements and 50% by branches, so
half its conditions have only ever gone one way. A branch measure on its own is
trivially met by a module with three branches while most of its body never
runs.

Note that coverage.py's `percent_covered` is *not* branch coverage when
`--cov-branch` is on - it is a combined lines-and-branches ratio, 88.6% against
77.7% here. This reads the two fields apart, and refuses a report produced
without branch measurement rather than quietly checking the wrong number.

Each floor sits a point or two under what the module measures today. That is
deliberate: the gate is a ratchet against regression, not a target to chase, and
a floor pinned to the exact current number turns every harmless refactor into a
failed build.

Run it after a coverage run:

    cd backend && .venv/bin/pytest -q --cov=app --cov-branch \
        --cov-report=json:coverage.json
    python3 ../scripts/check-coverage.py coverage.json

(The default path assumes the repository root, which is where CI runs it from.)
"""
from __future__ import annotations

import json
from pathlib import Path
import sys


# The whole-suite floors. Broad, and deliberately not the headline numbers:
# they catch a change that deletes a lot of tests at once, and nothing subtler.
TOTAL_STATEMENT_FLOOR = 89.0
TOTAL_BRANCH_FLOOR = 76.0

# module -> (statement floor, branch floor). On this list because an
# unexercised path here is a way in, a way to lose data, or a way to serve
# traffic that cannot be served.
#
# Both numbers, because each alone has a blind spot. A statement floor calls an
# `if` covered the moment it is reached, whatever the condition did. A branch
# floor is trivially met by a module with three branches while most of its body
# goes unexecuted. Together they are hard to satisfy without actually running
# the code.
#
# The floors are a ratchet under where the suite stands, not a statement that
# this is enough. #505 raised five of them by covering the failure paths those
# modules exist to get right - blocks.py and room_codes.py from 50% and 60%
# branches to 100% - and the rest are still worth raising the same way.
MODULE_FLOORS: dict[str, tuple[float, float]] = {
    # Authentication and session handling: the front door.
    "app/auth/rate_limit.py": (90.0, 71.0),
    "app/auth/sessions.py": (90.0, 79.0),
    "app/auth/tokens.py": (88.0, 78.0),
    "app/auth/password.py": (92.0, 78.0),
    "app/auth/middleware.py": (95.0, 73.0),
    "app/auth/recovery.py": (94.0, 80.0),
    "app/auth/bans.py": (85.0, 73.0),
    "app/auth/blocks.py": (98.0, 98.0),
    # Privacy: export and deletion have to be right the first time.
    "app/auth/account_data.py": (81.0, 73.0),
    # Moderation is the safety surface, and its API is the staff-facing one.
    "app/api/moderation.py": (90.0, 73.0),
    # Abuse ceilings and payload validation - the untrusted-traffic boundary.
    "app/request_limits.py": (95.0, 89.0),
    "app/handlers/payloads.py": (92.0, 71.0),
    # Durability of what players drew, and the rules that bound it.
    "app/canvas_storage.py": (95.0, 85.0),
    "app/drawing_rules.py": (98.0, 98.0),
    # Deployment invariants and the readiness contract an orchestrator acts on.
    "app/deployment.py": (98.0, 98.0),
    "app/services/readiness.py": (96.0, 98.0),
    "app/services/shutdown.py": (88.0, 74.0),
    "app/db/__init__.py": (92.0, 78.0),
    # Room-code allocation: a collision is two rooms sharing an identity.
    "app/services/room_codes.py": (98.0, 98.0),
    # Who is online: a ledger, so an unbalanced path is an account listed as
    # reachable with nothing listening on it - and, from #529, a friend
    # request delivered into that silence.
    "app/services/presence.py": (99.0, 89.0),
    # Friendships decide who may enter a room they cannot name, and most of
    # what these modules do is refuse. An untested refusal is a way in.
    "app/services/friends.py": (92.0, 83.0),
    "app/services/friend_invites.py": (100.0, 100.0),
    "app/handlers/friends.py": (88.0, 85.0),
    "app/api/friends.py": (82.0, 72.0),
}


def _percentages(summary: dict, where: str) -> tuple[float, float]:
    """Pull statement and branch percentages out of one coverage summary.

    `percent_covered` is deliberately not used. Under `--cov-branch` it is a
    *combined* lines-and-branches ratio, which reads far higher than branch
    coverage alone - 88.6% against 77.7% for this suite - so a floor set
    against it would be checking something nobody asked for.
    """
    try:
        return (
            float(summary["percent_statements_covered"]),
            float(summary["percent_branches_covered"]),
        )
    except KeyError as missing:
        raise SystemExit(
            f"{where} has no {missing} - the report was produced without "
            "branch measurement. Re-run pytest with --cov-branch."
        )


def main() -> int:
    report_path = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/coverage.json")
    if not report_path.exists():
        print(f"No coverage report at {report_path}.", file=sys.stderr)
        print(
            "Run: cd backend && .venv/bin/pytest -q --cov=app --cov-branch "
            "--cov-report=json:coverage.json",
            file=sys.stderr,
        )
        return 1

    report = json.loads(report_path.read_text())
    measured = {
        path.replace("\\", "/"): info["summary"] for path, info in report["files"].items()
    }

    failures: list[str] = []

    statements, branches = _percentages(report["totals"], "the whole suite")
    if statements < TOTAL_STATEMENT_FLOOR:
        failures.append(
            f"whole suite {statements:.1f}% of statements is below the "
            f"{TOTAL_STATEMENT_FLOOR:.0f}% floor"
        )
    if branches < TOTAL_BRANCH_FLOOR:
        failures.append(
            f"whole suite {branches:.1f}% of branches is below the "
            f"{TOTAL_BRANCH_FLOOR:.0f}% floor"
        )

    for module, (statement_floor, branch_floor) in sorted(MODULE_FLOORS.items()):
        if module not in measured:
            # A rename must not silently retire a floor. If the module moved,
            # move its entry; if it is gone, delete the entry deliberately.
            failures.append(
                f"{module} is in the floor table but not in the coverage report "
                "- if it moved, move its entry too"
            )
            continue
        statements, branches = _percentages(measured[module], module)
        if statements < statement_floor:
            failures.append(
                f"{module} {statements:.1f}% of statements is below its "
                f"{statement_floor:.0f}% floor"
            )
        if branches < branch_floor:
            failures.append(
                f"{module} {branches:.1f}% of branches is below its "
                f"{branch_floor:.0f}% floor"
            )

    if failures:
        print("Coverage floors not met:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print(
            "\nAdd tests for the uncovered paths. Lower a floor only with a "
            "reason in the commit message.",
            file=sys.stderr,
        )
        return 1

    total_statements, total_branches = _percentages(report["totals"], "the whole suite")
    print(
        f"Coverage floors met: whole suite {total_statements:.1f}% of statements "
        f"and {total_branches:.1f}% of branches, "
        f"{len(MODULE_FLOORS)} risk-critical modules."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
