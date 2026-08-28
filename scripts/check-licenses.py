#!/usr/bin/env python3
"""Refuse a dependency whose licence this project cannot ship under.

Reads the CycloneDX SBOMs the build publishes, rather than walking the
dependency tree a second way: the SBOM is the artifact that answers "what is in
this build", so making it the input to the policy keeps one description of what
ships instead of two that can disagree.

**The policy is an allowlist, and it fails closed** - on an unfamiliar
identifier, on an expression it cannot parse, and on an SBOM that lists nothing
at all. A denylist only refuses
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


# The words the grammar spends on structure. None of them can stand in for a
# licence or an exception name.
RESERVED = frozenset({"AND", "OR", "WITH", "(", ")"})


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


class _Parser:
    """A recursive-descent parser for the SPDX expression grammar.

        expression     := and-expression (OR and-expression)*
        and-expression := atom (AND atom)*
        atom           := IDENTIFIER [WITH IDENTIFIER] | "(" expression ")"

    It validates the grammar rather than scanning for operators, because an
    evaluator that never tracks whether it wants an operand next will happily
    read `MIT OR`, `MIT OR OR GPL-3.0-only`, and `()` as true. Malformed means
    unreviewed, and unreviewed has to fail.
    """

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.position = 0

    def peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self, expecting: str = "a licence") -> str:
        token = self.peek()
        if token is None:
            raise SpdxError(f"expression ends where {expecting} was expected")
        self.position += 1
        return token

    def parse(self) -> bool:
        value = self.parse_or()
        if self.position != len(self.tokens):
            raise SpdxError(f"unexpected {self.tokens[self.position]!r}")
        return value

    def parse_or(self) -> bool:
        # An offered choice: acceptable if either side is.
        value = self.parse_and()
        while (token := self.peek()) is not None and token.upper() == "OR":
            self.take()
            # Parsed first, then combined, so validation cannot be
            # short-circuited away by an operand that already decided it.
            value = self.parse_and() or value
        return value

    def parse_and(self) -> bool:
        # Every named term applies at once: acceptable only if all sides are.
        value = self.parse_atom()
        while (token := self.peek()) is not None and token.upper() == "AND":
            self.take()
            value = self.parse_atom() and value
        return value

    def parse_atom(self) -> bool:
        token = self.take()
        upper = token.upper()

        if upper == "(":
            value = self.parse_or()
            closing = self.take("a closing parenthesis")
            if closing != ")":
                raise SpdxError(f"expected ')', found {closing!r}")
            return value

        if upper in RESERVED:
            raise SpdxError(f"expected a licence, found {token!r}")

        value = normalise(token) in ALLOWED

        # "Apache-2.0 WITH LLVM-exception": an exception only ever grants extra
        # permission, so the base licence decides - but it has to be an actual
        # name. Without this check `Apache-2.0 WITH OR` consumes the operator
        # as the exception and comes out true.
        if (following := self.peek()) is not None and following.upper() == "WITH":
            self.take()
            exception = self.take("an exception name")
            if exception.upper() in RESERVED:
                raise SpdxError(
                    f"expected an exception name, found {exception!r}"
                )

        return value


def is_allowed(text: str) -> bool:
    """Whether one licence string - id, name, or SPDX expression - is shippable.

    The whole string is resolved as a single name **first**, because the names
    people actually write are full of the grammar's own words: "GNU Lesser
    General Public License v2 or later (LGPLv2+)" has an `or` and a pair of
    brackets in it, and "Mozilla Public License 2.0 (MPL 2.0)" has brackets
    too. Parsing before looking those up refuses every one of them.
    """
    if normalise(text) in ALLOWED:
        return True

    tokens = _tokenise(text)
    # Not a name this project knows. If it does not use the grammar either,
    # there is nothing left to try, and unrecognised fails closed.
    if not any(token.upper() in RESERVED for token in tokens):
        return False
    return _Parser(tokens).parse()


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
        components = document.get("components")
        # A generator that produced nothing, or produced a shape this does not
        # understand, must not read as "no problems found". That is the same
        # silent pass as a missing file, arriving by a different route.
        if not isinstance(components, list) or not components:
            print(
                f"{path} lists no components. An SBOM with nothing in it cannot "
                "clear a licence policy - check that the generator actually ran.",
                file=sys.stderr,
            )
            return 1
        for component in components:
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
