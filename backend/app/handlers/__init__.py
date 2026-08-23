"""Wire all Socket.IO handler domains onto a server."""
from __future__ import annotations

import socketio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.handlers import chat, connection, drawing, game, moderation, restart, rooms
from app.auth.blocks import BlockService
from app.handlers.context import HandlerContext
from app.repositories.interfaces import (
    GameHistoryRepository,
    UserRepository,
    PromptListRepository,
)
from app.rooms import RoomManager
from app.services.game_flow import GameFlowService
from app.services.message_retention import MessageRetentionService
from app.services.room_codes import RoomCodeService
from app.services.timers import TimerManager


def register_all_handlers(
    sio: socketio.AsyncServer,
    room_manager: RoomManager,
    *,
    timers: TimerManager | None = None,
    user_repo: UserRepository | None = None,
    game_history_repo: GameHistoryRepository | None = None,
    prompt_list_repo: PromptListRepository | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    block_service: BlockService | None = None,
) -> HandlerContext:
    """Create the shared context and register every domain exactly once."""
    ctx = HandlerContext(
        sio=sio,
        room_manager=room_manager,
        timers=timers if timers is not None else TimerManager(),
        user_repo=user_repo,
        game_history_repo=game_history_repo,
        prompt_list_repo=prompt_list_repo,
        session_factory=session_factory,
        block_service=(
            block_service
            if block_service is not None
            else BlockService(session_factory)
            if session_factory is not None
            else None
        ),
        message_retention=(
            MessageRetentionService(session_factory)
            if session_factory is not None
            else None
        ),
        room_codes=(
            RoomCodeService(session_factory)
            if session_factory is not None
            else None
        ),
    )
    ctx.game_flow = GameFlowService(ctx)

    moderation.register(ctx)
    restart.register(ctx)
    rooms.register(ctx)
    chat.register(ctx)
    drawing.register(ctx)
    game.register(ctx)
    connection.register(ctx)
    return ctx
