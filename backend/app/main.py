"""ASGI entrypoint: mounts the Socket.IO server alongside a small FastAPI REST app."""
from contextlib import asynccontextmanager
from pathlib import Path

import asyncio
import hashlib
import json
import os
import signal

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
from app.api.admin_controls import create_admin_controls_router, read_paused
from app.api.admin_settings import create_admin_settings_router
from app.api.operations import create_operations_router
from app.api.role_notices import (
    create_role_notice_router,
    pending_role_notice_payload,
)
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
    validate_database_configuration,
    validate_python_runtime,
    validate_worker_topology,
)
from app.handlers import register_all_handlers
from app.logging_config import configure_logging
from app.auth.retention import (
    purge_expired_auth_sessions,
    purge_expired_data_exports,
    start_retention_loop,
    stop_retention_loop,
)
from app.auth.mail import purge_expired_outbox_entries
from app.services.mail_delivery import start_delivery_loop, stop_delivery_loop
from app.services.runtime_metrics import start_metrics_loop, stop_metrics_loop
from app.services.readiness import LoopHealth, ReadinessProbe
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyPromptListRepository,
)
from app.client_config import client_config
from app.flow_timing import timing as flow_timing
from app.state import room_manager
from app.services.message_retention import purge_expired_room_messages
from app.services.room_presets import RoomPresetService
from app.services.config_store import read_prefixed
from app.services.runtime_settings import CONFIG_PREFIX
from app.services.tunables import build_runtime_settings
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
readiness_probe = ReadinessProbe(async_session_factory)

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
# Built here rather than at import so it can reach the live policy objects the
# handlers consult: a change has to move the value the next command reads, not
# a copy of it.
runtime_settings = build_runtime_settings(
    budgets=handler_context.command_budgets,
    quotas=handler_context.room_quotas,
    capacity=handler_context.room_capacity,
    flow=flow_timing,
    client=client_config,
    shutdown=shutdown_coordinator,
)


async def announce_client_config(changed) -> None:
    """Tell every connected client when one of *its* cadences moves.

    Only when one actually moved. The notice is cheap, but a broadcast to
    everybody in the building for a change to a server-side ceiling they
    cannot observe is noise on the wire and noise in a network panel.
    """
    if any(settings_name.startswith("client.") for settings_name in changed):
        await sio.emit("client_config", client_config.payload())


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
        notice = (
            ("account_suspended", suspension)
            if suspension is not None
            else ("session_superseded", {"reason": reason})
        )
        await handler_context.evict_player(room, player.id, notice=notice)


def _sockets_of(user_id: str) -> list[str]:
    """Every socket the account holds, seated or not.

    Walking the rooms only reaches a socket that already holds a seat, and one
    can be in flight: `create_room` and `join_room` await the database before
    they seat anybody, so a socket that was mid-entry when the sweep passed
    had no seat to be found and would have finished seating itself afterwards.
    Every socket joins its account's broadcast room at the handshake, so that
    is the list that has all of them.
    """
    return [sid for sid, _ in sio.manager.get_participants("/", f"user:{user_id}")]


async def _close_every_socket_of(
    user_id: str, notice: tuple[str, dict], sids: list[str]
) -> None:
    """Tell an account's sockets, then close them - seated or not."""
    event, payload = notice
    await sio.emit(event, payload, to=f"user:{user_id}")
    for sid in sids:
        await sio.disconnect(sid)


async def remove_deleted_account_from_live_rooms(user_id: str) -> None:
    block_service.clear()
    # Marked before the first await, not partway through. Every step below
    # yields, closing a socket waits at that socket's seating gate, and an
    # entry that reads the mark in one of those gaps is an entry that seats an
    # account this sweep is in the middle of ending.
    with handler_context.ending(_sockets_of(user_id)) as sids:
        await _remove_account_from_live_rooms(
            user_id, reason="Your account was deleted."
        )
        # Deletion ends the account as thoroughly as a suspension does, so it
        # ends the sockets the same way. This half was only ever done for bans.
        await _close_every_socket_of(
            user_id,
            ("session_superseded", {"reason": "Your account was deleted."}),
            sids,
        )


async def remove_banned_account_from_live_rooms(user_id: str) -> None:
    # Marked before even reading what to tell them: that read is an await like
    # any other, and the account is banned already by the time this is called.
    with handler_context.ending(_sockets_of(user_id)) as sids:
        suspension = await suspension_payload(async_session_factory, user_id)
        await _remove_account_from_live_rooms(
            user_id,
            reason="Your account was suspended.",
            suspension=suspension,
        )
        # The eviction above only reaches a socket seated in a room. The
        # account broadcast room covers the rest - a player idling in the
        # lobby learns now, not on their next refused request, and so does one
        # whose entry was still in flight when the sweep walked its room.
        await _close_every_socket_of(
            user_id, ("account_suspended", suspension), sids
        )


async def push_warning_to_account(user_id: str) -> None:
    """Tell a warned player now if any of their sockets is connected.

    The pop-up otherwise waits for their next visit's
    ``GET /api/warnings/pending``; both routes share one payload builder so
    they cannot say different things.
    """
    payload = await pending_warning_payload(async_session_factory, user_id)
    if payload.get("warning") is not None:
        await sio.emit("moderator_warning", payload, to=f"user:{user_id}")


async def push_role_change_to_account(user_id: str) -> None:
    """Tell an account its role changed, if any of its sockets is connected.

    The pop-up otherwise waits for their next visit's
    ``GET /api/role-notices/pending``; both routes share one payload builder so
    they cannot say different things. The account's broadcast room is what makes
    "wherever they are" true - a player idling in the lobby learns now rather
    than on some later page load, and so does one seated in a game.
    """
    payload = await pending_role_notice_payload(async_session_factory, user_id)
    if payload.get("notice") is not None:
        await sio.emit("role_changed", payload, to=f"user:{user_id}")


def request_process_exit() -> None:
    """Ask this process to stop, the same way a deployment would.

    A signal rather than a direct call into the coordinator, so the drain runs
    exactly where it runs for a real deploy - `DrainingServer.shutdown`, or the
    lifespan teardown when the app is served some other way. One path, so an
    operator-initiated stop cannot behave differently from an operator typing
    the same thing into a terminal.

    Deferred by a tick so the acknowledgement reaches the browser that asked:
    signalling inline races the response out of the door.
    """
    loop = asyncio.get_running_loop()
    loop.call_later(0.25, os.kill, os.getpid(), signal.SIGTERM)


async def announce_pause(payload: dict) -> None:
    """Tell everyone the moment a maintenance pause starts or ends.

    Sent to everybody rather than only to whoever tries something next: a
    player staring at a lobby wants to know why the create button will refuse
    them before they press it, and the banner has to clear on resume.
    """
    await sio.emit("server_paused", payload)


async def adopt_stored_settings() -> None:
    """Put an administrator's stored choices in force before anybody is admitted.

    Ordered before readiness on purpose: a process that opens on its compiled
    defaults and adopts the stored ones a moment later has served the first
    players a configuration nobody chose.
    """
    runtime_settings.apply_stored(
        await read_prefixed(async_session_factory, CONFIG_PREFIX)
    )
    # A pause is usually taken *because* a restart is coming, so it has to
    # survive one - otherwise the deploy it was guarding reopens the doors.
    shutdown_coordinator.pause(await read_paused(async_session_factory))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    shutdown_coordinator.begin_startup(
        drain_seconds=shutdown_drain_seconds()
    )
    mail_delivery = None
    metrics_flush = None
    retention_sweep = None
    mail_health = LoopHealth("mail_delivery")
    metrics_health = LoopHealth("runtime_metrics")
    retention_health = LoopHealth("retention_sweep")
    try:
        # Before anything that might have something to say.
        configure_logging()
        validate_python_runtime()
        validate_worker_topology()
        # Before init_db, so a production process pointed at a local file
        # refuses to start rather than migrating one and serving from it.
        validate_database_configuration()
        await init_db()
        if handler_context.room_codes is not None:
            await handler_context.room_codes.retire_orphaned_ephemeral()
        await purge_expired_room_messages(async_session_factory)
        await purge_expired_outbox_entries(async_session_factory)
        await purge_expired_auth_sessions(async_session_factory)
        await purge_expired_data_exports(async_session_factory)
        await purge_expired_shutdown_abandonments(async_session_factory)
        await seed_prompt_lists(prompt_list_repo)
        await adopt_stored_settings()
        # One worker owns everything (#382), so the outbox needs no scheduler
        # and no second process that somebody has to remember to start.
        mail_delivery = start_delivery_loop(
            async_session_factory, health=mail_health
        )
        metrics_flush = start_metrics_loop(
            async_session_factory, health=metrics_health
        )
        retention_sweep = start_retention_loop(
            async_session_factory, health=retention_health
        )
        readiness_probe.supervise("mail_delivery", mail_delivery, mail_health)
        readiness_probe.supervise("runtime_metrics", metrics_flush, metrics_health)
        readiness_probe.supervise("retention_sweep", retention_sweep, retention_health)
        shutdown_coordinator.mark_ready()
        yield
    finally:
        # Released before the loops are cancelled: a loop stopped on purpose
        # is not a crashed one, and readiness has already gone 503 for the
        # drain by the time this runs.
        readiness_probe.release()
        # Flushed on the way out, so the observations describing a planned
        # restart are not the ones lost to it.
        await stop_retention_loop(retention_sweep)
        await stop_metrics_loop(metrics_flush, async_session_factory)
        await stop_delivery_loop(mail_delivery)
        await shutdown_coordinator.begin_shutdown(sio)
        # After the sockets are drained, so the last thing anybody said is
        # written rather than left in the queue.
        if handler_context.message_retention is not None:
            await handler_context.message_retention.aclose()
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
    create_admin_settings_router(
        async_session_factory, runtime_settings, on_change=announce_client_config
    )
)
api.include_router(
    create_admin_controls_router(
        async_session_factory,
        shutdown_coordinator,
        room_manager,
        handler_context,
        on_change=announce_pause,
        on_role_changed=push_role_change_to_account,
        request_process_exit=request_process_exit,
    )
)
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
api.include_router(create_role_notice_router(async_session_factory))
api.include_router(
    create_moderation_router(
        async_session_factory,
        on_user_banned=remove_banned_account_from_live_rooms,
        on_user_warned=push_warning_to_account,
    )
)


@api.get("/api/health")
async def health():
    """Liveness, plus what the loops have to say for themselves.

    Deliberately still process-only: liveness answers "restart me or not",
    and a dependency outage is not a reason to restart a process that would
    come back into the same outage. The loop counters ride along because
    nothing else exposes them - a sweep that has failed on every iteration
    since startup is otherwise only a line in a log nobody is reading.
    """
    return {
        "status": "ok",
        "readiness": shutdown_coordinator.state,
        "paused": shutdown_coordinator.is_paused,
        "loops": readiness_probe.loop_snapshot(),
    }


@api.get("/api/ready")
async def ready():
    """Whether this process can actually serve, not merely whether it is up.

    The process's own state is tested before the database and again after it.
    Both are cheap and both can change while the probe is in flight - a drain
    can begin, and a supervised loop can stop - so an answer computed a second
    ago must not be delivered as if it were current. Checking the drain first
    also keeps R-SHUT-01 true: a draining process answers from the drain
    rather than being held up, or contradicted, by a dependency.
    """
    def blocked_by_this_process() -> str | None:
        if not shutdown_coordinator.is_ready:
            return shutdown_coordinator.state
        # A loop that only errors stays in rotation: it is reported in
        # `/api/health` and alerted on there. A loop whose task is *gone*
        # cannot come back without a restart, so it fails readiness and
        # invites a supervisor to replace this instance.
        dead = readiness_probe.dead_loops()
        if dead:
            return "background loop stopped: " + ", ".join(dead)
        return None

    def not_ready(reason: str | None) -> HTTPException:
        return HTTPException(
            status_code=503,
            detail={"status": "not_ready", "reason": reason},
        )

    reason = blocked_by_this_process()
    if reason is not None:
        raise not_ready(reason)

    database_ready, database_reason = await readiness_probe.check_database()

    # Asked again: the probe yields for up to a second, and that window is
    # long enough for a drain to begin or a loop to stop.
    reason = blocked_by_this_process()
    if reason is not None:
        raise not_ready(reason)

    if not database_ready:
        raise not_ready(database_reason)

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
