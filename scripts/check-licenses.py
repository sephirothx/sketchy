#!/usr/bin/env python3
"""Refuse a dependency whose licence this project cannot ship under.

Reads the CycloneDX SBOMs the build publishes, rather than walking the
dependency tree a second way: the SBOM is the artifact that answers "what is in
this build", so making it the input to the policy keeps one description of what
ships instead of two that can disagree.

**The policy is an allowlist, and it fails closed.** A denylist only refuses
the terms somebody thought to name, so `Elastic-2.0` - source-available, and
exactly what this gate exists to catch - would sail through one. An unfamiliar
identifier here means nobody has looked at it yet, which is a reason to stop,
not a reason to continue. Adding a licence to `ALLOWED` is a deliberate act.

SPDX expressions are parsed and evaluated rather than pattern-matched. A dual
licence is acceptable when *some* choice it offers is acceptable, which is what
the offer means; `AND` has to be satisfied on every side. So `MIT OR GPL-3.0`
passes on MIT, while `(MIT OR GPL-3.0) AND SSPL-1.0` does not - every way of
taking it still lands on SSPL.

    python3 scripts/check-licenses.py sbom-backend.json sbom-frontend.json
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys


# Permissive, weak-copyleft, and public-domain-equivalent terms this project
# can ship. LGPL is here deliberately: dependencies are used unmodified and
# dynamically, which is what its linking exception is for. Strong copyleft
# (GPL, AGPL) and source-available terms (SSPL, BUSL, Elastic) are absent, and
# absence is what refuses them - there is no list of villains to keep current.
ALLOWED = {
    "0BSD",
    "APACHE-2.0",
    "ARTISTIC-2.0",
    "BLUEOAK-1.0.0",
    "BSD-2-CLAUSE",
    "BSD-3-CLAUSE",
    "BSD-3-CLAUSE-CLEAR",
    "CC0-1.0",
    "CC-BY-4.0",
    "ISC",
    "LGPL-2.0-ONLY",
    "LGPL-2.0-OR-LATER",
    "LGPL-2.1-ONLY",
    "LGPL-2.1-OR-LATER",
    "LGPL-3.0-ONLY",
    "LGPL-3.0-OR-LATER",
    "MIT",
    "MIT-0",
    "MPL-2.0",
    "OFL-1.1",
    "PSF-2.0",
    "PYTHON-2.0",
    "UNLICENSE",
    "ZLIB",
}

# Package metadata does not always carry an SPDX id. These are the
# classifier and free-text spellings seen in practice, each mapped to what it
# actually is. Anything not here fails closed and needs a look.
SPELLINGS = {
    "APACHE SOFTWARE LICENSE": "APACHE-2.0",
    "APACHE 2.0": "APACHE-2.0",
    "APACHE LICENSE 2.0": "APACHE-2.0",
    "BSD LICENSE": "BSD-3-CLAUSE",
    "BSD": "BSD-3-CLAUSE",
    "MIT LICENSE": "MIT",
    "THE MIT LICENSE": "MIT",
    "ISC LICENSE (ISCL)": "ISC",
    "ISC LICENSE": "ISC",
    "MOZILLA PUBLIC LICENSE 2.0 (MPL 2.0)": "MPL-2.0",
    "PYTHON SOFTWARE FOUNDATION LICENSE": "PYTHON-2.0",
    "GNU LESSER GENERAL PUBLIC LICENSE V2 OR LATER (LGPLV2+)": "LGPL-2.0-OR-LATER",
    "GNU LESSER GENERAL PUBLIC LICENSE V3 (LGPLV3)": "LGPL-3.0-ONLY",
    "SIL OPEN FONT LICENSE 1.1": "OFL-1.1",
}

# Components that declare no licence at all, each one looked at deliberately.
ACKNOWLEDGED_WITHOUT_LICENCE: set[str] = set()


class SpdxError(ValueError):
    """An expression that cannot be parsed. Unparseable means unreviewed."""


def normalise(text: str) -> str:
    """Reduce one licence identifier to the form the allowlist is written in."""
    cleaned = text.strip().upper()
    # A trailing "+" means "or later", which SPDX also spells "-OR-LATER".
    if cleaned.endswith("+"):
        without = cleaned[:-1]
        cleaned = (
            without if without.endswith("-OR-LATER") else f"{without}-OR-LATER"
        )
    # Trove classifiers arrive as "License :: OSI Approved :: <the name>".
    if "::" in cleaned:
        cleaned = cleaned.rsplit("::", 1)[-1].strip()
    return SPELLINGS.get(cleaned, cleaned)


def _tokenise(expression: str) -> list[str]:
    tokens = re.findall(r"\(|\)|[^\s()]+", expression)
    if not tokens:
        raise SpdxError("empty expression")
    return tokens


def _evaluate(tokens: list[str], position: int = 0) -> tuple[bool, int]:
    """Evaluate an SPDX expression to "this project may ship it".

    OR is satisfied by either side, because the licensor is offering a choice.
    AND must hold on both, because every named term applies at once. AND binds
    tighter than OR, per the SPDX grammar.
    """
    or_result = False
    and_result = True
    operator = "AND"

    while position < len(tokens):
        token = tokens[position]
        upper = token.upper()

        if upper == ")":
            break

        if upper in ("AND", "OR"):
            if upper == "OR":
                or_result = or_result or and_result
                and_result = True
            operator = upper
            position += 1
            continue

        if upper == "(":
            value, position = _evaluate(tokens, position + 1)
            if position >= len(tokens) or tokens[position] != ")":
                raise SpdxError("unbalanced parenthesis")
            position += 1
        else:
            # "Apache-2.0 WITH LLVM-exception": an exception only ever grants
            # extra permission, so the base licence decides.
            value = normalise(token) in ALLOWED
            position += 1
            if position + 1 < len(tokens) and tokens[position].upper() == "WITH":
                position += 2

        and_result = and_result and value if operator == "AND" else value
        operator = "AND"

    return (or_result or and_result), position


def is_allowed(text: str) -> bool:
    """Whether one licence string - id, name, or SPDX expression - is shippable."""
    tokens = _tokenise(text)
    # A bare identifier can contain spaces ("BSD License"); only treat the
    # string as an expression when it actually uses the grammar.
    if not any(t.upper() in ("AND", "OR", "WITH", "(", ")") for t in tokens):
        return normalise(text) in ALLOWED
    allowed, position = _evaluate(tokens)
    if position != len(tokens):
        raise SpdxError(f"trailing tokens in {text!r}")
    return allowed


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
            # A component may declare several licences; any one that this
            # project may ship under is enough, since the licensee chooses.
            verdicts: list[str] = []
            for text in strings:
                try:
                    if is_allowed(text):
                        break
                    verdicts.append(f"{text} (not on the allowlist)")
                except SpdxError as error:
                    verdicts.append(f"{text} (unparseable: {error})")
            else:
                refused.append(f"{name}: " + "; ".join(verdicts))

    if refused or undeclared:
        print("Licence policy not met:", file=sys.stderr)
        for line in sorted(refused):
            print(f"  - refused: {line}", file=sys.stderr)
        for line in sorted(undeclared):
            print(f"  - no declared licence: {line}", file=sys.stderr)
        print(
            "\nThis policy is an allowlist, so an unfamiliar identifier lands here "
            "too. Look at the terms, then either add the licence to ALLOWED (or its "
            "spelling to SPELLINGS), or add the component to "
            "ACKNOWLEDGED_WITHOUT_LICENCE - deliberately, in a commit that says why.",
            file=sys.stderr,
        )
        return 1

    print(f"Licence policy met: {counted} components across {len(paths)} SBOMs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
