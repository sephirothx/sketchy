#!/usr/bin/env python3
"""Rebuild backend/tests/e2e_durations.json from CI's JUnit reports.

The E2E shards are balanced by how long each case took last time (see
backend/tests/e2e_sharding.py). Refresh the file when the split drifts - a
shard finishing well after the others - from the reports a run uploaded:

    gh run download <run-id> -p 'e2e-test-results-*' -D /tmp/e2e-junit
    python3 scripts/update-e2e-durations.py /tmp/e2e-junit/*/e2e.xml

Every report of one run together covers the suite once; the file is rebuilt
from what they hold, so a test that no longer exists drops out.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
TARGET = BACKEND / "tests" / "e2e_durations.json"


def nodeid(classname: str, name: str) -> str:
    """`tests.e2e.test_x[.Class]` + `test_y[param]` back to pytest's node ID."""
    parts = classname.split(".")
    for cut in range(len(parts), 0, -1):
        module = "/".join(parts[:cut]) + ".py"
        if (BACKEND / module).exists():
            return "::".join([module, *parts[cut:], name])
    raise SystemExit(f"no module under backend/ for JUnit classname {classname!r}")


def main(paths: list[str]) -> int:
    if not paths:
        print(__doc__, file=sys.stderr)
        return 2
    durations: dict[str, float] = {}
    for path in paths:
        for case in ET.parse(path).iter("testcase"):
            if case.find("skipped") is not None:
                continue
            key = nodeid(case.get("classname", ""), case.get("name", ""))
            durations[key] = max(durations.get(key, 0.0), float(case.get("time", "0")))
    TARGET.write_text(
        json.dumps({k: round(v, 1) for k, v in sorted(durations.items())}, indent=1) + "\n"
    )
    print(f"{len(durations)} cases -> {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
