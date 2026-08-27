"""What one caller may ask of a room, and how often.

The authentication surface has been carefully limited since it shipped; no
in-room command was limited at all. Every one of them does real work per call
- a database write and a fan-out for chat, a rebroadcast for a drawing frame,
a full canvas re-encode for a resync - so one seated player emitting in a loop
spends the whole worker, and on the default SQLite deployment their writes
contend with history and authentication for the single writer.

Budgets are sized against what the client actually does rather than against a
round number:

* **Drawing** is the busiest by design. The drawer's flush timer fires every
  40ms, so a legitimate drawer sends 25 frames a second, plus fills and shapes
  that do not wait for the timer. The budget is double that and no tighter,
  because each frame is small and already bounded, and a jittery connection
  bunches frames after a stall.
* **Conversation** is a message or two a second at speed.
* **Resync** is the cheap request with the expensive answer, so it gets a
  floor rather than a ceiling: a few seconds between full canvas replays.
* **Everything else** - votes, hints, settings, renames, previews - is a
  human pressing a control, which no one does thirty times in ten seconds.

Deliberately not configurable. These follow the client's own cadence, not the
size of the host, so an operator has nothing to tune here that would not be
better fixed in the protocol.
"""
from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
import time
from typing import Mapping


@dataclass(frozen=True)
class Budget:
    """How many of one command a caller may send inside a window."""

    limit: int
    window_seconds: float


# Double the 25 frames a second the drawer's timer produces.
DRAWING = Budget(limit=100, window_seconds=2.0)
# A fast typist sends about one a second; this is twice that, sustained.
CONVERSATION = Budget(limit=20, window_seconds=10.0)
# A floor between full canvas replays, which is the one cheap request with an
# expensive answer.
RESYNC = Budget(limit=3, window_seconds=10.0)
# The client heartbeats every five seconds and probes a stalled phase.
HEARTBEAT = Budget(limit=20, window_seconds=10.0)
# A person pressing a control.
ACTION = Budget(limit=30, window_seconds=10.0)

COMMAND_BUDGETS: Mapping[str, Budget] = {
    "draw": DRAWING,
    "undo_stroke": DRAWING,
    "send_chat": CONVERSATION,
    "guess": CONVERSATION,
    "request_sync_strokes": RESYNC,
    "session_ping": HEARTBEAT,
}


def budget_for(command: str) -> Budget:
    """The budget this command answers to; everything has one."""
    return COMMAND_BUDGETS.get(command, ACTION)


class CommandBudgets:
    """Sliding windows for one process's callers, keyed by socket and command.

    Deliberately in memory and per process: a budget is about what one live
    connection is doing right now, and a connection does not outlive the
    process that holds it. The persistent buckets in `auth/rate_limit.py`
    exist for the opposite case - attempts that must survive a restart.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, budget: Budget) -> bool:
        """Record one command, returning False once its window is full."""
        now = self._clock()
        cutoff = now - budget.window_seconds
        hits = self._hits[key]
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= budget.limit:
            return False
        hits.append(now)
        return True

    def forget(self, sid: str) -> None:
        """Drop every window belonging to a socket that has gone.

        Keyed by socket and command, so the map would otherwise keep a deque
        per command per connection for the life of the process - and this one
        also holds every live game.
        """
        prefix = f"{sid}:"
        for key in [key for key in self._hits if key.startswith(prefix)]:
            del self._hits[key]

    def tracked_keys(self) -> int:
        return len(self._hits)
