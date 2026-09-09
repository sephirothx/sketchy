"""When a person stopped answering, and what the room does about it.

AFK already meant everything it needs to mean: the rotation skips it, nobody
is waited on for it, the eligibility freeze records it, and a turn outcome
carries it. What it could not do was arrive on its own, so a player who simply
stopped responding cost the room a turn per rotation - their turn came round,
the choosing timer lapsed into a forced pick, and everyone watched a blank
canvas for the whole drawing time - and held every other turn open to its full
length, because a turn ends early only when every eligible guesser has
guessed. The remedies were both social and both too heavy: the AFK vote needs
a strict majority, which two players can never reach, and a kick is a larger
thing to ask of people than "they went to make coffee".

Three pieces, and the split is the design:

* `ActivityLedger` - when each socket last did something a person did. A plain
  ledger of stamps, written at the one door every command passes through.
* `decide` - pure, and the only place the rule lives. Given how long a socket
  has been quiet and how long its check has been open, it says nothing, ask,
  or raise.
* `AfkWatch` - the tick that walks live rooms, applies those decisions, and
  owns the one piece of mutable state the rule needs: which sockets have an
  open check.

**Inactivity is the only clock.** The tempting signal was `session_ping`,
which the client already gates on tab visibility, so its absence past
`MAX_GAP_MS` means the tab is hidden for free. It is not used, on the merits:
a hidden tab is not an absent player, and somebody reading a room list in
another window is still playing. It would also not have worked where it is
needed most - the heartbeat is gated on being in an active phase, so a
waiting-room seat sends none and a lobby socket never has. A hidden tab is
still marked, because it cannot answer the check; that is the inactivity rule
reaching it, not a rule about hiding.

**A guesser watching a drawing sends nothing, so the client answers for
them - on demand, not on a timer.** The check is a question, and a client that
has seen a pointer or a key inside its own window answers it silently. That is
faithful to what inactivity means to a person and costs one event and one
answer per idle window, rather than the periodic report that would have to run
whether anybody was near the deadline or not.

This is courtesy, not enforcement. A modified client that always answers is
never marked, and that is the right trade: the adversarial remedy is the AFK
vote, which already exists, and hardening this against a hostile client would
buy nothing against an honest one while costing every honest one the traffic.

Process-owned and never durable, like every other live-state owner (see the
state ownership table in `docs/architecture.md`).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time

from app.flow_timing import FlowTiming, timing as default_timing
from app.rooms import Player, Room, RoomManager

logger = logging.getLogger("sketchy.afk")

# How often the sweep looks. Deliberately coarse against a five-minute window:
# the check is not a deadline anybody is racing, and a second either way on
# when it is asked is not observable. One pass over the live rooms, which is
# the same pass the presence tick already makes once a second.
DEFAULT_SWEEP_INTERVAL_SECONDS = 5.0

# Commands that do not count as activity, because the client sends them
# without anybody asking it to. Everything else counts - the same
# default-is-strictest shape as `COMMAND_CLASSES` in `handlers/budgets.py`,
# so a command added without a thought about this lands on the safe side
# (it keeps a seat alive) rather than silently marking people absent.
#
# `session_ping` is the liveness probe, `request_sync_strokes` is the canvas
# recovering itself, `watch_lobby` and `unwatch_lobby` are a component
# mounting, and the two `get_` reads below are fetched on mount. Every other
# `get_` is a human clicking something and counts.
INACTIVITY_EXEMPT_COMMANDS: frozenset[str] = frozenset(
    {
        "session_ping",
        "request_sync_strokes",
        "watch_lobby",
        "unwatch_lobby",
        "get_room_settings",
        "get_custom_prompts",
    }
)

# What `decide` says to do about one socket.
NOTHING = "nothing"
CHECK = "check"
RAISE = "raise"


class ActivityLedger:
    """When each socket last did something a person did.

    Keyed by socket rather than by seat: the stamp is written at
    `HandlerContext.on`, which knows the sid and not the player, and a seat's
    activity is its current socket's activity by definition - a reconnected
    seat holds a new sid and starts a fresh clock, which is correct, because
    somebody who just reconnected did something.

    Monotonic, not wall clock: these are durations, and a clock stepped by NTP
    must not mark a room absent.
    """

    __slots__ = ("_last", "_clock")

    def __init__(self, *, clock=time.monotonic) -> None:
        self._last: dict[str, float] = {}
        self._clock = clock

    def note(self, sid: str) -> None:
        """Record that this socket just did something."""
        self._last[sid] = self._clock()

    def forget(self, sid: str) -> None:
        """Drop a socket that has gone."""
        self._last.pop(sid, None)

    def idle_seconds(self, sid: str) -> float:
        """How long this socket has been quiet.

        A socket with no stamp at all is treated as quiet since now rather
        than for ever: the handshake stamps every socket, so the only way to
        be missing is to have just been forgotten, and the answer that marks
        nobody is the right one for a race.
        """
        last = self._last.get(sid)
        if last is None:
            return 0.0
        return max(0.0, self._clock() - last)

    def __len__(self) -> int:
        return len(self._last)


def decide(
    *, idle_seconds: float, check_open_seconds: float | None, timing: FlowTiming
) -> str:
    """Nothing, ask, or raise - the whole rule, in one pure function.

    `check_open_seconds` is how long this socket's check has been open, or
    `None` when it has none. A check is only ever resolved by activity, which
    is why nothing here clears one: the caller drops it the moment the socket
    stops being idle, and `decide` never sees an open check on a socket that
    answered.
    """
    if check_open_seconds is not None:
        return RAISE if check_open_seconds >= timing.afk_check_seconds else NOTHING
    return CHECK if idle_seconds >= timing.afk_inactivity_seconds else NOTHING


def checkable_players(room: Room) -> list[Player]:
    """Seats the check applies to.

    Spectators are left out: nothing waits on one, so there is nothing to
    interrupt them for, and the flag would change nothing about the room.
    A seat already AFK is left out because it is already the thing the check
    produces, and a disconnected seat because its socket is gone - the
    reconnect grace, not this, is what decides its fate.
    """
    return [
        player
        for player in room.players.values()
        if player.connected
        and player.sid
        and not player.is_spectator
        and not player.is_afk
    ]


@dataclass(frozen=True, slots=True)
class AfkOutcome:
    """What one sweep did, for the tests and the logs."""

    checked: int = 0
    raised: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.checked and not self.raised


class AfkWatch:
    """The tick that asks, and then marks.

    Owns exactly one piece of mutable state - which sockets have an open
    check - because that is the only thing neither the ledger nor the rooms
    can answer. It is keyed by socket for the same reason the ledger is: a
    check belongs to the connection it was asked down, and a seat that
    reconnects has answered it by reconnecting.
    """

    def __init__(
        self,
        sio,
        room_manager: RoomManager,
        activity: ActivityLedger,
        game_flow,
        *,
        timing: FlowTiming | None = None,
        interval_seconds: float = DEFAULT_SWEEP_INTERVAL_SECONDS,
        clock=time.monotonic,
    ) -> None:
        self._sio = sio
        self._room_manager = room_manager
        self._activity = activity
        self._game_flow = game_flow
        self._timing = timing if timing is not None else default_timing
        self.interval_seconds = interval_seconds
        self._clock = clock
        self._checks: dict[str, float] = {}

    @property
    def open_checks(self) -> int:
        return len(self._checks)

    def forget(self, sid: str) -> None:
        """Drop a socket's open check, if it had one."""
        self._checks.pop(sid, None)

    def _check_open_for(self, sid: str) -> float | None:
        asked_at = self._checks.get(sid)
        if asked_at is None:
            return None
        return max(0.0, self._clock() - asked_at)

    async def flush(self) -> AfkOutcome:
        """One pass: ask the newly quiet, mark those who did not answer."""
        checked = 0
        raised = 0
        for room in list(self._room_manager.rooms.values()):
            for player in checkable_players(room):
                sid = player.sid
                assert sid is not None  # checkable_players filtered on it
                idle = self._activity.idle_seconds(sid)
                # Activity closes an open check wherever it happened, without
                # the command path having to know a check exists. The seat is
                # below the window again, so whatever it did counted.
                if idle < self._timing.afk_inactivity_seconds:
                    self._checks.pop(sid, None)
                    continue
                action = decide(
                    idle_seconds=idle,
                    check_open_seconds=self._check_open_for(sid),
                    timing=self._timing,
                )
                if action == CHECK:
                    self._checks[sid] = self._clock()
                    await self._ask(player)
                    checked += 1
                elif action == RAISE:
                    self._checks.pop(sid, None)
                    await self._raise(room, player)
                    raised += 1
        self._forget_departed()
        return AfkOutcome(checked=checked, raised=raised)

    def _forget_departed(self) -> None:
        """Drop checks for sockets no longer holding a live seat.

        `disconnect` drops the ordinary case; this covers a seat that changed
        hands or a room that closed under an open check, so the map cannot
        grow across a long-lived process.
        """
        if not self._checks:
            return
        live = {
            player.sid
            for room in self._room_manager.rooms.values()
            for player in room.players.values()
            if player.sid
        }
        for sid in [sid for sid in self._checks if sid not in live]:
            del self._checks[sid]

    async def _ask(self, player: Player) -> None:
        """Ask one seat whether anybody is there."""
        await self._sio.emit(
            "afk_check",
            {"seconds": self._timing.afk_check_seconds},
            to=player.sid,
        )

    async def _raise(self, room: Room, player: Player) -> None:
        """Mark one seat AFK, with everything that follows from it."""
        player.is_afk = True
        # The host role moves before the room hears about either change, so
        # the broadcast carries one consistent state rather than a room that
        # briefly has an AFK host. Only this path moves it: a player who set
        # AFK themselves is present and can toggle back, and one voted AFK had
        # a majority who could have kicked them instead.
        self._room_manager.release_host_if_held(room, player)
        await self._game_flow._emit_room_state(room)
        await self._game_flow.apply_afk_consequences(room, player)
        logger.info(
            "marked seat AFK after inactivity",
            extra={"room_id": room.id, "player_id": player.id},
        )

    async def run(self, *, health=None) -> None:
        """Tick for ever, swallowing everything but cancellation.

        Sleeps first, like the presence loop: a process that has just started
        has nobody who has been quiet long enough to ask.
        """
        while True:
            await asyncio.sleep(self.interval_seconds)
            try:
                await self.flush()
                if health is not None:
                    health.record_success()
            except asyncio.CancelledError:
                raise
            except Exception:
                # One bad tick must not stop every later one. Counted rather
                # than only logged: a sweep that fails every time is a game
                # that quietly stopped skipping absent players, which is
                # exactly the silent failure readiness exists to surface.
                if health is not None:
                    health.record_failure()
                logger.exception("AFK sweep failed")


def start_afk_loop(watch: AfkWatch, *, health=None) -> asyncio.Task[None]:
    return asyncio.create_task(watch.run(health=health))


async def stop_afk_loop(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def sweep_interval_from(timing: FlowTiming) -> float:
    """A sweep interval that cannot overshoot the check it is measuring.

    The check window is the short one, and a sweep coarser than it would let a
    check sit open for a whole extra interval - which matters once a
    deployment (or the E2E suite) tunes the windows down to seconds.
    """
    return max(0.1, min(DEFAULT_SWEEP_INTERVAL_SECONDS, timing.afk_check_seconds / 2))


__all__ = [
    "ActivityLedger",
    "AfkOutcome",
    "AfkWatch",
    "CHECK",
    "INACTIVITY_EXEMPT_COMMANDS",
    "NOTHING",
    "RAISE",
    "checkable_players",
    "decide",
    "start_afk_loop",
    "stop_afk_loop",
    "sweep_interval_from",
]
