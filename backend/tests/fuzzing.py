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

import faulthandler
import os
from contextlib import contextmanager
from pathlib import Path

from hypothesis import HealthCheck, settings

FUZZ_SCALE = max(1, int(os.environ.get("FUZZ_SCALE", "1") or "1"))

_COMMON = dict(
    database=None,
    # A budget is a count of examples, never a clock: CI runners are slower
    # than a laptop by a factor that changes, and a deadline would fail the
    # slow machine for being slow.
    deadline=None,
    print_blob=True,
    # The suites generate deliberately skewed input - mostly malformed frames,
    # mostly refused commands - and that is the point, not a smell.
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)

settings.register_profile("sketchy", derandomize=True, **_COMMON)
settings.register_profile("fuzz", derandomize=False, **_COMMON)
settings.load_profile("fuzz" if FUZZ_SCALE > 1 else "sketchy")


def budget(examples: int) -> int:
    """`examples` on an ordinary run, `FUZZ_SCALE` times that on a long one."""
    return examples * FUZZ_SCALE


# Far past any honest run of a generated-input suite on CI (about a minute),
# and short of the job being cancelled under it.
STALL_SECONDS = 300


@contextmanager
def stall_guard(seconds: float = STALL_SECONDS):
    """Dump every thread's stack and end the process if the body runs past
    `seconds`.

    A suite that blocks the thread its event loop runs on cannot be stopped
    by any asyncio timeout, and under xdist a stuck worker is silent: three
    CI runs of #1479 sat after their last report until the runner was shut
    down, with nothing in the log. Ending the worker makes xdist report it
    as crashed in the test it was running, so the job fails with a name and
    a stack (`test-results/stall-<worker>.txt`) instead of holding the runner.
    """
    # xdist does not show a worker's stderr, so the stacks go to a file in
    # `test-results/`, which CI uploads with the JUnit report once the job
    # fails rather than being cancelled.
    results = Path(__file__).resolve().parent.parent / "test-results"
    results.mkdir(exist_ok=True)
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    with open(results / f"stall-{worker}.txt", "w") as dump:
        faulthandler.dump_traceback_later(seconds, exit=True, file=dump)
        try:
            yield
        finally:
            faulthandler.cancel_dump_traceback_later()
    # Nothing stalled: leave no empty file behind to be mistaken for one.
    (results / f"stall-{worker}.txt").unlink(missing_ok=True)
