"""What one caller may ask of a room, and how often.

The authentication surface has been carefully limited since it shipped; no
in-room command was limited at all. Every one of them does real work per call
- a database write and a fan-out for chat, a rebroadcast for a drawing frame,
a full canvas re-encode for a resync - so one seated player emitting in a loop
spends the whole worker, and on the default SQLite deployment their writes
contend with history and authentication for the single writer.

Budgets are sized against what the client actually does rather than against a
round number, and they are grouped into a handful of classes rather than set
per command, because the thing being tuned is a *kind* of traffic:

* **Drawing** is the busiest by design. The drawer's flush timer fires every
  40ms, so a legitimate drawer sends 25 frames a second, plus fills and shapes
  that do not wait for the timer. The budget is double that and no tighter,
  because each frame is small and already bounded, and a jittery connection
  bunches frames after a stall. Refusals here are silent: nobody is waiting on
  an answer to a frame, and an error surfacing mid-stroke is worse than the
  dropped frame it describes.
* **Conversation** is a message or two a second at speed.
* **Resync** is the cheap request with the expensive answer, so it gets a
  floor rather than a ceiling: a few seconds between full canvas replays.
* **Everything else** - votes, hints, settings, renames, previews - is a
  human pressing a control, which no one does thirty times in ten seconds.

Held in a policy object rather than read from the environment, because the
values follow the client's cadence rather than the size of the host, and
because #446 wants tunables changed from an admin panel without a deploy -
and without a restart where that turns out to be possible. Each carries the
default, the bounds and the one-line description that panel will want;
nothing here reads `os.environ`, which would fix the value at startup and
foreclose the second half of that.
"""
from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
import time


@dataclass(frozen=True)
class Budget:
    """How many of one kind of command a caller may send inside a window."""

    limit: int
    window_seconds: float
    # Frames are fire-and-forget at twenty-five a second; a refusal that
    # answered would surface an error nobody asked for, mid-stroke.
    silent: bool = False


@dataclass(frozen=True)
class BudgetClass:
    """One tunable budget, with what a panel needs to show and bound it."""

    name: str
    default: Budget
    minimum: int
    maximum: int
    description: str


DRAWING = BudgetClass(
    name="drawing",
    default=Budget(limit=100, window_seconds=2.0, silent=True),
    minimum=50,
    maximum=400,
    description=(
        "Drawing frames per two seconds. The drawer's flush timer produces 25 "
        "a second, so anything at or below 50 refuses legitimate drawing."
    ),
)
CONVERSATION = BudgetClass(
    name="conversation",
    default=Budget(limit=20, window_seconds=10.0),
    minimum=5,
    maximum=120,
    description="Chat messages and guesses per ten seconds.",
)
RESYNC = BudgetClass(
    name="resync",
    default=Budget(limit=3, window_seconds=10.0),
    minimum=1,
    maximum=30,
    description=(
        "Full canvas replays per ten seconds. A cheap request with an "
        "expensive answer, so this is a floor rather than a ceiling."
    ),
)
HEARTBEAT = BudgetClass(
    name="heartbeat",
    default=Budget(limit=20, window_seconds=10.0),
    minimum=5,
    maximum=120,
    description="Liveness checks per ten seconds. The client sends one every five.",
)
ACTION = BudgetClass(
    name="action",
    default=Budget(limit=30, window_seconds=10.0),
    minimum=5,
    maximum=200,
    description=(
        "Everything else - votes, hints, settings, renames - per ten seconds. "
        "A person pressing a control."
    ),
)

BUDGET_CLASSES: tuple[BudgetClass, ...] = (
    DRAWING,
    CONVERSATION,
    RESYNC,
    HEARTBEAT,
    ACTION,
)

# Commands not named here answer to `action`, so a command added without a
# thought about its budget gets the strictest ordinary one rather than none.
COMMAND_CLASSES: Mapping[str, str] = {
    "draw": DRAWING.name,
    "undo_stroke": DRAWING.name,
    "send_chat": CONVERSATION.name,
    "guess": CONVERSATION.name,
    "request_sync_strokes": RESYNC.name,
    "session_ping": HEARTBEAT.name,
}


class CommandBudgetPolicy:
    """The budgets in force, and the metadata for changing them.

    Mutable on purpose: #446 asks for tunables to be changed from an admin
    panel without a deploy, and without a restart if that proves possible, so
    the values live behind an object a request could reach rather than in
    constants only a deploy can replace.
    """

    def __init__(self) -> None:
        self._classes = {item.name: item for item in BUDGET_CLASSES}
        self._budgets = {item.name: item.default for item in BUDGET_CLASSES}

    def for_command(self, command: str) -> Budget:
        """The budget this command answers to; everything has one."""
        return self._budgets[COMMAND_CLASSES.get(command, ACTION.name)]

    def describe(self) -> list[dict]:
        """Every budget with its current value, default, bounds and purpose.

        Plain field names, not wire names: this is what an endpoint would be
        built from, not a payload. #446 owns the endpoint and the camelCase
        that goes with it, and inventing keys here that no client reads would
        be a contract the wire tests are right to refuse.
        """
        return [
            {
                "name": item.name,
                "limit": self._budgets[item.name].limit,
                "window_seconds": self._budgets[item.name].window_seconds,
                "default": item.default.limit,
                "minimum": item.minimum,
                "maximum": item.maximum,
                "description": item.description,
            }
            for item in BUDGET_CLASSES
        ]

    def set_limit(self, name: str, limit: int) -> None:
        """Change one budget, refusing a value the client could not live with."""
        item = self._classes.get(name)
        if item is None:
            raise KeyError(f"unknown budget class: {name}")
        if not item.minimum <= limit <= item.maximum:
            raise ValueError(
                f"{name} must be between {item.minimum} and {item.maximum}"
            )
        self._budgets[name] = replace(self._budgets[name], limit=limit)


class CommandBudgets:
    """Sliding windows for one process's callers, keyed by socket and command.

    Deliberately in memory and per process: a budget is about what one live
    connection is doing right now, and a connection does not outlive the
    process holding it. The persistent buckets in `auth/rate_limit.py` exist
    for the opposite case - attempts that must survive a restart.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._reported: dict[str, float] = {}

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

    def should_report(self, key: str, budget: Budget) -> bool:
        """Whether this refusal is the one worth recording.

        Once per window rather than once per refusal: a caller being refused
        is being refused repeatedly, so recording each one would be the write
        amplification these budgets exist to stop - but recording only the
        first of a run would make a two-second mistake and a twenty-minute
        flood look identical afterwards.
        """
        now = self._clock()
        last = self._reported.get(key)
        if last is not None and now - last < budget.window_seconds:
            return False
        self._reported[key] = now
        return True

    def forget(self, sid: str) -> None:
        """Drop every window belonging to a socket that has gone.

        Keyed by socket and command, so the maps would otherwise keep an entry
        per command per connection for the life of a process that also holds
        every live game.
        """
        prefix = f"{sid}:"
        for key in [key for key in self._hits if key.startswith(prefix)]:
            del self._hits[key]
        for key in [key for key in self._reported if key.startswith(prefix)]:
            del self._reported[key]

    def tracked_keys(self) -> int:
        return len(self._hits)


def command_names(commands: Iterable[str]) -> set[str]:
    """The commands a policy knows a class for, for contract checking."""
    return set(commands) & set(COMMAND_CLASSES)
