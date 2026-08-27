"""ASGI entrypoint: mounts the Socket.IO server alongside a small FastAPI REST app."""
from contextlib import asynccontextmanager
from pathlib import Path

import hashlib
import json

import socketio

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.middleware.gzip import GZipMiddleware

from app.api.profiles import create_profile_router
from app.api.room_presets import create_room_preset_router
from app.api.prompt_lists import create_prompt_list_router
from app.api.bug_reports import create_bug_report_router
from app.api.moderation import create_moderation_router
from app.api.operations import create_operations_router
from app.api.user_settings import create_user_settings_router
from app.api.user_blocks import create_user_blocks_router
from app.auth.bans import suspension_payload
from app.auth.warnings import pending_warning_payload
from app.auth.blocks import BlockService
from app.auth.middleware import SessionAuthMiddleware
from app.request_limits import RequestSizeLimitMiddleware
from app.auth.routes import create_auth_router
from app.db import async_engine, async_session_factory, init_db
from app.db.seed import seed_prompt_lists
from app.deployment import (
    shutdown_drain_seconds,
    validate_python_runtime,
    validate_worker_topology,
)
from app.handlers import register_all_handlers
from app.logging_config import configure_logging
from app.services.mail_delivery import start_delivery_loop, stop_delivery_loop
from app.services.runtime_metrics import start_metrics_loop, stop_metrics_loop
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyPromptListRepository,
)
from app.state import room_manager
from app.services.message_retention import purge_expired_room_messages
from app.services.room_presets import RoomPresetService
from app.services.shutdown import (
    ShutdownCoordinator,
    purge_expired_shutdown_abandonments,
)


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
shutdown_coordinator = ShutdownCoordinator(async_session_factory, room_manager)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
handler_context = register_all_handlers(
    sio,
    room_manager,
    user_repo=user_repo,
    game_history_repo=game_history_repo,
    prompt_list_repo=prompt_list_repo,
    session_factory=async_session_factory,
    block_service=block_service,
    shutdown=shutdown_coordinator,
)


async def _remove_account_from_live_rooms(
    user_id: str, *, reason: str, suspension: dict | None = None
) -> None:
    """End live seats immediately after an account loses access.

    `suspension` carries what to tell them, when there is something to tell.
    A player mid-game learns from the socket rather than from their next
    request failing, which is the difference between being told and finding
    out.
    """
    for room in list(room_manager.rooms.values()):
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
            if suspension is not None:
                # Sent before the disconnect, so it arrives: a socket closed
                # first delivers nothing.
                await sio.emit("account_suspended", suspension, to=player_sid)
            else:
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
    suspension = await suspension_payload(async_session_factory, user_id)
    await _remove_account_from_live_rooms(
        user_id,
        reason="Your account was suspended.",
        suspension=suspension,
    )
    # The eviction above only reaches a socket seated in a room. The account
    # broadcast room covers the rest - a player idling in the lobby learns
    # now, not on their next refused request - and then every remaining
    # socket of the suspended account is closed.
    account_room = f"user:{user_id}"
    await sio.emit("account_suspended", suspension, to=account_room)
    for sid, _ in list(sio.manager.get_participants("/", account_room)):
        await sio.disconnect(sid)


async def push_warning_to_account(user_id: str) -> None:
    """Tell a warned player now if any of their sockets is connected.

    The pop-up otherwise waits for their next visit's
    ``GET /api/warnings/pending``; both routes share one payload builder so
    they cannot say different things.
    """
    payload = await pending_warning_payload(async_session_factory, user_id)
    if payload.get("warning") is not None:
        await sio.emit("moderator_warning", payload, to=f"user:{user_id}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    shutdown_coordinator.begin_startup(
        drain_seconds=shutdown_drain_seconds()
    )
    mail_delivery = None
    metrics_flush = None
    try:
        # Before anything that might have something to say.
        configure_logging()
        validate_python_runtime()
        validate_worker_topology()
        await init_db()
        if handler_context.room_codes is not None:
            await handler_context.room_codes.retire_orphaned_ephemeral()
        await purge_expired_room_messages(async_session_factory)
        await purge_expired_shutdown_abandonments(async_session_factory)
        await seed_prompt_lists(prompt_list_repo)
        # One worker owns everything (#382), so the outbox needs no scheduler
        # and no second process that somebody has to remember to start.
        mail_delivery = start_delivery_loop(async_session_factory)
        metrics_flush = start_metrics_loop(async_session_factory)
        shutdown_coordinator.mark_ready()
        yield
    finally:
        # Flushed on the way out, so the observations describing a planned
        # restart are not the ones lost to it.
        await stop_metrics_loop(metrics_flush, async_session_factory)
        await stop_delivery_loop(mail_delivery)
        await shutdown_coordinator.begin_shutdown(sio)
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
# Added last so it runs first: an oversized body is refused before any routing
# or session lookup, rather than after the server has already held it.
api.add_middleware(RequestSizeLimitMiddleware)
api.include_router(
    create_auth_router(
        user_repo,
        async_session_factory,
        on_account_deleted=remove_deleted_account_from_live_rooms,
        on_identity_merged=block_service.clear,
    )
)
api.include_router(create_operations_router(async_session_factory))
api.include_router(
    create_bug_report_router(async_session_factory, room_manager)
)
api.include_router(create_profile_router(user_repo, game_history_repo))
api.include_router(create_prompt_list_router(prompt_list_repo, user_repo))
api.include_router(create_user_settings_router(async_session_factory))
api.include_router(create_room_preset_router(room_preset_service))
api.include_router(
    create_user_blocks_router(async_session_factory, block_service)
)
api.include_router(
    create_moderation_router(
        async_session_factory,
        on_user_banned=remove_banned_account_from_live_rooms,
        on_user_warned=push_warning_to_account,
    )
)


@api.get("/api/health")
async def health():
    return {"status": "ok", "readiness": shutdown_coordinator.state}


@api.get("/api/ready")
async def ready():
    if not shutdown_coordinator.is_ready:
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "reason": shutdown_coordinator.state},
        )
    return {"status": "ready"}


@api.get("/api/rooms")
async def list_public_rooms(request: Request):
    """The lobby list, with a validator so an unchanged list costs no body.

    Every lobby viewer re-fetches this every four seconds whether or not
    anything moved, and most of the time nothing has. gzip shrinks the body
    but still sends it; a 304 sends none of it.

    The validator is a hash of the serialized list rather than a change
    counter. A counter has to be bumped at every site that touches any of the
    22 fields in `to_public_summary()`, and a missed bump is a lobby that is
    stale until something else happens to change - a silent correctness bug
    traded for a few microseconds. Hashing cannot go stale by construction.
    """
    rooms = room_manager.list_public_rooms()
    body = json.dumps(rooms, separators=(",", ":"), sort_keys=True).encode()
    etag = f'"{hashlib.blake2b(body, digest_size=16).hexdigest()}"'
    # `no-cache` rather than a max-age: the lobby is public and must never be
    # served stale from a browser cache, only revalidated cheaply.
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


# In production, serve the built frontend as static files from the same origin
# (single-port self-hosting). No-op during development when the folder is absent.
_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
configure_frontend(api, _frontend_dist)

app = socketio.ASGIApp(sio, other_asgi_app=api, socketio_path="socket.io")
