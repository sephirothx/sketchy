"""Short-lived persistence for audience-aware player-authored messages."""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
import logging
import time
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.telemetry import database_operation_of, telemetry
from app.auth.erasure import erased_identity_ids
from app.services.sweeps import (
    SweepBudget,
    SweepReport,
    delete_in_batches,
    overdue_probe,
    sweep_budget_from_env,
)
from app.db.models import RoomMessage
from app.identifiers import generate_uuid7


MESSAGE_RETENTION = timedelta(days=30)
# Deep enough to ride out a slow write without ever being the reason a room
# goes quiet, shallow enough that a database that has stopped answering costs
# bounded memory rather than growing until the process dies.
QUEUE_DEPTH = 2000
WRITE_BATCH = 100
# How long the writer waits after the first line of a batch for the rest of it
# (#972). Taking only what was already queued made a batch of one: rooms talk
# a line at a time, never two in the same instant, so the load gate wrote 2,885
# lines in 2,874 transactions - each an insert plus the erasure barrier's two
# reads, half of every statement the process ran. Delivery never waited on
# this write; the one reader that cannot wait out the linger - a report citing
# a line said a moment ago - flushes the queue first (`flush`).
WRITE_LINGER_SECONDS = 0.25
WRITE_TIMEOUT_SECONDS = 10
# How long a report waits for queued lines to be written before reading its
# evidence; past it the report reads what is there, as before batching.
EVIDENCE_FLUSH_SECONDS = 2
SHUTDOWN_DRAIN_SECONDS = 5

logger = logging.getLogger(__name__)


async def purge_expired_room_messages(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    budget: SweepBudget | None = None,
) -> SweepReport:
    """Delete ordinary messages after their bounded retention window.

    Report evidence is a separate copied row, so this operation can never
    erase content already selected for moderator review. Batched and budgeted
    (`services.sweeps`): oldest expiry first, one committed batch at a time,
    never inside anybody's insert.
    """
    cutoff = now or datetime.now(timezone.utc)
    return await delete_in_batches(
        session_factory,
        name="room_messages",
        candidates=select(RoomMessage.id)
        .where(RoomMessage.expires_at <= cutoff)
        .order_by(RoomMessage.expires_at, RoomMessage.id),
        delete_for=lambda ids: delete(RoomMessage).where(RoomMessage.id.in_(ids)),
        budget=budget or sweep_budget_from_env(),
        probe=overdue_probe(RoomMessage.expires_at, RoomMessage.expires_at <= cutoff),
        now=cutoff,
    )


class MessageRetentionService:
    """Persist accepted player text without making chat delivery depend on it.

    That sentence used to describe the intent and not the code: `record` awaited
    a transaction, so every message in every room waited for the database, and
    a lock or a slow disk became chat latency for everyone. The row is composed
    on the spot - it is a snapshot of live state, and a moment later the room
    has moved on - and then handed to a worker that writes it.

    What the caller gets back is the identifier, not a promise that the write
    landed. That identifier is what lets a player select the line as report
    evidence later; if the write never lands, the report is refused with the
    "unavailable" answer the moderation API already gives for a message past
    its retention window.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        queue_depth: int = QUEUE_DEPTH,
        batch_size: int = WRITE_BATCH,
        linger_seconds: float = WRITE_LINGER_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._queue: asyncio.Queue[RoomMessage] = asyncio.Queue(maxsize=queue_depth)
        self._batch_size = batch_size
        self._linger_seconds = linger_seconds
        self._worker: asyncio.Task[None] | None = None
        # Cuts a linger short: set when a full batch is waiting, and for as
        # long as anybody is draining - a caller waiting for the queue to
        # empty is not a reason to hold lines back.
        self._wake = asyncio.Event()
        self._draining = 0
        # How many rows have been taken, and how many have been dealt with:
        # `flush` waits for the ones already queued when it was called, not
        # for whatever other rooms say while it waits (#972 review).
        self._enqueued = 0
        self._written = 0
        # Woken whenever a batch has been dealt with. An event rather than a
        # condition because a worker being cancelled settles its batch too,
        # and there is no lock to take there.
        self._progress = asyncio.Event()
        # How far a waiting reader needs the queue written. State the writer
        # reads, not a signal it can clear: a flush that lands before the
        # writer reaches its linger used to lose the cut and pay the whole
        # window - 254 ms where the wait should have been 3 (#972 third
        # review).
        self._cut = 0
        # How many readers are waiting on that cut right now.
        self._flushing = 0
        # Set once `aclose` starts: no new line, and so no new writer.
        self._closing = False

    async def record(
        self,
        *,
        room,
        player,
        text: str,
        message_kind: str,
        audience: str,
        recipient_sids: list[str],
        near_miss_kind: str | None = None,
    ) -> str | None:
        """Take one accepted message for retention and return its UUIDv7.

        Returns without waiting for the database. ``None`` means this line will
        not be retained and the client is told so by the absence of the
        identifier, exactly as it was when a failed write returned ``None``:
        either the message is not the kind that is kept, or so much is already
        waiting to be written that taking more would cost memory instead of
        buying evidence.
        """
        game = room.game
        game_id = game.id if game is not None else None
        turn_id = game.current_turn_id if game is not None else None
        if message_kind != "chat" and (not game_id or not turn_id):
            return None

        # Composed here rather than in the worker: every field below is a
        # snapshot of live state - who was in the room, what they were called,
        # which turn was running - and by the time the row is written the room
        # has moved on.
        recipients = {
            candidate.user_id
            for candidate in room.players.values()
            if candidate.sid in recipient_sids and candidate.user_id
        }
        message_id = generate_uuid7()
        now = datetime.now(timezone.utc)
        row = RoomMessage(
            id=message_id,
            room_instance_id=UUID(room.retention_scope_id),
            game_id=UUID(game_id) if game_id else None,
            turn_id=UUID(turn_id) if turn_id else None,
            sender_user_id=(UUID(player.user_id) if player.user_id else None),
            sender_player_id=UUID(player.id),
            sender_seat_id=(
                UUID(game.history_seat_ids[player.id])
                if game is not None and player.id in game.history_seat_ids
                else None
            ),
            sender_display_name_snapshot=player.nickname,
            sender_name_color_snapshot=player.name_color,
            sender_is_anonymous_snapshot=player.is_anonymous,
            is_spectator=player.is_spectator,
            message_kind=message_kind,
            audience=audience,
            audience_user_ids=sorted(recipients),
            near_miss_kind=near_miss_kind,
            text=text,
            created_at=now,
            expires_at=now + MESSAGE_RETENTION,
        )
        return self._enqueue(row, f"for game {game_id} turn {turn_id}")

    async def record_lobby(
        self,
        *,
        user_id: str,
        display_name: str,
        name_color: str | None,
        is_anonymous: bool,
        text: str,
        sent_at: datetime,
    ) -> str | None:
        """Take one lobby line for retention and return its UUIDv7.

        The same bargain as `record`, for a line with no room and no seat: the
        row is composed now from what the lobby knows about its author and
        written later. The audience is the lobby itself - everybody with one
        open - so no recipient list is kept; the moderation API reads the
        audience value instead of the list when deciding who may cite it.
        """
        try:
            sender = UUID(user_id)
        except ValueError:
            logger.warning("Lobby line by %r has no account id; not kept", user_id)
            return None
        row = RoomMessage(
            id=generate_uuid7(),
            room_instance_id=None,
            game_id=None,
            turn_id=None,
            sender_user_id=sender,
            sender_player_id=None,
            sender_seat_id=None,
            sender_display_name_snapshot=display_name,
            sender_name_color_snapshot=name_color,
            sender_is_anonymous_snapshot=is_anonymous,
            is_spectator=False,
            message_kind="chat",
            audience="lobby",
            audience_user_ids=[],
            near_miss_kind=None,
            text=text,
            created_at=sent_at,
            expires_at=sent_at + MESSAGE_RETENTION,
        )
        return self._enqueue(row, "from the lobby")

    def _enqueue(self, row: RoomMessage, described: str) -> str | None:
        """Hand one composed row to the writer, or say why it will not be kept."""
        if self._closing and (self._worker is None or self._worker.done()):
            # The writer has stopped and this is a shutdown: starting another
            # would outlive it, and the count it kept would be wrong for the
            # one that did the work (#972 fifth review). While the writer is
            # still draining, a line is taken as it always was - the drain
            # exists so that the last thing anybody said is written rather
            # than abandoned (#972 sixth review).
            logger.warning("Retention is closing; message %s %s is not kept", row.id, described)
            return None
        self._ensure_worker()
        try:
            self._queue.put_nowait(row)
        except asyncio.QueueFull:
            # The database has stopped keeping up. Chat is not the place to
            # find that out, so the line goes out unretained and the log is
            # where it is said.
            logger.warning(
                "Retention queue is full; message %s %s is not kept",
                row.id,
                described,
            )
            return None
        self._enqueued += 1
        if self._queue.qsize() >= self._batch_size - 1:
            # The line the writer holds plus these fill a batch: write now.
            self._wake.set()
        return str(row.id)

    def _ensure_worker(self) -> None:
        """Start the writer, or replace one that somehow stopped."""

        if self._worker is None or self._worker.done():
            # No reconciliation here: `_write_queued` settles its batch in a
            # `finally`, so every way a writer can end - a bad batch, a
            # cancellation, an exception out of the linger - has already
            # accounted for the rows it held (#972 sixth review). The count
            # this used to repair is always zero, and a block that can only
            # ever subtract nothing is worse than no block.
            self._worker = asyncio.create_task(self._write_queued())

    async def _write_queued(self) -> None:
        """Write what is waiting, in batches, for as long as anything is.

        Batched because the alternative is a transaction per message, and a
        busy room is the case that matters. A batch is what arrived within
        `WRITE_LINGER_SECONDS` of its first line, not only what happened to be
        queued already - which, a line at a time, was nothing. Every failure is
        survived except cancellation: one bad batch must not stop every later
        message.
        """
        while True:
            batch = [await self._queue.get()]
            try:
                await self._linger()
                while len(batch) < self._batch_size:
                    try:
                        batch.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                try:
                    await asyncio.wait_for(
                        self._write(batch), timeout=WRITE_TIMEOUT_SECONDS
                    )
                except asyncio.TimeoutError:
                    logger.error(
                        "Timed out retaining %d messages after %ss",
                        len(batch),
                        WRITE_TIMEOUT_SECONDS,
                    )
                except Exception:
                    logger.exception("Failed to retain %d messages", len(batch))
            finally:
                # Written, dropped or cancelled: these rows have left the
                # queue, and a batch nobody accounts for hangs every later
                # `drain` on `join()` and leaves every later `flush` waiting
                # its whole bound for a row no one will write (#972 third
                # review). A `finally` rather than an `except`, because there
                # is no path where they are still outstanding.
                self._settle(batch)

    def _settle(self, batch: list[RoomMessage]) -> None:
        """Account for a batch that has left the queue, written or not.

        Dropped, written or lost, it is no longer outstanding - without this a
        failed write would hang every `drain`.
        """
        for _ in batch:
            self._queue.task_done()
        self._written += len(batch)
        # Whoever is waiting is woken now; anybody arriving later reads the
        # counters first and waits for the next batch.
        self._progress.set()
        self._progress.clear()

    async def _linger(self) -> None:
        """Give the rest of a batch a moment to arrive, unless it is already
        here or somebody is waiting for the queue to empty."""
        if (
            self._linger_seconds <= 0
            or self._draining
            or self._cut > self._written
            or self._queue.qsize() >= self._batch_size - 1
        ):
            return
        self._wake.clear()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout=self._linger_seconds)

    @database_operation_of("message_batch")
    async def _write(self, batch: list[RoomMessage]) -> None:
        """Insert one batch. Only insert: the expiry purge is the retention
        sweep's, on its own schedule and budget, so a purge backlog can never
        be the reason a room's lines are dropped (#550)."""
        async with self._session_factory() as session:
            async with session.begin():
                # The erasure barrier (app.auth.erasure): a line was composed
                # with its author's name and text a moment ago, and the
                # account may have been deleted since. Re-read under the
                # shared lock and drop what an erased account said, rather
                # than storing again what the deletion just removed.
                erased = await erased_identity_ids(
                    session,
                    (row.sender_user_id for row in batch if row.sender_user_id),
                )
                kept = [row for row in batch if row.sender_user_id not in erased]
                if len(kept) < len(batch):
                    logger.info(
                        "Dropped %d queued messages by erased accounts",
                        len(batch) - len(kept),
                    )
                session.add_all(kept)
        # Counted once committed (#895): how much is kept, of which kind, and
        # for how many recipients - the number #545 turned on, now measured
        # rather than scanned for.
        for row in kept:
            telemetry.message_retained(
                row.message_kind, row.audience, len(row.audience_user_ids or ())
            )

    async def drain(self) -> None:
        """Wait for everything taken so far to have been dealt with."""

        if self._worker is None:
            return
        self._draining += 1
        self._wake.set()
        try:
            await self._queue.join()
        finally:
            self._draining -= 1

    async def flush(self) -> None:
        """Write the lines queued right now, for a reader that needs them.

        Report evidence reads `room_messages` directly, and a line still
        inside the writer's linger would be missing from it (#972 review).
        Only what is already queued is waited for - a busy server keeps
        lingering for everyone else meanwhile - and the wait is bounded, so a
        database that has stopped answering cannot hold a report up.
        """
        target = self._enqueued
        if self._written >= target:
            return
        # Both, because the writer may be either side of its linger: the cut
        # is what it reads before waiting, the event what wakes it if it is
        # already waiting. Assigned rather than raised to the maximum: a later
        # reader's target is never lower than an earlier one's, since it is
        # `_enqueued` and that only grows, and the only thing that lowers the
        # cut is the reset below, which runs when nobody is waiting.
        self._cut = target
        self._wake.set()
        self._flushing += 1
        deadline = time.monotonic() + EVIDENCE_FLUSH_SECONDS
        try:
            while self._written < target:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._progress.wait(), timeout=remaining)
        finally:
            self._flushing -= 1
            if not self._flushing:
                # Nobody is waiting any more. Left standing, a cut nothing
                # reached - a flush that gave up on a stalled database - would
                # go on suppressing the linger for every room until the writer
                # caught up with it (#972 fourth review).
                self._cut = self._written
        if self._written < target:
            logger.warning(
                "Retention queue not flushed within %ss for a report", EVIDENCE_FLUSH_SECONDS
            )

    async def aclose(self) -> None:
        """Write what is still waiting, then stop - bounded, on the way out.

        A shutdown that waits indefinitely for a database that has stopped
        answering is a shutdown that does not happen, so the drain is given a
        few seconds and the rest is lost knowingly.
        """
        worker = self._worker
        self._closing = True
        if worker is None:
            return
        # Still `self._worker` while the drain runs: cleared any earlier and a
        # line recorded during it starts a second writer, which nothing then
        # cancels and which the lost-row reconciliation cannot account for
        # (#972 fourth review).
        self._draining += 1
        self._wake.set()
        try:
            await asyncio.wait_for(self._queue.join(), timeout=SHUTDOWN_DRAIN_SECONDS)
        except asyncio.TimeoutError:
            logger.error(
                "Gave up retaining %d queued messages at shutdown",
                self._queue.qsize(),
            )
        finally:
            self._draining -= 1
        worker.cancel()
        # Cleared on the next line, with no await in between, and it must stay
        # that way: `_enqueue` takes a line while a worker is alive, so any
        # suspension point between the cancel and this clear is a window where
        # a line is given an identifier - which a report may later cite - and
        # written by nobody (#972 seventh review).
        self._worker = None
        with contextlib.suppress(asyncio.CancelledError):
            await worker
