"""Shared dependencies passed to every Socket.IO handler domain."""
from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
import logging
from time import perf_counter
from typing import AsyncIterator, Iterable, Iterator, TYPE_CHECKING

import socketio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import correlation
from app.repositories.interfaces import (
    GameHistoryRepository,
    UserRepository,
    PromptListRepository,
)
from app.domain_values import RuntimeEventType
from app.handlers.refusals import ErrorCode, refuse
from app.live_drawing import frame_kind
from app.protocol import PROTOCOL_VERSION, stale_client_bucket
from app.handlers.budgets import SILENT_COMMANDS, CommandBudgetPolicy, CommandBudgets
from app.rooms import RoomManager
from app.services.afk import INACTIVITY_EXEMPT_COMMANDS, ActivityLedger
from app.services.runtime_metrics import metrics
from app.services.telemetry import payload_bytes, telemetry
from app.services.timers import TimerManager

if TYPE_CHECKING:
    from app.auth.blocks import BlockService
    from app.services.afk import AfkWatch
    from app.services.game_flow import GameFlowService
    from app.services.game_handoff import FinishedGameHandoffWorker
    from app.services.friend_invites import FriendInviteBook
    from app.services.friends import FriendService
    from app.services.lobby_chat import LobbyChatLog
    from app.services.message_retention import MessageRetentionService
    from app.services.friend_presence import FriendPresence
    from app.services.presence import (
        LobbyBroadcaster,
        PresenceIdentityCache,
        PresenceRegistry,
    )
    from app.services.room_codes import RoomCodeService
    from app.services.room_quotas import RoomCapacityService, RoomQuotaService
    from app.services.shutdown import ShutdownCoordinator


_ERROR_CODES = frozenset(code.value for code in ErrorCode)


def _note_door_refusal(command: str, code: ErrorCode, frame_result: str, args: tuple) -> None:
    """A command refused before its handler ran (#882): counted by its code
    like any other refusal, and a `draw` frame counted in the frame mix too,
    so the mix does not lose exactly the frames a saturated drawer sends."""
    telemetry.note_refusal(command, code.value)
    if command == "draw":
        telemetry.note_draw_frame(*frame_kind(args[0] if args else None), frame_result)

logger = logging.getLogger("sketchy.handlers.context")

# How long retiring a torn-down room's invite code may take (#879). The same ten
# seconds every other write on these paths is allowed.
ROOM_CODE_RETIRE_TIMEOUT_SECONDS = 10


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
    # Where a finished game goes (#541): staged whole, replayed into the two
    # repositories above by the worker's loop. None means no history at all.
    finished_games: FinishedGameHandoffWorker | None = None
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
    presence_broadcaster: LobbyBroadcaster = field(init=False)
    friend_presence: "FriendPresence" = field(init=False)
    # The last few lobby lines, for an arrival; an event stream rather than a
    # feed of the broadcaster's, so it lives beside it rather than inside it.
    lobby_chat: LobbyChatLog = field(init=False)
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
    # Sockets told to upgrade and not yet gone (#476): the version each one
    # claimed, and the task that closes it if it does not reload in time.
    _stale_sockets: dict[str, tuple[int, asyncio.Task | None]] = field(
        default_factory=dict, init=False, repr=False
    )
    # Sockets whose last `draw` frame was dropped at the door (throttled).
    # Nobody awaits a frame, so the drop is silent here; the drawing handler
    # reads this on the next frame and closes the path the drop tore a hole
    # in (#559), so that nothing is ever resolved against a point the server
    # never recorded.
    dropped_draw_frames: set[str] = field(default_factory=set, init=False, repr=False)
    # The last `create_room` each account made, by its request id (#879):
    # account -> (request id, room id, monotonic expiry). One entry per
    # account, pruned on every write, so it is bounded by active creators.
    recent_room_creations: dict[str, tuple[str, str, float]] = field(
        default_factory=dict, init=False, repr=False
    )
    # And those still being made, by (account, request id), so a copy of the
    # same press on another socket waits for the first rather than racing it.
    room_creations_in_flight: dict[tuple[str, str], asyncio.Future] = field(
        default_factory=dict, init=False, repr=False
    )
    # The durable half of teardowns an entry started (#879), running on their
    # own so the entry does not wait on them; drained at shutdown.
    room_cleanups: set[asyncio.Task] = field(default_factory=set, init=False, repr=False)
    # Guesses being handled, by (sid, guess id), until they are answered: a
    # retry of one still in flight waits for its answer (#884).
    guesses_in_flight: dict[tuple[str, int], asyncio.Future] = field(
        default_factory=dict, init=False, repr=False
    )
    # When each socket last did something a person did, and the sweep that
    # asks the quiet ones whether anybody is there (#677). The ledger is
    # written below, at the one door every command passes through; the watch
    # reads it on its own tick.
    activity: ActivityLedger = field(
        default_factory=ActivityLedger, init=False, repr=False
    )
    afk_watch: AfkWatch = field(init=False, repr=False)

    def on(self, command: str, handler) -> None:
        """Register a client command, with the budget it answers to.

        Every client-originated command goes through here rather than through
        `sio.on` directly, so that adding one cannot quietly add an unbounded
        one. `test_command_budgets.py` checks the two lists against each other.
        """

        # Every command takes one payload; `draw` may add its action identity.
        # More than that is not a call this handler can make, and it must be
        # refused here, bounded, rather than surface as a TypeError inside
        # python-socketio (#596).
        max_args = 2 if command == "draw" else 1

        async def guarded(sid, *args):
            # Every line logged underneath names the socket, the command and
            # a fresh id for this one invocation, the way a request does.
            # Task-local: python-socketio runs each handler in its own task.
            correlation.socket_sid.set(sid)
            correlation.socket_event.set(command)
            correlation.request_id.set(correlation.new_request_id())
            if len(args) > max_args:
                telemetry.socket_event(command, "refused", None)
                _note_door_refusal(command, ErrorCode.INVALID_PAYLOAD, "invalid", args)
                if command in SILENT_COMMANDS:
                    return None
                return refuse(ErrorCode.INVALID_PAYLOAD, "Invalid request payload")
            # A socket told to upgrade is held to it here, at the one door
            # every command uses (#476): nothing it says is parsed, let alone
            # acted on, because its payloads are of a contract this server
            # does not speak. The notice already carried the way out.
            stale = self._stale_sockets.get(sid)
            if stale is not None:
                telemetry.socket_event(command, "refused", None)
                _note_door_refusal(command, ErrorCode.PROTOCOL_MISMATCH, "refused", args)
                if command in SILENT_COMMANDS:
                    return None
                return refuse(
                    ErrorCode.PROTOCOL_MISMATCH,
                    "This tab is running an older version of Sketchy. "
                    "Reload the page to continue.",
                    expected=PROTOCOL_VERSION,
                    received=stale[0],
                )
            # A person did something. Stamped before the budget check on
            # purpose: a command refused for arriving too fast still came from
            # somebody at the keyboard, and throttling them is not a reason to
            # start calling them absent. Exempt commands are the ones the
            # client sends on its own (#677).
            if command not in INACTIVITY_EXEMPT_COMMANDS:
                self.activity.note(sid)
            # Before parsing, before authorization, before any mutation: a
            # refused command must cost nothing but the check itself.
            budget = self.command_budgets.for_command(command)
            # Keyed by the kind of traffic, not the command: two commands of
            # one kind share the allowance their kind was given.
            key = f"{sid}:{self.command_budgets.class_of(command)}"
            # Sized before the budget check: a throttled payload arrived too.
            telemetry.socket_command_payload(command, payload_bytes(*args))
            if self._command_windows.check(key, budget):
                # Timed and counted here, at the one door every command
                # uses, so a handler cannot be added without being measured.
                # A refusal the handler chose (`ok: False`) is a different
                # outcome from an exception it did not, and the exception is
                # counted before it propagates rather than instead.
                started = perf_counter()
                try:
                    # One snapshot per room this command changed, sent when
                    # it is done (#880).
                    async with self._room_state_batch():
                        result = await handler(sid, *args)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    telemetry.socket_event(command, "error", perf_counter() - started)
                    raise
                refused = isinstance(result, dict) and result.get("ok") is False
                telemetry.socket_event(
                    command, "refused" if refused else "ok", perf_counter() - started
                )
                if refused:
                    # Which refusal (#882): `errorCode` is a closed enum, but
                    # it is read off a dict, so anything outside it is `other`
                    # rather than a new series.
                    code = result.get("errorCode")
                    telemetry.note_refusal(
                        command,
                        str(code) if isinstance(code, str) and code in _ERROR_CODES else "other",
                    )
                return result
            telemetry.socket_event(command, "throttled", None)
            _note_door_refusal(command, ErrorCode.TOO_FAST, "throttled", args)
            if self._command_windows.should_report(key, budget):
                logger.warning("throttled %s from %s", command, sid)
                metrics.record(
                    RuntimeEventType.COMMAND_THROTTLED, details={"command": command}
                )
            if command in SILENT_COMMANDS:
                # A frame nobody is waiting on. Answering would put an error on
                # screen in the middle of a stroke, about a frame the client
                # never expected a reply to. Remembered instead, for the
                # handler to act on at the next frame.
                self.dropped_draw_frames.add(sid)
                return None
            return {
                "ok": False, "errorCode": ErrorCode.TOO_FAST, "retryAfterMs": int(budget.window_seconds * 1000),
                "error": "You are doing that too quickly. Slow down a moment.",
            }

        self.sio.on(command, handler=guarded)

    def quarantine(
        self, sid: str, received: int, *, close_after: float
    ) -> None:
        """Hold a socket that was told to upgrade to it (#476).

        Every command from it is refused until it goes, and it is closed
        after `close_after` seconds if it has not gone by itself. The close
        is a task rather than a sleep in the handshake so the handshake
        answers at once and the reload the notice asked for is not waiting
        on it.
        """
        previous = self._stale_sockets.pop(sid, None)
        if previous is not None and previous[1] is not None:
            previous[1].cancel()

        async def close_later() -> None:
            try:
                await asyncio.sleep(close_after)
            except asyncio.CancelledError:
                return
            stale = self._stale_sockets.pop(sid, None)
            if stale is None:
                return
            # Popped before the close, so the disconnect it causes does not
            # count this socket a second time as one that reloaded.
            telemetry.note_stale_client(stale_client_bucket(stale[0]), "closed")
            logger.warning(
                "closing stale socket %s: told to upgrade %.0fs ago and still here",
                sid, close_after,
            )
            await self.sio.disconnect(sid)

        self._stale_sockets[sid] = (received, asyncio.create_task(close_later()))

    def _room_state_batch(self):
        """The command's room_state batch (#880), or no batch at all for a
        context built without a game flow - a bare one in a test."""
        game_flow = getattr(self, "game_flow", None)
        return game_flow.room_state_batch() if game_flow is not None else contextlib.nullcontext()

    def is_stale(self, sid: str) -> bool:
        """Whether this socket was told to upgrade and has not gone yet."""
        return sid in self._stale_sockets

    def release_stale(self, sid: str, *, closed_by_server: bool = False) -> None:
        """Forget a stale socket, cancelling its close: it has gone.

        `reloaded` means it left by itself before the close came due - the
        reload the notice asked for, or the tab going. A socket another server
        path closed first (a suspension, a superseded seat) did not reload,
        and counts as `closed` like one the quarantine timer closed.
        """
        stale = self._stale_sockets.pop(sid, None)
        if stale is None:
            return
        telemetry.note_stale_client(
            stale_client_bucket(stale[0]), "closed" if closed_by_server else "reloaded"
        )
        if stale[1] is not None:
            stale[1].cancel()

    def allow_canvas_notice(self, sid: str) -> bool:
        """At most one recovery notice per socket per resync window.

        A burst of refused frames is one fact - this client needs to resync -
        and one notice says it; the rest of the burst is dropped in silence
        and counted (#562).
        """
        budget = self.command_budgets.for_command("request_sync_strokes")
        return self._command_windows.check(f"{sid}:canvas_notice", budget)

    def clear_command_budget(self, sid: str) -> None:
        """Forget a socket that has gone, so the windows do not outlive it."""

        self._command_windows.forget(sid)
        self.dropped_draw_frames.discard(sid)

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

    async def remove_room_if_empty(self, room_id: str, *, defer_durable: bool = False) -> bool:
        """Remove an empty live room and retire its published invite code.

        `defer_durable` is for a teardown an entry causes by leaving its old
        room (#879): the room leaves memory now, and the writes that follow -
        the abandoned game, the code retirement - run as a task of their own,
        so neither can hold the entry past its deadline with the seating gate
        pinned. Neither is safe to cut short instead: a staging cancelled
        halfway loses the game, a retirement cancelled leaves the code claimed.
        """

        removed = self.room_manager.remove_room_if_empty(room_id)
        if removed is None:
            return False
        if defer_durable:
            self.defer_cleanup(self._retire_removed_room(removed))
            return True
        await self._retire_removed_room(removed)
        return True

    def defer_cleanup(self, coroutine) -> None:
        """Run a durable cleanup an entry caused on its own, tracked (#879).

        The entry has a deadline and holds the socket's seating gate; these
        writes have neither, and cutting one short is worse than letting it
        run - a staging cancelled halfway loses the game, a retirement
        cancelled leaves the code claimed. So they are handed here instead.
        """
        task = asyncio.create_task(coroutine)
        self.room_cleanups.add(task)
        task.add_done_callback(self.room_cleanups.discard)

    async def _retire_removed_room(self, removed) -> None:
        # A room can be torn down while it still holds a game: the last player
        # to be evicted takes the room with them, and that path never reaches
        # `_remove_player_from_game`. This is the one place every teardown
        # passes through, so it is where a lost game gets written down.
        await self.game_flow.record_abandoned_game(removed)
        if self.room_codes is not None:
            try:
                # Bounded like the history staging above it: a retirement
                # that never answers must not hold a teardown for ever.
                await asyncio.wait_for(
                    self.room_codes.retire_ephemeral(removed.code),
                    timeout=ROOM_CODE_RETIRE_TIMEOUT_SECONDS,
                )
            except Exception:
                # The active reservation remains claimed on failure, which is
                # safer than making a stale invite join an unrelated room;
                # `retire_orphaned_ephemeral` reclaims it at the next start.
                logger.exception("Failed to retire an ephemeral room code")

    async def drain_room_cleanups(self, within_seconds: float) -> None:
        """Let deferred teardowns finish before the process stops."""
        if self.room_cleanups:
            await asyncio.wait(set(self.room_cleanups), timeout=within_seconds)
