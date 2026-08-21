"""Socket.IO handlers for the rooms domain."""
from __future__ import annotations

import logging
from functools import partial

from app.game import Phase
from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    CreateRoomPayload,
    JoinRoomPayload,
    PayloadError,
    PlayerSettingsPayload,
    RecapDrawingPayload,
    RenamePlayerPayload,
    RoomPreviewPayload,
    UpdateRoomSettingsPayload,
    parse_empty_payload,
    parse_payload,
)
from app.handlers.identity import IdentityError, resolve_identity
from app.presenters import editable_room_settings_payload, session_payload
from app.rooms import (
    ANONYMOUS_NAME_COLOR,
    RoomFullError,
    generate_random_name_color,
    normalize_name_color,
)

logger = logging.getLogger("sketchy.handlers.rooms")

async def create_room(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(CreateRoomPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    try:
        identity = await resolve_identity(ctx, sid, payload.nickname)
    except IdentityError as error:
        return {"ok": False, "error": str(error), "field": "nickname"}
    settings = await ctx.game_flow.room_settings_from_payload(payload)

    room = ctx.room_manager.create_room(
        **settings,
    )
    player = ctx.room_manager.add_player(
        room,
        identity.nickname,
        name_color=identity.name_color or normalize_name_color(payload.name_color),
        user_id=identity.user_id,
        is_anonymous=identity.is_anonymous,
    )
    await ctx.game_flow._join_socket_room(sid, room, player, is_reconnect=False)
    return session_payload(room, player)


async def get_room_settings(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[1].is_host:
        return {"ok": False, "error": "Only the host can view room settings"}
    room, _ = current
    return {"ok": True, "settings": editable_room_settings_payload(room)}


async def get_custom_words(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, player = current
    if player.is_spectator:
        return {"ok": False, "error": "Only players can view custom prompts"}
    if room.state != "waiting" or room.game:
        return {
            "ok": False,
            "error": "Custom prompts can only be viewed in the waiting room",
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
    drawing = room.last_game_drawings[payload.index]
    if not drawing.is_available:
        # Given up to keep the room's recap inside its budget. Distinct from
        # "not found" so the client can say so plainly instead of offering a
        # retry for something that is never coming back.
        return {
            "ok": False,
            "error": "This drawing was not kept",
            "unavailable": True,
        }
    return {"ok": True, "drawing": drawing.payload(payload.index)}


async def update_room_settings(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(UpdateRoomSettingsPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[1].is_host:
        return {"ok": False, "error": "Only the host can change room settings"}
    room, _ = current
    if room.state != "waiting" or room.game:
        return {"ok": False, "error": "Settings can only be changed in the waiting room"}
    settings = await ctx.game_flow.room_settings_from_payload(payload, fallback=room)
    active_count = len(room.seated_players())
    if settings["max_players"] < active_count:
        return {"ok": False, "error": f"Max players cannot be below the {active_count} players already in the room"}
    if not settings["custom_words"]:
        settings["custom_words_only"] = False
    for key, value in settings.items():
        setattr(room, key, value)
    await ctx.game_flow.announce(room, "The host updated the room settings.")
    await ctx.game_flow._emit_room_state(room)
    return {"ok": True}


async def get_room_preview(ctx: HandlerContext, sid, data):
    """Return invite-screen metadata without joining or exposing player details."""
    try:
        payload = parse_payload(RoomPreviewPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    room = ctx.room_manager.get_room_by_code(payload.code)
    if not room:
        return {"ok": False, "error": "Room not found"}
    return {"ok": True, "room": room.to_public_summary()}


async def join_room(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(JoinRoomPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    name_color = normalize_name_color(payload.name_color)

    room = ctx.room_manager.get_room(payload.room_id) or ctx.room_manager.get_room_by_code(payload.code)
    if not room:
        return {"ok": False, "error": "Room not found"}

    # Checked before the token-reconnect branch below: a client's first
    # join_room call (e.g. from the lobby) is very often followed by a
    # second one moments later on the very same socket (e.g. GameRoomPage
    # re-joining with the token it was just given). That second call
    # would otherwise match the token-reconnect branch and fire a
    # spurious "reconnected" message for a session that never actually
    # disconnected - so if this exact socket already has a live session
    # in this room, just confirm it rather than reprocessing the join.
    already_joined = await ctx.game_flow._existing_player_for_sid(sid, room.id)
    if already_joined:
        already_joined.sid = sid
        already_joined.connected = True
        ctx.timers.cancel_disconnect_timer(already_joined.id)
        # Soft checks (heartbeat/visibility) must not dump full canvas history.
        await ctx.game_flow._sync_player_view(
            sid,
            room,
            already_joined,
            sync_canvas=not payload.soft,
        )
        return session_payload(room, already_joined)

    session = await ctx.sio.get_session(sid) if sid else None
    user_id = session.get("user_id") if session else None

    # One seat per account per room. A second tab - or a reconnect after the
    # transport dropped - takes over the existing seat instead of adding
    # another, so scores and turn order survive and cannot be duplicated.
    player = ctx.room_manager.get_player_by_user_id(room, user_id)
    if player:
        # The account may have been claimed since this seat was taken - this is
        # the path a guest returns through after registering or logging in
        # mid-game, so the seat has to pick up the new name and status.
        await _refresh_seat_identity(ctx, player, name_color)
        if not player.is_anonymous:
            stored = await _account_name_color(ctx, player.user_id)
            if stored or name_color:
                player.name_color = stored or name_color
        # _join_socket_room notifies and disconnects any socket that was
        # holding this seat before handing it to the new one.
        await ctx.game_flow._join_socket_room(sid, room, player, is_reconnect=True)
        return session_payload(room, player)

    if payload.resume_only:
        return {"ok": False, "error": "No existing session in this room"}

    try:
        identity = await resolve_identity(ctx, sid, payload.nickname)
    except IdentityError as error:
        return {"ok": False, "error": str(error), "field": "nickname"}

    try:
        player = ctx.room_manager.add_player(
            room,
            identity.nickname,
            is_spectator=payload.as_spectator,
            name_color=identity.name_color or name_color,
            user_id=identity.user_id,
            is_anonymous=identity.is_anonymous,
        )
    except RoomFullError:
        # Flagged rather than left for the client to recognise by its prose:
        # the "you can still spectate" offer hangs off this exact case.
        return {"ok": False, "error": "Room is full", "roomFull": True}

    # A game already in progress keeps running its existing turn_order -
    # joining mid-game just enrolls the new player into future turns
    # (appended to the end, so everyone already playing keeps their
    # relative order) rather than blocking the join entirely.
    if room.game and not player.is_spectator:
        room.game.add_player_to_rotation(player.id)

    await ctx.game_flow._join_socket_room(sid, room, player, is_reconnect=False)
    return session_payload(room, player)


async def _account_name_color(ctx: HandlerContext, user_id: str | None) -> str | None:
    """The colour stored on an account, if it has one."""
    if ctx.user_repo is None or not user_id:
        return None
    account = await ctx.user_repo.get_by_id(user_id)
    return normalize_name_color(account.name_color) if account else None


async def _refresh_seat_identity(
    ctx: HandlerContext, player, name_color: str | None
) -> None:
    """Re-sync a rebound seat with its account.

    Registering keeps the same user id, so the seat survives - but its nickname
    and guest status are stale until refreshed here. Only ever upgrades a guest
    seat to a registered one; it never renames a player mid-game otherwise.
    """
    if ctx.user_repo is None or not player.user_id or not player.is_anonymous:
        return
    account = await ctx.user_repo.get_by_id(player.user_id)
    if account is None or account.is_anonymous or not account.username:
        return
    player.nickname = account.username
    player.is_anonymous = False
    player.name_color = (
        normalize_name_color(account.name_color)
        or normalize_name_color(name_color)
        or generate_random_name_color()
    )


async def session_ping(ctx: HandlerContext, sid, data=None):
    """Compact liveness check: [1, phase, round, remaining, gen, seq] or [0]."""
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
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
        # Grey italics is what marks a name as unclaimed; letting guests recolour
        # would erase the only cue distinguishing them from registered players.
        player.name_color = ANONYMOUS_NAME_COLOR
        await ctx.game_flow._emit_room_state(room)
        return {"ok": False, "error": "Create an account to choose a name colour"}
    player.name_color = normalize_name_color(payload.name_color) or player.name_color
    # Keep the account in step with the seat, so the colour this player is
    # using right now is the one their profile shows. A failure here must not
    # cost the room its update: the seat has already changed colour, and
    # skipping the broadcast would leave everyone else looking at the old one.
    if ctx.user_repo is not None and player.user_id:
        try:
            await ctx.user_repo.update_profile(
                player.user_id, name_color=player.name_color
            )
        except Exception:
            logger.exception(
                "Failed to store name colour for user %s", player.user_id
            )
    await ctx.game_flow._emit_room_state(room)
    return {"ok": True}


async def rename_player(ctx: HandlerContext, sid, data):
    """Change the name a guest is playing under, live.

    Guests are handed a generated name rather than being asked for one, so
    renaming has to be possible at any moment - including mid-game. The new
    name is stored on the account, which is what makes it survive a reload and
    follow the player into the next room.
    """
    try:
        payload = parse_payload(RenamePlayerPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, player = current

    if not player.is_anonymous:
        return {
            "ok": False,
            "error": "Registered players play as their username",
            "field": "nickname",
        }

    nickname = payload.nickname
    if ctx.user_repo is not None:
        owner = await ctx.user_repo.get_by_username(nickname)
        if owner is not None and not owner.is_anonymous:
            return {
                "ok": False,
                "error": "That name belongs to a registered player.",
                "field": "nickname",
            }

    previous = player.nickname
    if previous == nickname:
        return {"ok": True, "nickname": nickname}

    player.nickname = nickname
    if ctx.user_repo is not None and player.user_id:
        await ctx.user_repo.update_profile(player.user_id, display_name=nickname)

    await ctx.game_flow.announce(room, f"{previous} is now known as {nickname}.")
    await ctx.game_flow._emit_room_state(room)
    return {"ok": True, "nickname": nickname}


async def become_player(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, player = current
    if room.state != "waiting" or room.game:
        return {"ok": False, "error": "You can only join as a player from the waiting room"}
    if not player.is_spectator:
        return {"ok": False, "error": "You are already a player"}

    active_count = len(room.seated_players())
    if active_count >= room.max_players:
        return {"ok": False, "error": "Player slots are full"}

    player.is_spectator = False
    player.score = 0
    await ctx.game_flow.announce(room, f"{player.nickname} joined as a player.")
    await ctx.game_flow._emit_room_state(room)
    return {"ok": True}


async def leave_room(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return
    room, player = current
    ctx.timers.cancel_disconnect_timer(player.id)
    ctx.room_manager.remove_player(room, player.id)
    await ctx.sio.leave_room(sid, room.id)
    # Drop the room binding but keep the account: the socket stays open and the
    # player may immediately join another room as themselves.
    session = await ctx.sio.get_session(sid) or {}
    await ctx.sio.save_session(sid, {"user_id": session.get("user_id")})
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
    ctx.sio.on("rename_player", handler=partial(rename_player, ctx))
    ctx.sio.on("become_player", handler=partial(become_player, ctx))
    ctx.sio.on("leave_room", handler=partial(leave_room, ctx))
