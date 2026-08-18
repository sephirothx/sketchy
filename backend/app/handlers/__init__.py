"""Wire all Socket.IO handler domains onto a server."""
from __future__ import annotations

from collections.abc import Callable

import socketio

from app.handlers import chat, connection, drawing, game, moderation, restart, rooms
from app.handlers.context import HandlerContext
from app.repositories.interfaces import (
    GameHistoryRepository,
    UserRepository,
    WordListRepository,
)
from app.rooms import RoomManager
from app.services.game_flow import GameFlowService
from app.services.timers import TimerManager


def register_all_handlers(
    sio: socketio.AsyncServer,
    room_manager: RoomManager,
    *,
    timers: TimerManager | None = None,
    user_repo: UserRepository | None = None,
    game_history_repo: GameHistoryRepository | None = None,
    word_list_repo: WordListRepository | None = None,
    jwt_secret_getter: Callable[[], str] | None = None,
) -> HandlerContext:
    """Create the shared context and register every domain exactly once."""
    ctx = HandlerContext(
        sio=sio,
        room_manager=room_manager,
        timers=timers if timers is not None else TimerManager(),
        user_repo=user_repo,
        game_history_repo=game_history_repo,
        word_list_repo=word_list_repo,
        jwt_secret_getter=jwt_secret_getter,
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
