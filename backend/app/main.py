"""ASGI entrypoint: mounts the Socket.IO server alongside a small FastAPI REST app."""
from contextlib import asynccontextmanager
from pathlib import Path

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.middleware.gzip import GZipMiddleware

from app.api.profiles import create_profile_router
from app.api.persistent_rooms import create_persistent_room_router
from app.api.room_presets import create_room_preset_router
from app.api.prompt_lists import create_prompt_list_router
from app.api.moderation import create_moderation_router
from app.api.user_settings import create_user_settings_router
from app.api.user_blocks import create_user_blocks_router
from app.auth.blocks import BlockService
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db import async_engine, async_session_factory, init_db
from app.db.seed import seed_prompt_lists
from app.deployment import validate_worker_topology
from app.handlers import register_all_handlers
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyPromptListRepository,
)
from app.state import room_manager
from app.services.message_retention import purge_expired_room_messages
from app.services.room_presets import RoomPresetService


class SPAStaticFiles(StaticFiles):
    """Serve the SPA for extensionless client routes while preserving real 404s."""

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            is_client_route = (
                exc.status_code == 404
                and not path.startswith("api/")
                and not Path(path).suffix
            )
            if not is_client_route:
                raise
            response = await super().get_response("index.html", scope)

        if path.startswith("assets/"):
            response.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable"
            )
        else:
            # HTML and non-fingerprinted files must revalidate so a new deploy is
            # discovered instead of leaving clients on a stale application shell.
            response.headers["Cache-Control"] = "no-cache"
        return response


def configure_frontend(app: FastAPI, directory: Path) -> None:
    """Enable static compression and mount the production frontend when present."""

    app.add_middleware(GZipMiddleware, minimum_size=500)
    if directory.is_dir():
        app.mount(
            "/",
            SPAStaticFiles(directory=str(directory), html=True),
            name="frontend",
        )


user_repo = SqlAlchemyUserRepository(async_session_factory)
game_history_repo = SqlAlchemyGameHistoryRepository(async_session_factory)
prompt_list_repo = SqlAlchemyPromptListRepository(async_session_factory)
block_service = BlockService(async_session_factory)
room_preset_service = RoomPresetService(async_session_factory, prompt_list_repo)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
handler_context = register_all_handlers(
    sio,
    room_manager,
    user_repo=user_repo,
    game_history_repo=game_history_repo,
    prompt_list_repo=prompt_list_repo,
    session_factory=async_session_factory,
    block_service=block_service,
)


async def _remove_account_from_live_rooms(user_id: str, *, reason: str) -> None:
    """End live seats immediately after an account loses access."""
    for room in list(room_manager.rooms.values()):
        if room.persistent_owner_user_id == user_id:
            room.persistent_room_id = None
            room.persistent_owner_user_id = None
            room.persistent_config_version = None
        player = room_manager.get_player_by_user_id(room, user_id)
        if player is None:
            continue
        player_id = player.id
        player_sid = player.sid
        handler_context.timers.cancel_disconnect_timer(player_id)
        room_manager.remove_player(room, player_id)
        if room.game and room.state == "playing":
            await handler_context.game_flow._remove_player_from_game(room, player_id)
        if player_sid:
            await sio.emit(
                "session_superseded",
                {"reason": reason},
                to=player_sid,
            )
            await sio.leave_room(player_sid, room.id)
            await sio.disconnect(player_sid)
        if room.connected_players():
            await handler_context.game_flow._emit_room_state(room)
        else:
            handler_context.timers.cancel_phase_timer(room.id)
            handler_context.timers.cancel_hint_timers(room.id)
            handler_context.timers.cancel_restart_timer(room.id)
            await handler_context.remove_room_if_empty(room.id)


async def remove_deleted_account_from_live_rooms(user_id: str) -> None:
    block_service.clear()
    await _remove_account_from_live_rooms(
        user_id, reason="Your account was deleted."
    )


async def remove_banned_account_from_live_rooms(user_id: str) -> None:
    await _remove_account_from_live_rooms(
        user_id, reason="Your account was suspended."
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        validate_worker_topology()
        await init_db()
        if handler_context.room_codes is not None:
            await handler_context.room_codes.retire_orphaned_ephemeral()
        await purge_expired_room_messages(async_session_factory)
        await seed_prompt_lists(prompt_list_repo)
        yield
    finally:
        await handler_context.timers.close()
        await async_engine.dispose()


api = FastAPI(title="Sketchy", lifespan=lifespan)
# No allow_credentials: the frontend is served from this same origin, so the
# session cookie rides along without CORS involvement. Turning credentials on
# alongside a wildcard origin is invalid anyway, and would be the only reason
# to need CSRF tokens on top of SameSite=Lax.
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
api.add_middleware(SessionAuthMiddleware, session_factory=async_session_factory)
api.include_router(
    create_auth_router(
        user_repo,
        async_session_factory,
        on_account_deleted=remove_deleted_account_from_live_rooms,
        on_identity_merged=block_service.clear,
    )
)
api.include_router(create_profile_router(user_repo, game_history_repo))
api.include_router(create_prompt_list_router(prompt_list_repo, user_repo))
api.include_router(create_user_settings_router(async_session_factory))
if handler_context.persistent_rooms is not None:
    api.include_router(create_persistent_room_router(handler_context.persistent_rooms))
api.include_router(create_room_preset_router(room_preset_service))
api.include_router(
    create_user_blocks_router(async_session_factory, block_service)
)
api.include_router(
    create_moderation_router(
        async_session_factory,
        on_user_banned=remove_banned_account_from_live_rooms,
    )
)


@api.get("/api/health")
async def health():
    return {"status": "ok"}


@api.get("/api/rooms")
async def list_public_rooms():
    return room_manager.list_public_rooms()


# In production, serve the built frontend as static files from the same origin
# (single-port self-hosting). No-op during development when the folder is absent.
_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
configure_frontend(api, _frontend_dist)

app = socketio.ASGIApp(sio, other_asgi_app=api, socketio_path="socket.io")
