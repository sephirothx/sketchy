"""Shared dependencies passed to every Socket.IO handler domain."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import socketio

from app.repositories.interfaces import (
    GameHistoryRepository,
    UserRepository,
    WordListRepository,
)
from app.rooms import RoomManager
from app.services.timers import TimerManager

if TYPE_CHECKING:
    from app.services.game_flow import GameFlowService


@dataclass
class HandlerContext:
    """Application-owned state used by the Socket.IO transport adapters."""

    sio: socketio.AsyncServer
    room_manager: RoomManager
    timers: TimerManager = field(default_factory=TimerManager)
    user_repo: UserRepository | None = None
    game_history_repo: GameHistoryRepository | None = None
    word_list_repo: WordListRepository | None = None
    jwt_secret_getter: Any = None
    game_flow: GameFlowService = field(init=False)
