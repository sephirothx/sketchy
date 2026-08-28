#!/usr/bin/env python3
"""Refuse a dependency whose licence this project cannot ship under.

Reads one or more CycloneDX SBOMs - the ones the SBOM job generates - rather
than scanning the dependency tree a second way. The SBOM is the artifact the
audit asked for, so making it the input to the policy keeps one description of
what ships instead of two that can disagree.

Two things fail a build:

- **Strong copyleft or source-available terms.** The frontend is compiled into
  a bundle served to every player, so an AGPL, GPL, SSPL, or BUSL dependency
  is a licensing obligation this project is not set up to meet. LGPL is *not*
  in that set: it is used unmodified and dynamically, which is what its
  linking exception is for.
- **No declared licence at all.** Not because absence is proof of a problem,
  but because it means nobody has looked. Add the component to
  ``ACKNOWLEDGED_WITHOUT_LICENCE`` once someone has.

A dual licence that offers a permissive option (``MIT OR GPL-2.0``) passes on
the permissive one, which is the whole point of the offer.

    python3 scripts/check-licenses.py sbom-backend.json sbom-frontend.json
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys


DENIED = (
    (re.compile(r"\bAGPL|AFFERO", re.I), "Affero GPL"),
    (re.compile(r"\bSSPL|SERVER SIDE PUBLIC", re.I), "Server Side Public License"),
    (re.compile(r"\bBUSL|BUSINESS SOURCE", re.I), "Business Source License"),
    (re.compile(r"COMMONS CLAUSE", re.I), "Commons Clause"),
    (re.compile(r"\bEUPL", re.I), "European Union Public Licence"),
    (re.compile(r"\bOSL-|OPEN SOFTWARE LICENSE", re.I), "Open Software License"),
    # Plain GPL only. The negative lookbehind keeps LGPL out, and the phrase
    # form is matched separately so "GNU General Public License" is caught
    # while "GNU Lesser General Public License" is not.
    (re.compile(r"(?<![LA])GPL", re.I), "GPL"),
    (re.compile(r"(?<!LESSER )GNU GENERAL PUBLIC", re.I), "GPL"),
)

PERMISSIVE = re.compile(
    r"\bMIT\b|\bBSD\b|APACHE|\bISC\b|\bMPL\b|MOZILLA|PYTHON-2|\bPSF\b|"
    r"\bZLIB\b|UNLICENSE|\bCC0\b|BLUEOAK|\bOFL\b|OPEN FONT|\bLGPL\b|LESSER",
    re.I,
)

# Components known to declare no licence, each one looked at deliberately.
ACKNOWLEDGED_WITHOUT_LICENCE: set[str] = set()


def _licence_strings(component: dict) -> list[str]:
    found: list[str] = []
    for entry in component.get("licenses", []):
        licence = entry.get("license", {})
        for key in ("id", "name"):
            if licence.get(key):
                found.append(str(licence[key]))
        if entry.get("expression"):
            found.append(str(entry["expression"]))
    return found


def _verdict(text: str) -> str | None:
    """The reason this licence string is refused, or None if it is fine."""
    # A dual licence offering something permissive is taken on that offer.
    if " OR " in text.upper() and PERMISSIVE.search(text):
        return None
    for pattern, name in DENIED:
        if pattern.search(text):
            return name
    return None


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print("usage: check-licenses.py <sbom.json> [<sbom.json> ...]", file=sys.stderr)
        return 1

    refused: list[str] = []
    undeclared: list[str] = []
    counted = 0

    for path in paths:
        if not path.exists():
            print(f"No SBOM at {path}.", file=sys.stderr)
            return 1
        document = json.loads(path.read_text())
        for component in document.get("components", []):
            counted += 1
            name = component.get("purl") or component.get("name", "(unnamed)")
            strings = _licence_strings(component)
            if not strings:
                if name not in ACKNOWLEDGED_WITHOUT_LICENCE:
                    undeclared.append(name)
                continue
            for text in strings:
                reason = _verdict(text)
                if reason is not None:
                    refused.append(f"{name}: {text} ({reason})")
                    break

    if refused or undeclared:
        print("Licence policy not met:", file=sys.stderr)
        for line in sorted(refused):
            print(f"  - refused: {line}", file=sys.stderr)
        for line in sorted(undeclared):
            print(f"  - no declared licence: {line}", file=sys.stderr)
        if undeclared:
            print(
                "\nLook at each undeclared component and, if it is fine, add it to "
                "ACKNOWLEDGED_WITHOUT_LICENCE in this script.",
                file=sys.stderr,
            )
        return 1

    print(f"Licence policy met: {counted} components across {len(paths)} SBOMs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
