"""Socket.IO handlers for the rooms domain."""
from __future__ import annotations

from functools import partial

from app.game import Phase
from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    CreateRoomPayload,
    JoinRoomPayload,
    PayloadError,
    PlayerSettingsPayload,
    RecapDrawingPayload,
    RoomPreviewPayload,
    UpdateRoomSettingsPayload,
    parse_empty_payload,
    parse_payload,
)
from app.rooms import RoomFullError, STARTING_SCORE, normalize_name_color

async def _resolve_user_and_nickname(
    ctx: HandlerContext, sid: str, requested_nickname: str
) -> tuple[str, str, bool, str | None]:
    """
    Resolves the player's identity and effective nickname:
    - If registered: Always enforces user.username (or user.display_name), ignoring requested_nickname.
    - If guest: Validates that requested_nickname is not an in-use username by a registered user.
    Returns (user_id, effective_nickname, is_anonymous, error_message).
    """
    session = await ctx.sio.get_session(sid) if sid else {}
    user_id = session.get("user_id") if session else None
    user = None
    if user_id and ctx.user_repo:
        try:
            user = await ctx.user_repo.get_by_id(user_id)
        except Exception:
            pass

    clean_nickname = requested_nickname.strip() or "Player"
    existing = None
    if ctx.user_repo:
        try:
            existing = await ctx.user_repo.get_by_username(clean_nickname)
        except Exception:
            pass

    # If the user resolved from socket session is registered:
    if user is not None and not user.is_anonymous:
        effective_nickname = user.username or user.display_name or "Player"
        return (user.id, effective_nickname, False, None)

    # If the requested nickname matches a registered account, verify ownership via cookie token:
    if existing is not None and not existing.is_anonymous:
        if user_id == existing.id or (user is not None and user.id == existing.id):
            return (existing.id, clean_nickname, False, None)
        if sid:
            try:
                environ = ctx.sio.get_environ(sid)
                if environ:
                    from app.handlers.connection import extract_jwt_cookie
                    token = extract_jwt_cookie(environ)
                    if token:
                        jwt_secret = ctx.jwt_secret_getter() if ctx.jwt_secret_getter else ""
                        if not jwt_secret:
                            from app.db import async_session_factory
                            jwt_secret = await get_or_create_jwt_secret(async_session_factory)
                        token_user_id = decode_token(token, jwt_secret)
                        if token_user_id == existing.id:
                            if session is not None:
                                session["user_id"] = existing.id
                                await ctx.sio.save_session(sid, session)
                            return (existing.id, clean_nickname, False, None)
            except Exception:
                pass
        return ("", "", True, f"The nickname '{clean_nickname}' is already taken by a registered account")

    if user is None and ctx.user_repo:
        try:
            user = await ctx.user_repo.create_anonymous(display_name=clean_nickname)
            user_id = user.id
            if session is not None:
                session["user_id"] = user_id
                await ctx.sio.save_session(sid, session)
        except Exception:
            pass

    return (user.id if user else (user_id or sid), clean_nickname, True, None)


async def create_room(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(CreateRoomPayload, data)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    settings = await ctx.game_flow.room_settings_from_payload(payload)

    user_id, effective_nickname, is_anonymous, error = await _resolve_user_and_nickname(ctx, sid, payload.nickname)
    if error:
        return {"ok": False, "error": error}

    room = ctx.room_manager.create_room(
        **settings,
    )
    player = ctx.room_manager.add_player(
        room,
        effective_nickname,
        user_id=user_id,
        name_color=None if is_anonymous else normalize_name_color(payload.name_color),
        is_anonymous=is_anonymous,
    )
    await ctx.game_flow._join_socket_room(sid, room, player, is_reconnect=False)
    return ctx.game_flow._session_ack(room, player)


async def get_room_settings(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[1].is_host:
        return {"ok": False, "error": "Only the host can view room settings"}
    room, _ = current
    return {"ok": True, "settings": ctx.game_flow.editable_room_settings(room)}


async def get_custom_words(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, player = current
    if player.is_spectator:
        return {"ok": False, "error": "Only players can view custom words"}
    if room.state != "waiting" or room.game:
        return {
            "ok": False,
            "error": "Custom words can only be viewed in the waiting room",
        }
    return {"ok": True, "words": list(room.custom_words)}


async def get_recap_drawing(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(RecapDrawingPayload, data)
    except PayloadError:
        return {"ok": False, "error": "Drawing not found"}
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, _ = current
    if payload.index >= len(room.last_game_drawings):
        return {"ok": False, "error": "Drawing not found"}
    return {
        "ok": True,
        "drawing": room.last_game_drawings[payload.index].payload(payload.index),
    }


async def update_room_settings(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(UpdateRoomSettingsPayload, data)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[1].is_host:
        return {"ok": False, "error": "Only the host can change room settings"}
    room, _ = current
    if room.state != "waiting" or room.game:
        return {"ok": False, "error": "Settings can only be changed in the waiting room"}
    settings = await ctx.game_flow.room_settings_from_payload(payload, fallback=room)
    active_count = len([p for p in room.player_list() if not p.is_spectator])
    if settings["max_players"] < active_count:
        return {"ok": False, "error": f"Max players cannot be below the {active_count} players already in the room"}
    if not settings["custom_words"]:
        settings["custom_words_only"] = False
    for key, value in settings.items():
        setattr(room, key, value)
    await ctx.sio.emit("chat_message", {"playerId": "", "nickname": "", "text": "The host updated the room settings.", "correct": False, "system": True}, room=room.id)
    await ctx.game_flow._emit_room_state(room)
    return {"ok": True}


async def get_room_preview(ctx: HandlerContext, sid, data):
    """Return invite-screen metadata without joining or exposing player details."""
    try:
        payload = parse_payload(RoomPreviewPayload, data)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    room = ctx.room_manager.get_room_by_code(payload.code)
    if not room:
        return {"ok": False, "error": "Room not found"}
    return {"ok": True, "room": room.to_public_summary()}


async def join_room(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(JoinRoomPayload, data)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    name_color = normalize_name_color(payload.name_color)

    room = ctx.room_manager.get_room(payload.room_id) or ctx.room_manager.get_room_by_code(payload.code)
    if not room:
        return {"ok": False, "error": "Room not found"}

    # Checked before the reconnect branch below: if this exact socket already has a live session in this room
    already_joined = await ctx.game_flow._existing_player_for_sid(sid, room.id)
    if already_joined:
        if not already_joined.connected:
            await ctx.game_flow._join_socket_room(sid, room, already_joined, is_reconnect=True)
            return ctx.game_flow._session_ack(room, already_joined)
        already_joined.sid = sid
        ctx.timers.cancel_disconnect_timer(already_joined.id)
        # Soft checks (heartbeat/visibility) must not dump full canvas history.
        await ctx.game_flow._sync_player_view(
            sid,
            room,
            already_joined,
            sync_canvas=not payload.soft,
        )
        return ctx.game_flow._session_ack(room, already_joined)

    user_id, effective_nickname, is_anonymous, error = await _resolve_user_and_nickname(ctx, sid, payload.nickname)
    if error:
        return {"ok": False, "error": error}

    player = ctx.room_manager.get_player_by_user_id(room, user_id)
    if not player and is_anonymous:
        for p in room.player_list():
            if p.nickname == effective_nickname and not p.connected:
                player = p
                break
    if player:
        player.nickname = effective_nickname
        if not is_anonymous and name_color:
            player.name_color = name_color
        await ctx.game_flow._join_socket_room(sid, room, player, is_reconnect=True)
        return ctx.game_flow._session_ack(room, player)

    try:
        player = ctx.room_manager.add_player(
            room,
            effective_nickname,
            user_id=user_id,
            is_spectator=payload.as_spectator,
            name_color=None if is_anonymous else name_color,
            is_anonymous=is_anonymous,
        )
    except RoomFullError:
        return {"ok": False, "error": "Room is full"}

    # A game already in progress keeps running its existing turn_order
    if room.game and not player.is_spectator:
        room.game.add_player_to_rotation(player.id)

    await ctx.game_flow._join_socket_room(sid, room, player, is_reconnect=False)
    return ctx.game_flow._session_ack(room, player)


async def session_ping(ctx: HandlerContext, sid, data=None):
    """Compact liveness check: [1, phase, round, remaining, gen, seq] or [0]."""
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return [0]
    room, _ = current
    game = room.game
    phase = {
        Phase.CHOOSING_WORD: 1,
        Phase.DRAWING: 2,
        Phase.ROUND_END: 3,
        Phase.GAME_END: 4,
    }.get(game.phase, 0) if game else 0
    return [
        1,
        phase,
        game.round_number if game else 0,
        round(game.remaining_seconds()) if game else 0,
        game.canvas.generation if game else 0,
        game.canvas.sequence if game else 0,
    ]


async def update_player_settings(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(PlayerSettingsPayload, data)
    except PayloadError:
        return {"ok": False, "error": "Invalid player name color"}
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, player = current
    if player.is_anonymous:
        return {"ok": False, "error": "Guest accounts cannot customize name color"}
    player.name_color = normalize_name_color(payload.name_color) or player.name_color
    await ctx.game_flow._emit_room_state(room)
    return {"ok": True}


async def become_player(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, player = current
    if room.state != "waiting" or room.game:
        return {"ok": False, "error": "You can only join as a player from the waiting room"}
    if not player.is_spectator:
        return {"ok": False, "error": "You are already a player"}

    active_count = len([candidate for candidate in room.players.values() if not candidate.is_spectator])
    if active_count >= room.max_players:
        return {"ok": False, "error": "Player slots are full"}

    player.is_spectator = False
    player.score = STARTING_SCORE if room.scoring_mode == "default" else 0
    await ctx.sio.emit(
        "chat_message",
        {
            "playerId": "",
            "nickname": "",
            "text": f"{player.nickname} joined as a player.",
            "correct": False,
            "system": True,
        },
        room=room.id,
    )
    await ctx.game_flow._emit_room_state(room)
    return {"ok": True}


async def leave_room(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return
    room, player = current
    ctx.timers.cancel_disconnect_timer(player.id)
    ctx.room_manager.remove_player(room, player.id)
    await ctx.sio.leave_room(sid, room.id)
    await ctx.sio.save_session(sid, {})
    if not room.connected_players():
        ctx.timers.cancel_phase_timer(room.id)
        ctx.timers.cancel_hint_timers(room.id)
        ctx.timers.cancel_restart_timer(room.id)
        ctx.room_manager.remove_room_if_empty(room.id)
    else:
        await ctx.game_flow._remove_player_from_game(room, player.id)
        await ctx.sio.emit("player_left", {"playerId": player.id}, room=room.id)
        await ctx.game_flow._emit_room_state(room)


def register(ctx: HandlerContext) -> None:
    ctx.sio.on("create_room", handler=partial(create_room, ctx))
    ctx.sio.on("get_room_settings", handler=partial(get_room_settings, ctx))
    ctx.sio.on("get_custom_words", handler=partial(get_custom_words, ctx))
    ctx.sio.on("get_recap_drawing", handler=partial(get_recap_drawing, ctx))
    ctx.sio.on("update_room_settings", handler=partial(update_room_settings, ctx))
    ctx.sio.on("get_room_preview", handler=partial(get_room_preview, ctx))
    ctx.sio.on("join_room", handler=partial(join_room, ctx))
    ctx.sio.on("session_ping", handler=partial(session_ping, ctx))
    ctx.sio.on("update_player_settings", handler=partial(update_player_settings, ctx))
    ctx.sio.on("become_player", handler=partial(become_player, ctx))
    ctx.sio.on("leave_room", handler=partial(leave_room, ctx))
