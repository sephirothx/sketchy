"""Socket.IO handlers for the connection domain."""
from __future__ import annotations

import asyncio
import logging
from functools import partial

from app.auth.jwt import JWT_COOKIE_NAME, decode_token, get_or_create_jwt_secret
from app.handlers.context import HandlerContext

logger = logging.getLogger("sketchy.handlers.connection")
RECONNECT_GRACE_SECONDS = 30


def extract_jwt_cookie(environ: dict) -> str | None:
    if not isinstance(environ, dict):
        return None
    raw_cookie = environ.get("HTTP_COOKIE")
    if not raw_cookie and "asgi.scope" in environ:
        headers = dict(environ["asgi.scope"].get("headers", []))
        raw_cookie = headers.get(b"cookie", b"").decode("utf-8", errors="ignore")
    if not raw_cookie:
        return None
    for part in raw_cookie.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            if k.strip() == JWT_COOKIE_NAME:
                return v.strip()
    return None


async def connect(ctx: HandlerContext, sid, environ, auth):
    logger.info("socket connected: %s", sid)
    token = extract_jwt_cookie(environ)
    user_id = None
    if token:
        try:
            from app.db import async_session_factory
            jwt_secret = await get_or_create_jwt_secret(async_session_factory)
            user_id = decode_token(token, jwt_secret)
        except Exception:
            logger.exception("Error decoding JWT on socket connect")

    if not user_id and ctx.user_repo:
        try:
            guest = await ctx.user_repo.create_anonymous(display_name="Guest")
            user_id = guest.id
        except Exception:
            logger.exception("Failed to auto-provision anonymous user on socket connect")

    await ctx.sio.save_session(sid, {"user_id": user_id})


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
    for p in room.players.values():
        p.kick_votes.discard(token)
        p.afk_votes.discard(token)
    await ctx.sio.emit(
        "player_disconnected", {"playerId": token, "nickname": player.nickname}, room=room.id
    )
    await ctx.game_flow._emit_room_state(room)

    async def _evict_after_grace() -> None:
        try:
            await asyncio.sleep(RECONNECT_GRACE_SECONDS)
        except asyncio.CancelledError:
            return
        still_present = room.players.get(token)
        if not still_present or still_present.connected:
            return
        ctx.room_manager.remove_player(room, token)
        await ctx.sio.emit("player_left", {"playerId": token}, room=room.id)
        if not room.connected_players():
            ctx.timers.cancel_phase_timer(room.id)
            ctx.timers.cancel_hint_timers(room.id)
            ctx.timers.cancel_restart_timer(room.id)
            ctx.room_manager.remove_room_if_empty(room.id)
            return
        await ctx.game_flow._remove_player_from_game(room, token)
        await ctx.game_flow._emit_room_state(room)

    ctx.timers.replace_disconnect_timer(
        token, asyncio.create_task(_evict_after_grace())
    )


def register(ctx: HandlerContext) -> None:
    ctx.sio.on("connect", handler=partial(connect, ctx))
    ctx.sio.on("disconnect", handler=partial(disconnect, ctx))
