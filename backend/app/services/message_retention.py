"""Short-lived persistence for audience-aware player-authored messages."""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
import logging
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import RoomMessage
from app.identifiers import generate_uuid7


MESSAGE_RETENTION = timedelta(days=30)
CLEANUP_INTERVAL = timedelta(hours=1)
# Deep enough to ride out a slow write without ever being the reason a room
# goes quiet, shallow enough that a database that has stopped answering costs
# bounded memory rather than growing until the process dies.
QUEUE_DEPTH = 2000
WRITE_BATCH = 100
WRITE_TIMEOUT_SECONDS = 10
SHUTDOWN_DRAIN_SECONDS = 5

logger = logging.getLogger(__name__)


async def purge_expired_room_messages(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
) -> int:
    """Delete ordinary messages after their bounded retention window.

    Report evidence is a separate copied row, so this operation can never
    erase content already selected for moderator review.
    """
    cutoff = now or datetime.now(timezone.utc)
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                delete(RoomMessage).where(RoomMessage.expires_at <= cutoff)
            )
            return int(result.rowcount or 0)


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
    ) -> None:
        self._session_factory = session_factory
        self._last_cleanup_at: datetime | None = None
        self._queue: asyncio.Queue[RoomMessage] = asyncio.Queue(maxsize=queue_depth)
        self._batch_size = batch_size
        self._worker: asyncio.Task[None] | None = None

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
        return str(row.id)

    def _ensure_worker(self) -> None:
        """Start the writer, or replace one that somehow stopped."""

        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._write_queued())

    async def _write_queued(self) -> None:
        """Write what is waiting, in batches, for as long as anything is.

        Batched because the alternative is a transaction per message, and a
        busy room is the case that matters. Every failure is survived except
        cancellation: one bad batch must not stop every later message.
        """
        while True:
            batch = [await self._queue.get()]
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
                # Dropped or written, the batch is no longer outstanding -
                # without this a failed write would hang every `drain`.
                for _ in batch:
                    self._queue.task_done()

    async def _write(self, batch: list[RoomMessage]) -> None:
        now = batch[-1].created_at
        async with self._session_factory() as session:
            async with session.begin():
                session.add_all(batch)
                if (
                    self._last_cleanup_at is None
                    or now - self._last_cleanup_at >= CLEANUP_INTERVAL
                ):
                    await session.execute(
                        delete(RoomMessage).where(RoomMessage.expires_at <= now)
                    )
                    self._last_cleanup_at = now

    async def drain(self) -> None:
        """Wait for everything taken so far to have been dealt with."""

        if self._worker is None:
            return
        await self._queue.join()

    async def aclose(self) -> None:
        """Write what is still waiting, then stop - bounded, on the way out.

        A shutdown that waits indefinitely for a database that has stopped
        answering is a shutdown that does not happen, so the drain is given a
        few seconds and the rest is lost knowingly.
        """
        worker = self._worker
        if worker is None:
            return
        self._worker = None
        try:
            await asyncio.wait_for(self._queue.join(), timeout=SHUTDOWN_DRAIN_SECONDS)
        except asyncio.TimeoutError:
            logger.error(
                "Gave up retaining %d queued messages at shutdown",
                self._queue.qsize(),
            )
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
