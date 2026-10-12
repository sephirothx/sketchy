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
import signal
import sys
import threading
import traceback
from contextlib import contextmanager

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


# Far past any honest run of a generated-input suite on CI (about a minute).
STALL_SECONDS = 240


class Stalled(AssertionError):
    """A generated-input suite outlived `STALL_SECONDS`; carries every
    thread's stack at that moment."""


def _every_stack() -> str:
    names = {thread.ident: thread.name for thread in threading.enumerate()}
    blocks = []
    for ident, frame in sys._current_frames().items():
        stack = "".join(traceback.format_stack(frame, limit=12))
        blocks.append(f"--- thread {names.get(ident, ident)} ---\n{stack}")
    return "\n".join(blocks)


@contextmanager
def stall_guard(seconds: float = STALL_SECONDS):
    """Fail the test, with every thread's stack, if the body runs past
    `seconds`.

    A suite that blocks the thread its event loop runs on cannot be stopped
    by any asyncio timeout, and under xdist a stuck worker is silent: CI runs
    of #1479 sat after their last report until the runner was shut down.
    Ending the worker instead left xdist's controller waiting out the job's
    six hours. An alarm signal interrupts the main thread where it is
    blocked - a select, a lock, a pure-Python loop - and raises there, so the
    test fails as an ordinary failure whose report, which xdist does show,
    holds the stacks.
    """
    def interrupt(signum, frame):
        raise Stalled(f"ran past {seconds} s; every thread at that moment:\n{_every_stack()}")

    previous = signal.signal(signal.SIGALRM, interrupt)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
