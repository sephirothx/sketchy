"""Shared dependencies passed to every Socket.IO handler domain."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
import logging
from typing import AsyncIterator, Iterable, Iterator, TYPE_CHECKING

import socketio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.interfaces import (
    GameHistoryRepository,
    UserRepository,
    PromptListRepository,
)
from app.domain_values import RuntimeEventType
from app.handlers.budgets import SILENT_COMMANDS, CommandBudgetPolicy, CommandBudgets
from app.rooms import RoomManager
from app.services.runtime_metrics import metrics
from app.services.timers import TimerManager

if TYPE_CHECKING:
    from app.auth.blocks import BlockService
    from app.services.game_flow import GameFlowService
    from app.services.friend_invites import FriendInviteBook
    from app.services.friends import FriendService
    from app.services.message_retention import MessageRetentionService
    from app.services.presence import (
        PresenceBroadcaster,
        PresenceIdentityCache,
        PresenceRegistry,
    )
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
    # Who is connected at all, as opposed to who is holding a seat. Built
    # here rather than in a handler module because the handshake writes it
    # and the lobby channel reads it, and neither owns it.
    presence: PresenceRegistry = field(init=False)
    presence_identities: PresenceIdentityCache = field(init=False)
    presence_broadcaster: PresenceBroadcaster = field(init=False)
    # Friendships are durable, so the service exists only where there is a
    # database; the invitations are live state and always exist.
    friend_service: FriendService | None = None
    friend_invites: FriendInviteBook = field(init=False)
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
    _ending_sockets: dict[str, int] = field(
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
            # Keyed by the kind of traffic, not the command: two commands of
            # one kind share the allowance their kind was given.
            key = f"{sid}:{self.command_budgets.class_of(command)}"
            if self._command_windows.check(key, budget):
                return await handler(sid, *args)
            if self._command_windows.should_report(key, budget):
                logger.warning("throttled %s from %s", command, sid)
                metrics.record(
                    RuntimeEventType.COMMAND_THROTTLED, details={"command": command}
                )
            if command in SILENT_COMMANDS:
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

    @contextmanager
    def ending(self, sids: Iterable[str]) -> Iterator[list[str]]:
        """Mark an account's sockets while its access is being taken away.

        Held across the whole sweep, and taken before its first await: every
        step of ending an account yields, closing a socket waits at that
        socket's seating gate, and an entry already holding one runs to
        completion first. Without the mark, the ban is applied to a seat
        created after the ban. With it, the entry refuses - and if the mark
        lands while it is already seating, it takes the seat back.

        Yields the sids it marked, so the sweep closes the same sockets it
        marked rather than a list re-read after several awaits.
        """

        marked = list(sids)
        for sid in marked:
            self._ending_sockets[sid] = self._ending_sockets.get(sid, 0) + 1
        try:
            yield marked
        finally:
            for sid in marked:
                remaining = self._ending_sockets.get(sid, 1) - 1
                if remaining <= 0:
                    self._ending_sockets.pop(sid, None)
                else:
                    self._ending_sockets[sid] = remaining

    def is_ending(self, sid: str) -> bool:
        """Whether this socket's account has just lost access."""

        return sid in self._ending_sockets

    async def evict_player(
        self, room, player_id: str, *, notice: tuple[str, dict] | None = None
    ) -> bool:
        """End one player's seat now, and tell them why before the socket goes.

        The sequence matters and is easy to get subtly wrong, which is why it
        is stated once rather than at each caller. The disconnect timer has to
        be cancelled or the grace period will try to evict a seat that is
        already gone; the game has to be told separately from the room,
        because a seat can be in one and not the other; the notice has to be
        emitted *before* the socket is closed, since a closed socket delivers
        nothing; and the room has to be either re-broadcast or torn down,
        because a room whose last player just left does not outlive them.

        `notice` is what to say, when there is anything to say. A player being
        removed for their own account's sake reads a different sentence from
        one an administrator closed a room around.
        """
        player = room.players.get(player_id)
        if player is None:
            return False
        player_sid = player.sid
        self.timers.cancel_disconnect_timer(player_id)
        self.room_manager.remove_player(room, player_id)
        if room.game and room.state == "playing":
            await self.game_flow._remove_player_from_game(room, player_id)
        if player_sid:
            if notice is not None:
                event, payload = notice
                await self.sio.emit(event, payload, to=player_sid)
            await self.sio.leave_room(player_sid, room.id)
            # Marked as ours, because it is: this server is ending the socket,
            # not the client. Socket.IO runs the disconnect handler inline from
            # here, and unmarked it would queue at that socket's seating gate -
            # pointless work, since the seat was removed above and there is
            # nothing left to reconcile, and a deadlock for any future caller
            # that reaches this while already holding that gate.
            with self.closing(player_sid):
                await self.sio.disconnect(player_sid)
        if room.connected_players():
            await self.game_flow._emit_room_state(room)
        else:
            self.timers.cancel_phase_timer(room.id)
            self.timers.cancel_hint_timers(room.id)
            self.timers.cancel_restart_timer(room.id)
            await self.remove_room_if_empty(room.id)
        return True

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
