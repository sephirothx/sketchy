"""Waiting rooms that never start a game are closed after a while (#1232).

A room is the one ceiling a handful of idle clients could fill: 200 per process,
three per account, and an account costs nothing to make, so 67 guests on idle
sockets held every room for as long as they cared to. The per-address ceiling
in `room_quotas.py` bounds one client; this bounds everybody else - a room is
for playing in, and one that has sat in its waiting room for
`IDLE_ROOM_SECONDS` without ever starting a game is closed.

Only rooms that have **never** started a game: a room between games has
players who just played together and a recap on screen, and an empty room
already goes with its last player (#480). Closing tells every seat why before
its socket goes, with the same `kicked` notice an administrator's close uses
and its own code (`room_expired`), so the client says so rather than
reconnecting into a room that no longer exists.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from app.rooms import Room, RoomManager

logger = logging.getLogger("sketchy.idle_rooms")

#: How long a room may wait for its first game. Long enough to gather friends
#: from a shared link; far longer than any lobby a person is still watching.
IDLE_ROOM_SECONDS = 30 * 60
#: How often rooms are looked at. A room closes within this of its deadline.
SWEEP_SECONDS = 60.0
#: What a closed room's seats are told. English, for a log; the client writes
#: its own sentence from the code (R-I18N-01).
EXPIRED_NOTICE = (
    "kicked",
    {"code": "room_expired", "reason": "This room closed after 30 minutes without a game."},
)


def is_idle(room: Room, now: float, idle_seconds: float = IDLE_ROOM_SECONDS) -> bool:
    """Whether `room` has waited `idle_seconds` without ever starting a game."""
    return (
        not room.started_a_game
        and room.game is None
        and room.state == "waiting"
        and now - room.created_at >= idle_seconds
    )


class IdleRoomReaper:
    """Closes the rooms `is_idle` names, one pass per tick."""

    def __init__(
        self,
        room_manager: RoomManager,
        context,
        *,
        idle_seconds: float = IDLE_ROOM_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._rooms = room_manager
        self._context = context
        self.idle_seconds = idle_seconds
        self._clock = clock

    async def flush(self) -> int:
        """Close every idle room; return how many were closed."""
        now = self._clock()
        closed = 0
        for room in list(self._rooms.rooms.values()):
            if not is_idle(room, now, self.idle_seconds):
                continue
            # Re-read after every await: a seat evicted above can take the
            # room with it, and one may have started a game meanwhile.
            for player in list(room.player_list()):
                if room.started_a_game or self._rooms.rooms.get(room.id) is not room:
                    break
                await self._context.evict_player(room, player.id, notice=EXPIRED_NOTICE)
            if self._rooms.rooms.get(room.id) is room and not room.started_a_game:
                await self._context.remove_room_if_empty(room.id)
            closed += 1
            logger.info("closed room %s: no game in %.0f minutes", room.id, self.idle_seconds / 60)
        return closed

    async def run(self, *, health=None) -> None:
        """Tick for ever, swallowing everything but cancellation."""
        while True:
            await asyncio.sleep(SWEEP_SECONDS)
            try:
                await self.flush()
                if health is not None:
                    health.record_success()
            except asyncio.CancelledError:
                raise
            except Exception:
                # One bad pass must not stop the next; counted, so a reaper
                # that fails every time is a readiness signal, not a surprise.
                if health is not None:
                    health.record_failure()
                logger.exception("idle room sweep failed")


def start_idle_room_loop(reaper: IdleRoomReaper, *, health=None) -> asyncio.Task[None]:
    return asyncio.create_task(reaper.run(health=health))


async def stop_idle_room_loop(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
