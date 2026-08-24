"""Shared dependencies passed to every Socket.IO handler domain."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING

import socketio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.interfaces import (
    GameHistoryRepository,
    UserRepository,
    PromptListRepository,
)
from app.rooms import RoomManager
from app.services.timers import TimerManager

if TYPE_CHECKING:
    from app.auth.blocks import BlockService
    from app.services.game_flow import GameFlowService
    from app.services.message_retention import MessageRetentionService
    from app.services.room_codes import RoomCodeService
    from app.services.persistent_rooms import PersistentRoomService
    from app.services.shutdown import ShutdownCoordinator


logger = logging.getLogger("sketchy.handlers.context")


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
    persistent_rooms: PersistentRoomService | None = None
    shutdown: ShutdownCoordinator | None = None
    game_flow: GameFlowService = field(init=False)

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
        if self.room_codes is not None and removed.persistent_room_id is None:
            try:
                await self.room_codes.retire_ephemeral(removed.code)
            except Exception:
                # The active reservation remains claimed on failure, which is
                # safer than making a stale invite join an unrelated room.
                logger.exception("Failed to retire an ephemeral room code")
        return True
