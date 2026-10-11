"""Hypothesis settings shared by the generated-input suites (#1456).

Two profiles. On every run - CI and a plain local `pytest` - generation is
**derandomized**: the same inputs every time, so a red build is a fact about the
change and not about the draw, which is the convention the seeded property tests
already keep (`test_live_drawing_properties.py`). No example database either, so
a failure reproduces from the test alone rather than from a local replay store.

`FUZZ_SCALE=<n>` switches to the exploratory profile: every budget multiplied by
`n`, and random generation, so each run looks somewhere new. That is the long
run a person starts by hand; a failure it finds prints the `@reproduce_failure`
blob to pin it with, and the input it shrank to belongs in the suite as an
example.
"""
from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

FUZZ_SCALE = max(1, int(os.environ.get("FUZZ_SCALE", "1") or "1"))

_COMMON = dict(
    database=None,
    # A budget is a count of examples, never a clock: CI runners are slower
    # than a laptop by a factor that changes, and a deadline would fail the
    # slow machine for being slow.
    deadline=None,
    print_blob=True,
    # The suites generate deliberately skewed input - mostly malformed frames -
    # and that is the point, not a smell.
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)

settings.register_profile("sketchy", derandomize=True, **_COMMON)
settings.register_profile("fuzz", derandomize=False, **_COMMON)
settings.load_profile("fuzz" if FUZZ_SCALE > 1 else "sketchy")


def budget(examples: int) -> int:
    """`examples` on an ordinary run, `FUZZ_SCALE` times that on a long one."""
    return examples * FUZZ_SCALE
