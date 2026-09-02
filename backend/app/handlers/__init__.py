"""Wire all Socket.IO handler domains onto a server."""
from __future__ import annotations

import socketio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.handlers import (
    chat,
    connection,
    drawing,
    friends,
    game,
    lobby,
    moderation,
    restart,
    rooms,
)
from app.auth.blocks import BlockService
from app.handlers.context import HandlerContext
from app.repositories.interfaces import (
    GameHistoryRepository,
    UserRepository,
    PromptListRepository,
)
from app.rooms import RoomManager
from app.services.game_flow import GameFlowService
from app.services.friend_invites import FriendInviteBook
from app.services.friends import FriendService
from app.services.message_retention import MessageRetentionService
from app.services.presence import (
    DEFAULT_MAX_CACHED_IDENTITIES,
    PresenceBroadcaster,
    PresenceIdentityCache,
    PresenceRegistry,
)
from app.services.room_codes import RoomCodeService
from app.services.room_quotas import RoomCapacityService, RoomQuotaService
from app.services.timers import TimerManager
from app.services.shutdown import ShutdownCoordinator


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
    friend_service: FriendService | None = None,
    shutdown: ShutdownCoordinator | None = None,
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
        friend_service=(
            friend_service
            if friend_service is not None
            else FriendService(session_factory)
            if session_factory is not None
            else None
        ),
        shutdown=shutdown,
    )
    ctx.game_flow = GameFlowService(ctx)
    # Built even without a database: the live-room ceilings are answered from
    # memory, and only the creation *rate* needs a persistent bucket.
    ctx.room_quotas = RoomQuotaService(room_manager, session_factory)
    ctx.room_capacity = RoomCapacityService()
    # Also built without a database: presence is answered entirely from
    # memory, and only the name beside each row needs one - which is why the
    # cache tolerates having no repository at all rather than refusing.
    ctx.presence = PresenceRegistry()
    # Sized from the socket ceiling, not a constant: every account that can be
    # online at once has to fit, or the identity cache evicts rows the next
    # tick immediately reads back.
    ctx.presence_identities = PresenceIdentityCache(
        user_repo,
        max_cached=max(DEFAULT_MAX_CACHED_IDENTITIES, ctx.room_capacity.sockets),
    )
    ctx.presence_broadcaster = PresenceBroadcaster(
        sio, ctx.presence, ctx.presence_identities, room_manager
    )
    ctx.friend_invites = FriendInviteBook()

    moderation.register(ctx)
    restart.register(ctx)
    rooms.register(ctx)
    chat.register(ctx)
    drawing.register(ctx)
    game.register(ctx)
    friends.register(ctx)
    lobby.register(ctx)
    connection.register(ctx)
    return ctx
