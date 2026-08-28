"""Bounded planned-shutdown drain for process-owned live rooms."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import math
import time
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PlannedShutdownAbandonment
from app.rooms import Room, RoomManager


logger = logging.getLogger("sketchy.shutdown")
SHUTDOWN_NOTICE_CONTRACT_VERSION = 1
PAUSE_NOTICE_CONTRACT_VERSION = 1
ABANDONMENT_RETENTION = timedelta(days=90)
NEW_WORK_REJECTION = "Server update in progress; try again shortly"
PAUSE_REJECTION = "New rooms are paused for maintenance; try again shortly"
SHUTDOWN_NOTICE_TIMEOUT_SECONDS = 2.0
ABANDONMENT_WRITE_TIMEOUT_SECONDS = 5.0


class _DrainAborted(Exception):
    """The operator asked for an immediate exit while the drain was waiting."""


def _never_abort() -> bool:
    return False


@dataclass(frozen=True)
class DrainResult:
    # Games that left the active set during the window. Most finished normally;
    # a room everyone abandoned also leaves it, so this counts "no longer live"
    # rather than "reached game_end".
    drained_game_count: int
    abandoned_game_count: int
    timed_out: bool
    aborted: bool = False


class ShutdownCoordinator:
    """Own readiness and one bounded graceful drain per process lifetime."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        room_manager: RoomManager,
    ) -> None:
        self._session_factory = session_factory
        self._room_manager = room_manager
        self._state = "starting"
        self._paused = False
        self._shutdown_claimed = False
        self._drain_seconds = 0.0
        self._started_at: datetime | None = None
        self._game_state_changed = asyncio.Event()

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_ready(self) -> bool:
        return self._state == "ready"

    @property
    def is_draining(self) -> bool:
        """A bounded deployment drain is running. One-way, once per process."""
        return self._state == "draining"

    @property
    def is_paused(self) -> bool:
        """An administrator has stopped this process taking new work."""
        return self._paused

    @property
    def refuses_new_work(self) -> bool:
        """Whether this process is taking new rooms, games and votes.

        The one question every admission check actually asks. A drain and a
        maintenance pause are different events with different notices, but
        they are the same answer here, so the handlers consult this rather
        than enumerating the reasons - which is what keeps a new reason from
        having to be added in nine places.
        """
        return self._state == "draining" or self._paused

    @property
    def shutdown_requested(self) -> bool:
        """Whether a stop has been asked for but has not begun draining yet."""
        return self._shutdown_claimed

    def claim_shutdown(self) -> bool:
        """Take the right to stop this process, once. False if already taken.

        There is a gap between asking the process to stop and the drain
        actually starting, and `is_draining` is false for all of it - so
        without a claim, two clicks a moment apart are two accepted requests,
        two audit events for one shutdown, and a second chance to change the
        drain window after the first was written down.

        Check and set with no await between them, which on one event loop is
        as atomic as it needs to be.
        """
        if self._shutdown_claimed:
            return False
        self._shutdown_claimed = True
        return True

    def release_shutdown_claim(self) -> None:
        """Give the claim back, for a request that did not go through with it."""
        self._shutdown_claimed = False

    def pause(self, paused: bool = True) -> None:
        """Stop, or resume, admitting new work - without stopping the process.

        Deliberately not `begin_shutdown` with a longer drain. That is one-way
        by construction, records the games it outlives as abandoned, and ends
        with a process that has to be restarted; a pause is none of those. It
        also leaves `is_ready` alone on purpose, so `/api/ready` keeps
        answering 200: a readiness failure invites an orchestrator to replace
        the container, which is the opposite of what pausing it is for.
        """
        self._paused = paused

    def pause_payload(self) -> dict:
        """The `server_paused` notice, sent on each toggle."""
        return {
            "contractVersion": PAUSE_NOTICE_CONTRACT_VERSION,
            "paused": self._paused,
            "reason": "maintenance",
        }

    @property
    def drain_seconds(self) -> float:
        return self._drain_seconds

    def set_drain_seconds(self, seconds: float) -> None:
        """Change how long the next drain will wait for games to finish.

        Read at the top of `begin_shutdown` rather than captured at startup,
        so a value changed while the process is running is the one the next
        deployment drain uses. Changing it *during* a drain does not move the
        deadline already being waited on, which is the honest behaviour: the
        clients were told a number in the shutdown notice.
        """
        self._drain_seconds = seconds

    def begin_startup(self, *, drain_seconds: float) -> None:
        self._state = "starting"
        self._drain_seconds = drain_seconds
        self._started_at = None
        self._game_state_changed = asyncio.Event()

    def mark_ready(self) -> None:
        if self._state != "starting":
            raise RuntimeError("shutdown coordinator is not starting")
        self._state = "ready"

    def notify_game_state_changed(self) -> None:
        self._game_state_changed.set()

    def rejection_acknowledgement(self) -> dict:
        """Why this command was refused, in words written for the player.

        A drain and a pause are told apart on the wire rather than sharing one
        flag: a drain means this server is going away and a reload will find
        another, while a pause means it is still here and will take the room
        shortly. A client that could not tell them apart would have to guess
        which advice to give.
        """
        if self._state == "draining":
            return {
                "ok": False,
                "error": NEW_WORK_REJECTION,
                "serverDraining": True,
            }
        return {
            "ok": False,
            "error": PAUSE_REJECTION,
            "serverPaused": True,
        }

    def notice_payload(self) -> dict:
        if self._started_at is None:
            raise RuntimeError("shutdown drain has not started")
        return {
            "contractVersion": SHUTDOWN_NOTICE_CONTRACT_VERSION,
            "reason": "deployment",
            "drainSeconds": math.ceil(self._drain_seconds),
            "startedAt": self._started_at.isoformat(),
        }

    def _active_games(self) -> list[tuple[Room, object]]:
        return [
            (room, room.game)
            for room in self._room_manager.rooms.values()
            if room.state == "playing" and room.game is not None
        ]

    async def _wait_for_games(
        self, deadline: float, should_abort: Callable[[], bool]
    ) -> None:
        while self._active_games():
            if should_abort():
                # A second termination signal means the operator wants out now,
                # so the rest of the window is forfeited rather than waited out.
                raise _DrainAborted
            self._game_state_changed.clear()
            if not self._active_games():
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            try:
                await asyncio.wait_for(
                    self._game_state_changed.wait(),
                    timeout=min(remaining, 0.25),
                )
            except asyncio.TimeoutError:
                # The short polling fallback means a missed notification can
                # never hold shutdown open past the configured deadline.
                continue

    async def begin_shutdown(
        self, sio, *, should_abort: Callable[[], bool] | None = None
    ) -> DrainResult:
        """Stop admitting new work, announce, drain, then record only leftovers."""

        if self._state == "stopped":
            return DrainResult(0, 0, False)
        if self._state == "draining":
            raise RuntimeError("shutdown drain is already running")

        # Flip readiness synchronously. Handlers refuse new work on this flag,
        # and in-flight create/start handlers check it again after every
        # repository await and before their live mutation, so no admission lock
        # is needed to keep a half-finished room out of the drained process.
        self._state = "draining"
        self._started_at = datetime.now(timezone.utc)
        initial_game_ids = {str(game.id) for _, game in self._active_games()}
        try:
            await asyncio.wait_for(
                sio.emit("server_shutdown", self.notice_payload()),
                timeout=SHUTDOWN_NOTICE_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.exception("Failed to emit planned shutdown notice")

        abort = should_abort if should_abort is not None else _never_abort
        timed_out = False
        aborted = False
        if initial_game_ids and self._drain_seconds > 0:
            try:
                await self._wait_for_games(
                    time.monotonic() + self._drain_seconds, abort
                )
            except _DrainAborted:
                aborted = True
            except TimeoutError:
                timed_out = True
        elif initial_game_ids:
            timed_out = True

        remaining = [
            (room, game)
            for room, game in self._active_games()
            if str(game.id) in initial_game_ids
        ]
        if remaining and not aborted:
            timed_out = True
            try:
                await asyncio.wait_for(
                    self._record_abandonments(remaining),
                    timeout=ABANDONMENT_WRITE_TIMEOUT_SECONDS,
                )
            except Exception:
                # Shutdown must remain bounded even if diagnostics storage is
                # unavailable. This failure is itself operator-visible in logs.
                logger.exception("Failed to record planned shutdown abandonments")
        self._state = "stopped"
        result = DrainResult(
            drained_game_count=len(initial_game_ids) - len(remaining),
            abandoned_game_count=len(remaining),
            timed_out=timed_out,
            aborted=aborted,
        )
        logger.info(
            "Planned shutdown drain finished: %d game(s) drained, %d left live, "
            "timed_out=%s, aborted=%s",
            result.drained_game_count,
            result.abandoned_game_count,
            result.timed_out,
            result.aborted,
        )
        return result

    async def _record_abandonments(self, games: list[tuple[Room, object]]) -> None:
        observed_at = datetime.now(timezone.utc)
        game_ids = [UUID(str(game.id)) for _, game in games]
        async with self._session_factory() as session:
            async with session.begin():
                existing = set(
                    (
                        await session.scalars(
                            select(PlannedShutdownAbandonment.game_id).where(
                                PlannedShutdownAbandonment.game_id.in_(game_ids)
                            )
                        )
                    ).all()
                )
                for room, game in games:
                    game_id = UUID(str(game.id))
                    if game_id in existing:
                        continue
                    phase = getattr(game.phase, "value", str(game.phase))
                    seated = room.seated_players()
                    session.add(
                        PlannedShutdownAbandonment(
                            game_id=game_id,
                            room_instance_id=UUID(room.retention_scope_id),
                            reason="drain_timeout",
                            phase=phase,
                            round_number=max(0, game.round_number),
                            completed_turn_count=len(game.completed_turns),
                            seated_player_count=len(seated),
                            connected_player_count=sum(
                                player.connected for player in seated
                            ),
                            spectator_count=sum(
                                player.is_spectator
                                for player in room.player_list()
                            ),
                            canvas_action_count=len(game.canvas.history),
                            game_started_at=game.started_at,
                            observed_at=observed_at,
                        )
                    )


async def purge_expired_shutdown_abandonments(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
) -> int:
    """Enforce the 90-day diagnostic-retention boundary at startup."""

    cutoff = (now or datetime.now(timezone.utc)) - ABANDONMENT_RETENTION
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                delete(PlannedShutdownAbandonment).where(
                    PlannedShutdownAbandonment.observed_at <= cutoff
                )
            )
            return int(result.rowcount or 0)
