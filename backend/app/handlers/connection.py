"""Socket.IO handlers for the connection domain."""
from __future__ import annotations

import asyncio
import logging
from functools import partial

from socketio.exceptions import ConnectionRefusedError

from app.auth.sessions import (
    resolve_session_status,
    session_token_from_cookie_header,
)
from app.domain_values import RuntimeEventType
from app.handlers.context import HandlerContext
from app.rooms import _metrics_user_id as metrics_user_id
from app.services.runtime_metrics import metrics

logger = logging.getLogger("sketchy.handlers.connection")
RECONNECT_GRACE_SECONDS = 30

async def connect(ctx: HandlerContext, sid, environ, auth):
    """Bind the socket to whatever account the session cookie names.

    Read-only: a visitor with no cookie yet connects as ``user_id=None`` and
    plays normally, just without reconnect or history. Guests are provisioned
    solely by ``GET /api/auth/me`` so that merely opening a socket cannot
    create user rows.
    """
    user_id = None
    if ctx.session_factory is not None:
        token = session_token_from_cookie_header(environ.get("HTTP_COOKIE"))
        resolution = await resolve_session_status(ctx.session_factory, token)
        if resolution.banned_user_id is not None:
            raise ConnectionRefusedError("This account is suspended.")
        auth_session = resolution.session
        user_id = auth_session.user_id if auth_session else None
    await ctx.sio.save_session(sid, {"user_id": user_id})
    if user_id is not None:
        # Every socket of an account shares one broadcast room, so account-
        # level news (a suspension, a moderator warning) reaches a player in
        # the lobby as immediately as one seated in a game.
        await ctx.sio.enter_room(sid, f"user:{user_id}")
    shutdown = getattr(ctx, "shutdown", None)
    if shutdown is not None and shutdown.is_draining:
        await ctx.sio.emit(
            "server_shutdown", shutdown.notice_payload(), to=sid
        )
    logger.info("socket connected: %s (user=%s)", sid, user_id or "anonymous")


async def disconnect(ctx: HandlerContext, sid):
    session = await ctx.sio.get_session(sid) if sid else None
    if not session:
        return
    room = ctx.room_manager.get_room(session.get("room_id"))
    token = session.get("player_id")
    if not room or not token or token not in room.players:
        return
    player = room.players[token]
    if player.sid != sid:
        # Stale disconnect for a sid that's already been superseded by a
        # newer connection (e.g. the client reconnected - a new sid ran
        # join_room and updated player.sid - before this older sid's
        # disconnect event was processed). The player is still actively
        # connected via the newer sid, so ignore this one rather than
        # incorrectly marking them disconnected.
        return
    player.connected = False
    player.sid = None
    metrics.record(
        RuntimeEventType.PLAYER_DISCONNECTED,
        room_id=room.id,
        user_id=metrics_user_id(player.user_id),
    )
    for p in room.players.values():
        p.kick_votes.discard(token)
        p.afk_votes.discard(token)
    await ctx.sio.emit(
        "player_disconnected", {"playerId": token, "nickname": player.nickname}, room=room.id
    )
    await ctx.game_flow._emit_room_state(room)
    await ctx.game_flow._end_turn_if_all_guessed(room)

    async def _evict_after_grace() -> None:
        try:
            await asyncio.sleep(RECONNECT_GRACE_SECONDS)
        except asyncio.CancelledError:
            return
        still_present = room.players.get(token)
        if not still_present or still_present.connected:
            return
        # The grace window ran out: this is the disconnect that became a
        # departure, which is the number worth separating from the rest.
        metrics.record(
            RuntimeEventType.PLAYER_EVICTED,
            room_id=room.id,
            user_id=metrics_user_id(still_present.user_id),
            value=int(RECONNECT_GRACE_SECONDS),
        )
        ctx.room_manager.remove_player(room, token)
        await ctx.sio.emit("player_left", {"playerId": token}, room=room.id)
        if not room.connected_players():
            ctx.timers.cancel_phase_timer(room.id)
            ctx.timers.cancel_hint_timers(room.id)
            ctx.timers.cancel_restart_timer(room.id)
            await ctx.remove_room_if_empty(room.id)
            return
        await ctx.game_flow._remove_player_from_game(room, token)
        await ctx.game_flow._emit_room_state(room)

    ctx.timers.replace_disconnect_timer(
        token, asyncio.create_task(_evict_after_grace())
    )


def register(ctx: HandlerContext) -> None:
    ctx.sio.on("connect", handler=partial(connect, ctx))
    ctx.sio.on("disconnect", handler=partial(disconnect, ctx))
