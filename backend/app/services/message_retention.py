"""Short-lived persistence for audience-aware player-authored messages."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import RoomMessage
from app.identifiers import generate_uuid7


MESSAGE_RETENTION = timedelta(days=30)
CLEANUP_INTERVAL = timedelta(hours=1)

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
    """Persist accepted player text without making chat delivery depend on it."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._last_cleanup_at: datetime | None = None

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
        """Write one accepted message and return its durable UUIDv7.

        A storage failure is logged without message text or player names and
        returns ``None``. Live chat remains available; the missing identifier
        makes it explicit to clients that this line cannot be selected as
        server-retained report evidence.
        """
        game = room.game
        game_id = game.id if game is not None else None
        turn_id = game.current_turn_id if game is not None else None
        if message_kind != "chat" and (not game_id or not turn_id):
            return None

        recipients = {
            candidate.user_id
            for candidate in room.players.values()
            if candidate.sid in recipient_sids and candidate.user_id
        }
        message_id = generate_uuid7()
        now = datetime.now(timezone.utc)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add(
                        RoomMessage(
                            id=message_id,
                            room_instance_id=UUID(room.retention_scope_id),
                            game_id=UUID(game_id) if game_id else None,
                            turn_id=UUID(turn_id) if turn_id else None,
                            sender_user_id=(
                                UUID(player.user_id) if player.user_id else None
                            ),
                            sender_player_id=UUID(player.id),
                            sender_seat_id=(
                                UUID(game.history_seat_ids[player.id])
                                if game is not None
                                and player.id in game.history_seat_ids
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
                    )
                    if (
                        self._last_cleanup_at is None
                        or now - self._last_cleanup_at >= CLEANUP_INTERVAL
                    ):
                        await session.execute(
                            delete(RoomMessage).where(RoomMessage.expires_at <= now)
                        )
                        self._last_cleanup_at = now
        except Exception:
            logger.exception(
                "Failed to retain room message %s for game %s turn %s",
                message_id,
                game_id,
                turn_id,
            )
            return None
        return str(message_id)
