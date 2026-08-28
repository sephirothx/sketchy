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
from app.client_config import client_config
from app.flow_timing import timing
from app.handlers.context import HandlerContext
from app.protocol import PROTOCOL_VERSION, client_protocol_version
from app.rooms import Player, Room, _metrics_user_id as metrics_user_id
from app.services.runtime_metrics import metrics

logger = logging.getLogger("sketchy.handlers.connection")


async def connect(ctx: HandlerContext, sid, environ, auth):
    """Bind the socket to whatever account the session cookie names.

    Read-only: a visitor with no cookie yet connects as ``user_id=None`` and
    plays normally, just without reconnect or history. Guests are provisioned
    solely by ``GET /api/auth/me`` so that merely opening a socket cannot
    create user rows.
    """
    # The ledger is balanced in a `finally`, not on each way out. A handshake
    # refused with `ConnectionRefusedError` never reaches the disconnect
    # handler at all - Socket.IO answers it with CONNECT_ERROR and tears the
    # session down itself - so a suspended account could otherwise fill the
    # ceiling with sockets that were never open, and the process would refuse
    # everybody. The same is true of any other failure in here.
    ctx.room_capacity.note_socket_opened(sid)
    accepted = False
    try:
        # Counted before the ceiling is read, so this socket is measured
        # against a ceiling that includes it.
        if not ctx.room_capacity.has_socket_capacity():
            # Told, not refused. A refusal carries no diagnosable signal and
            # `ConnectionRefusedError` is reserved for suspensions, so the client
            # learns why and can say so instead of retrying into silence.
            logger.warning(
                "refusing socket %s: %d already open", sid, ctx.room_capacity.open_sockets
            )
            await ctx.sio.emit(
                "server_full",
                {"reason": "Sketchy is full right now. Try again in a few minutes."},
                to=sid,
            )
            await ctx.sio.disconnect(sid)
            return
        user_id = None
        if ctx.session_factory is not None:
            token = session_token_from_cookie_header(environ.get("HTTP_COOKIE"))
            resolution = await resolve_session_status(ctx.session_factory, token)
            if resolution.banned_user_id is not None:
                raise ConnectionRefusedError("This account is suspended.")
            auth_session = resolution.session
            user_id = auth_session.user_id if auth_session else None
        await ctx.sio.save_session(sid, {"user_id": user_id})
        client_protocol = client_protocol_version(auth)
        if client_protocol != PROTOCOL_VERSION:
            # Accepted, then told. Refusing would leave a stale build with nothing
            # to act on; this way it can reload onto the one being served. The
            # socket is otherwise ordinary until it does.
            await ctx.sio.emit(
                "upgrade_required",
                {
                    "reason": "This tab is running an older version of Sketchy.",
                    "expected": PROTOCOL_VERSION,
                    "received": client_protocol,
                },
                to=sid,
            )
        if user_id is not None:
            # Every socket of an account shares one broadcast room, so account-
            # level news (a suspension, a moderator warning) reaches a player in
            # the lobby as immediately as one seated in a game.
            await ctx.sio.enter_room(sid, f"user:{user_id}")
        # Sent to every socket, including one that will be told to upgrade:
        # a client running the current bundle needs these before it draws
        # anything, and there is no acknowledgement on a handshake to put
        # them in. Re-sent to everybody when an administrator changes one.
        await ctx.sio.emit("client_config", client_config.payload(), to=sid)
        shutdown = getattr(ctx, "shutdown", None)
        if shutdown is not None and shutdown.is_draining:
            await ctx.sio.emit(
                "server_shutdown", shutdown.notice_payload(), to=sid
            )
        elif shutdown is not None and shutdown.is_paused:
            # A pause outlives any one connection, so a socket opened during
            # one has to be told on arrival rather than only by the broadcast
            # it missed. Not `elif` for tidiness: a drain that begins while
            # paused is the more urgent of the two, and saying both would put
            # two banners on one screen.
            await ctx.sio.emit("server_paused", shutdown.pause_payload(), to=sid)
        logger.info("socket connected: %s (user=%s)", sid, user_id or "anonymous")
        accepted = True
    finally:
        if not accepted:
            ctx.room_capacity.note_socket_closed(sid)


async def disconnect(ctx: HandlerContext, sid):
    if not sid:
        return
    ctx.room_capacity.note_socket_closed(sid)
    ctx.clear_command_budget(sid)
    if ctx.is_closing(sid):
        # We are closing this socket ourselves, from inside a seat transition
        # that has already moved its seat on - the tab a reconnect superseded.
        # Socket.IO runs this handler inline from that transition, so queueing
        # at the gate would be waiting for the caller, and two sockets
        # superseding each other at the same moment would wait for each other
        # for ever.
        await reconcile_socket_seats(ctx, sid)
        return
    # Queued behind whatever else is moving this socket between seats, so a
    # connection that drops mid-entry is reconciled once its new seat exists
    # rather than a moment before it does.
    async with ctx.seating(sid):
        await reconcile_socket_seats(ctx, sid)


async def reconcile_socket_seats(ctx: HandlerContext, sid: str) -> None:
    """Start the reconnect grace on every seat this socket still holds.

    Resolved by walking the live rooms rather than by reading the socket
    session. The session names a single room, so a socket that ever held a
    seat in more than one - the room it was moved out of, or one stranded by
    an older build - would leave the rest behind, connected to a socket that
    is gone and therefore uncountable as empty forever.

    A seat whose `sid` is no longer this one is simply not found: that is the
    stale disconnect for a socket a newer connection has already superseded,
    and its player is still actively connected through the newer sid.
    """
    for room, player in ctx.room_manager.seats_for_sid(sid):
        await _begin_reconnect_grace(ctx, room, player)


async def _begin_reconnect_grace(
    ctx: HandlerContext, room: Room, player: Player
) -> None:
    token = player.id
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
            await asyncio.sleep(timing.reconnect_grace_seconds)
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
            value=int(timing.reconnect_grace_seconds),
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
