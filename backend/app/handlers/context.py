"""Shared dependencies passed to every Socket.IO handler domain."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import socketio

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
    game_flow: GameFlowService = field(init=False)
