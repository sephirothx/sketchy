"""Shared dependencies passed to every Socket.IO handler domain."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
import logging
from typing import AsyncIterator, Iterator, TYPE_CHECKING

import socketio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.interfaces import (
    GameHistoryRepository,
    UserRepository,
    PromptListRepository,
)
from app.domain_values import RuntimeEventType
from app.handlers.budgets import CommandBudgetPolicy, CommandBudgets
from app.rooms import RoomManager
from app.services.runtime_metrics import metrics
from app.services.timers import TimerManager

if TYPE_CHECKING:
    from app.auth.blocks import BlockService
    from app.services.game_flow import GameFlowService
    from app.services.message_retention import MessageRetentionService
    from app.services.room_codes import RoomCodeService
    from app.services.room_quotas import RoomCapacityService, RoomQuotaService
    from app.services.shutdown import ShutdownCoordinator


logger = logging.getLogger("sketchy.handlers.context")


@dataclass
class SeatingGate:
    """The serializer for one socket's seat transitions.

    Socket.IO dispatches each event from a connection as its own task, so a
    second `create_room` can arrive while the first is still waiting on the
    database. Every transition that takes, moves or gives up a seat runs under
    this, which is what makes "one socket, one seat" a rule rather than a
    property of where the awaits happen to fall.

    The disconnect queues here too, which is the ordering that matters most:
    a socket that drops mid-entry is reconciled after its seat exists rather
    than before, so it cannot leave one behind marked connected.
    """

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Live holders, waiting ones included. The gate is dropped at zero so the
    # registry cannot outgrow the sockets that are actually seating.
    holders: int = 0


@dataclass
class HandlerContext:
    """Application-owned state used by the Socket.IO transport adapters."""

    sio: socketio.AsyncServer
    room_manager: RoomManager
    timers: TimerManager = field(default_factory=TimerManager)
    user_repo: UserRepository | None = None
    game_history_repo: GameHistoryRepository | None = None
    prompt_list_repo: PromptListRepository | None = None
    # Needed to resolve a hashed opaque session when a socket presents a cookie.
    session_factory: async_sessionmaker[AsyncSession] | None = None
    block_service: BlockService | None = None
    message_retention: MessageRetentionService | None = None
    room_codes: RoomCodeService | None = None
    room_quotas: RoomQuotaService = field(init=False)
    room_capacity: RoomCapacityService = field(init=False)
    shutdown: ShutdownCoordinator | None = None
    game_flow: GameFlowService = field(init=False)
    _seating_gates: dict[str, SeatingGate] = field(
        default_factory=dict, init=False, repr=False
    )
    # The budgets in force. Mutable on purpose: #446 wants tunables changed
    # from an admin panel without a deploy, so they live where a request could
    # reach them rather than in constants only a deploy can replace.
    command_budgets: CommandBudgetPolicy = field(
        default_factory=CommandBudgetPolicy, init=False, repr=False
    )
    _command_windows: CommandBudgets = field(
        default_factory=CommandBudgets, init=False, repr=False
    )
    # Sockets this server is in the act of closing, counted so that two
    # closes of the same socket cannot uncount each other.
    _closing_sockets: dict[str, int] = field(
        default_factory=dict, init=False, repr=False
    )

    def on(self, command: str, handler) -> None:
        """Register a client command, with the budget it answers to.

        Every client-originated command goes through here rather than through
        `sio.on` directly, so that adding one cannot quietly add an unbounded
        one. `test_command_budgets.py` checks the two lists against each other.
        """

        async def guarded(sid, *args):
            # Before parsing, before authorization, before any mutation: a
            # refused command must cost nothing but the check itself.
            budget = self.command_budgets.for_command(command)
            key = f"{sid}:{command}"
            if self._command_windows.check(key, budget):
                return await handler(sid, *args)
            if self._command_windows.should_report(key, budget):
                logger.warning("throttled %s from %s", command, sid)
                metrics.record(
                    RuntimeEventType.COMMAND_THROTTLED, details={"command": command}
                )
            if budget.silent:
                # A frame nobody is waiting on. Answering would put an error on
                # screen in the middle of a stroke, about a frame the client
                # never expected a reply to.
                return None
            return {
                "ok": False,
                "error": "You are doing that too quickly. Slow down a moment.",
            }

        self.sio.on(command, handler=guarded)

    def clear_command_budget(self, sid: str) -> None:
        """Forget a socket that has gone, so the windows do not outlive it."""

        self._command_windows.forget(sid)

    @asynccontextmanager
    async def seating(self, sid: str) -> AsyncIterator[SeatingGate]:
        """Hold one socket's seat transitions to one at a time."""

        gate = self._seating_gates.get(sid)
        if gate is None:
            gate = self._seating_gates[sid] = SeatingGate()
        gate.holders += 1
        try:
            async with gate.lock:
                yield gate
        finally:
            gate.holders -= 1
            if gate.holders <= 0:
                self._seating_gates.pop(sid, None)

    @contextmanager
    def closing(self, sid: str) -> Iterator[None]:
        """Mark a socket this server is closing itself, while it closes it.

        Socket.IO runs a closed socket's disconnect handler inline, so the
        handler has to be able to tell "the client went away" from "we are
        cutting this one off from inside a seat transition". Answered here
        rather than from the framework's disconnect reason, which would make a
        deadlock depend on how a dependency passes an argument.
        """

        self._closing_sockets[sid] = self._closing_sockets.get(sid, 0) + 1
        try:
            yield
        finally:
            remaining = self._closing_sockets.get(sid, 1) - 1
            if remaining <= 0:
                self._closing_sockets.pop(sid, None)
            else:
                self._closing_sockets[sid] = remaining

    def is_closing(self, sid: str) -> bool:
        """Whether this server, rather than the client, is ending this socket."""

        return sid in self._closing_sockets

    async def remove_room_if_empty(self, room_id: str) -> bool:
        """Remove an empty live room and retire its published invite code."""

        removed = self.room_manager.remove_room_if_empty(room_id)
        if removed is None:
            return False
        # A room can be torn down while it still holds a game: the last player
        # to be evicted takes the room with them, and that path never reaches
        # `_remove_player_from_game`. This is the one place every teardown
        # passes through, so it is where a lost game gets written down.
        await self.game_flow.record_abandoned_game(removed)
        if self.room_codes is not None:
            try:
                await self.room_codes.retire_ephemeral(removed.code)
            except Exception:
                # The active reservation remains claimed on failure, which is
                # safer than making a stale invite join an unrelated room.
                logger.exception("Failed to retire an ephemeral room code")
        return True
