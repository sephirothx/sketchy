#!/usr/bin/env python3
"""Keep fixtures/wire_contract.json true, and say when a change needs a bump.

Three jobs, in the order CI runs them:

1. `--write` regenerates the fixture from the tree. Run it after any wire
   change; the checklist in docs/wire-protocol.md §11 says so.
2. Without flags, refuse a fixture that no longer matches the tree, printing
   the difference. A stale fixture is a wire change nobody wrote down.
3. `--base <git ref>` also reads the fixture as it was at that revision and
   diffs the two. A difference under the same PROTOCOL_VERSION is reported;
   with `--enforce` it fails. Comparing against the *base* rather than the
   working tree is what makes regenerating the fixture under the same number
   visible: the fixture can be rewritten, the base cannot.

Before launch the policy (§11) is regenerate-and-commit, with the bump
advisory - CI runs this without `--enforce` and the report is a warning. At
launch, add `--enforce` to the CI step and delete the pre-launch section.

Usage:
  backend/.venv/bin/python scripts/check-wire-contract.py --write
  backend/.venv/bin/python scripts/check-wire-contract.py
  backend/.venv/bin/python scripts/check-wire-contract.py --base origin/main [--enforce]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.wire_contract import FIXTURE_PATH, build_contract, bump_missing, diff_contracts, dumps  # noqa: E402

RELATIVE = FIXTURE_PATH.relative_to(ROOT).as_posix()


def base_contract(ref: str) -> dict | None:
    try:
        text = subprocess.run(
            ["git", "show", f"{ref}:{RELATIVE}"], capture_output=True, text=True, check=True, cwd=ROOT
        ).stdout
    except subprocess.CalledProcessError:
        return None
    return json.loads(text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="regenerate the fixture from the tree")
    parser.add_argument("--base", metavar="REF", help="git revision to compare the fixture against")
    parser.add_argument("--enforce", action="store_true", help="fail, not warn, on an unbumped change against --base")
    args = parser.parse_args()

    current = build_contract()
    if args.write:
        FIXTURE_PATH.write_text(dumps(current))
        print(f"wrote {RELATIVE} (protocol {current['protocolVersion']})")
        return 0

    status = 0
    tracked = json.loads(FIXTURE_PATH.read_text()) if FIXTURE_PATH.exists() else {}
    stale = diff_contracts(tracked, current) or (tracked.get("protocolVersion") != current["protocolVersion"])
    if stale:
        print(f"{RELATIVE} is stale; regenerate it with `scripts/check-wire-contract.py --write`:")
        for line in diff_contracts(tracked, current):
            print("  " + line)
        if tracked.get("protocolVersion") != current["protocolVersion"]:
            print(f"  ~ protocolVersion: {tracked.get('protocolVersion')} -> {current['protocolVersion']}")
        status = 1

    if args.base:
        base = base_contract(args.base)
        if base is None:
            print(f"no {RELATIVE} at {args.base}; nothing to compare against")
        else:
            changes = diff_contracts(base, current)
            bumped = current["protocolVersion"] != base.get("protocolVersion")
            if not changes and not bumped:
                print(f"socket contract unchanged since {args.base}")
            elif bumped:
                print(f"socket contract changed since {args.base}; PROTOCOL_VERSION "
                      f"{base.get('protocolVersion')} -> {current['protocolVersion']} ({len(changes)} change(s))")
                for line in changes:
                    print("  " + line)
            elif bump_missing(base, current):
                severity = "error" if args.enforce else "warning"
                print(f"::{severity}::socket contract changed since {args.base} without a PROTOCOL_VERSION bump "
                      f"(still {current['protocolVersion']}); {len(changes)} change(s):")
                for line in changes:
                    print("  " + line)
                if args.enforce:
                    status = 1
    return status


if __name__ == "__main__":
    if os.environ.get("GITHUB_ACTIONS") and "--base" not in sys.argv:
        print("::notice::run with --base <ref> in CI to compare against the base revision")
    raise SystemExit(main())
