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
from app.handlers.identity import (
    IdentityError,
    resolve_colorblind_safe_preference,
    resolve_identity,
)
from app.presenters import editable_room_settings_payload, session_payload
from app.services.game_flow import RoomPromptResolutionError
from app.services.persistent_rooms import (
    PersistentRoomError,
    PersistentRoomUnavailable,
)
from app.rooms import (
    ANONYMOUS_NAME_COLOR,
    RoomFullError,
    generate_random_room_name,
    generate_random_name_color,
    normalize_name_color,
)

logger = logging.getLogger("sketchy.handlers.rooms")


async def _room_for_code(ctx: HandlerContext, code: str):
    room = ctx.room_manager.get_room_by_code(code)
    if room is not None or ctx.persistent_rooms is None:
        return room
    return await ctx.persistent_rooms.materialize(ctx.room_manager, code)


async def _record_player_activity(ctx: HandlerContext, player) -> None:
    """Best-effort retention signal for a successfully seated player."""
    if (
        ctx.user_repo is None
        or not player.user_id
        or player.is_spectator
    ):
        return
    try:
        await ctx.user_repo.touch_last_active(player.user_id)
    except Exception:
        logger.exception("Failed to record activity for user %s", player.user_id)

async def create_room(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(CreateRoomPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    try:
        identity = await resolve_identity(
            ctx,
            sid,
            payload.nickname,
            payload.colorblind_safe_colors,
        )
    except IdentityError as error:
        return {"ok": False, "error": str(error), "field": "nickname"}
    try:
        settings = await ctx.game_flow.room_settings_from_payload(
            payload, requesting_user_id=identity.user_id
        )
    except RoomPromptResolutionError as error:
        return {"ok": False, "error": str(error), "field": "promptListSlugs"}

    if not settings["name"]:
        settings["name"] = generate_random_room_name()
    code = None
    persistent_config = None
    if ctx.room_codes is not None:
        try:
            code = await ctx.room_codes.allocate(
                kind="persistent" if payload.persistent else "ephemeral"
            )
        except Exception:
            logger.exception("Failed to allocate a room code")
            return {"ok": False, "error": "Could not create the room"}
    if payload.persistent:
        if code is None or ctx.persistent_rooms is None:
            if code is not None and ctx.room_codes is not None:
                await ctx.room_codes.release_unpublished(code)
            return {"ok": False, "error": "Persistent rooms require durable storage"}
        try:
            persistent_config = await ctx.persistent_rooms.create(
                owner_user_id=identity.user_id or "",
                code=code,
                settings=settings,
            )
        except (PersistentRoomError, ValueError) as error:
            await ctx.room_codes.release_unpublished(code)
            return {"ok": False, "error": str(error)}
    try:
        room = ctx.room_manager.create_room(
            **settings,
            code=code,
            persistent_room_id=(persistent_config.id if persistent_config else None),
            persistent_owner_user_id=(
                persistent_config.owner_user_id if persistent_config else None
            ),
            persistent_config_version=(
                persistent_config.version if persistent_config else None
            ),
        )
    except Exception:
        if persistent_config is not None and ctx.persistent_rooms is not None:
            await ctx.persistent_rooms.delete_unpublished(persistent_config.id)
        if code is not None and ctx.room_codes is not None:
            await ctx.room_codes.release_unpublished(code)
        raise
    player = ctx.room_manager.add_player(
        room,
        identity.nickname,
        name_color=identity.name_color or normalize_name_color(payload.name_color),
        user_id=identity.user_id,
        is_anonymous=identity.is_anonymous,
        colorblind_safe_colors=identity.colorblind_safe_colors,
    )
    await ctx.game_flow._join_socket_room(sid, room, player, is_reconnect=False)
    await _record_player_activity(ctx, player)
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


async def get_custom_prompts(ctx: HandlerContext, sid, data=None):
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
    return {"ok": True, "prompts": list(room.custom_prompts)}


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
    room, player = current
    # Resolving the prompt lists reads the repository, and the host may press
    # Start while that is in the air. Under the lock the game cannot begin
    # half-way through this, so a setting that arrived first is a setting the
    # game is played with.
    async with room.lock:
        if room.state != "waiting" or room.game:
            return {"ok": False, "error": "Settings can only be changed in the waiting room"}
        try:
            settings = await ctx.game_flow.room_settings_from_payload(
                payload,
                fallback=room,
                requesting_user_id=player.user_id,
            )
        except RoomPromptResolutionError as error:
            return {"ok": False, "error": str(error), "field": "promptListSlugs"}
        active_count = len(room.seated_players())
        if settings["max_players"] < active_count:
            return {"ok": False, "error": f"Max players cannot be below the {active_count} players already in the room"}
        if not settings["custom_prompts"]:
            settings["custom_prompts_only"] = False
        if room.persistent_room_id is not None:
            if (
                ctx.persistent_rooms is None
                or not player.user_id
                or player.user_id != room.persistent_owner_user_id
            ):
                return {
                    "ok": False,
                    "error": "Only the persistent room owner can change its settings",
                }
            try:
                room.persistent_config_version = await ctx.persistent_rooms.update(
                    room=room,
                    owner_user_id=player.user_id,
                    settings=settings,
                )
            except PersistentRoomError as error:
                return {"ok": False, "error": str(error)}
        for key, value in settings.items():
            setattr(room, key, value)
        # No announcement: settings save as the host touches them, so a line per
        # change would bury the lobby's conversation. Everyone sees the new
        # values in the room state this broadcast carries.
        await ctx.game_flow._emit_room_state(room)
    return {"ok": True}


async def get_room_preview(ctx: HandlerContext, sid, data):
    """Return invite-screen metadata without joining or exposing player details."""
    try:
        payload = parse_payload(RoomPreviewPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    try:
        room = await _room_for_code(ctx, payload.code)
    except PersistentRoomUnavailable as error:
        return {"ok": False, "error": str(error)}
    if not room:
        if ctx.room_codes is not None and await ctx.room_codes.is_retired(payload.code):
            return {
                "ok": False,
                "error": "This room has ended",
                "codeRetired": True,
            }
        return {"ok": False, "error": "Room not found"}
    return {"ok": True, "room": room.to_public_summary()}


async def join_room(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(JoinRoomPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    name_color = normalize_name_color(payload.name_color)

    room = ctx.room_manager.get_room(payload.room_id)
    if room is None and payload.code:
        try:
            room = await _room_for_code(ctx, payload.code)
        except PersistentRoomUnavailable as error:
            return {"ok": False, "error": str(error)}
    if not room:
        if (
            payload.code
            and ctx.room_codes is not None
            and await ctx.room_codes.is_retired(payload.code)
        ):
            return {
                "ok": False,
                "error": "This room has ended",
                "codeRetired": True,
            }
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
        already_joined.colorblind_safe_colors = (
            await resolve_colorblind_safe_preference(
                ctx,
                user_id=already_joined.user_id,
                is_anonymous=already_joined.is_anonymous,
                requested=payload.colorblind_safe_colors,
            )
        )
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
        await _record_player_activity(ctx, already_joined)
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
        player.colorblind_safe_colors = await resolve_colorblind_safe_preference(
            ctx,
            user_id=player.user_id,
            is_anonymous=player.is_anonymous,
            requested=payload.colorblind_safe_colors,
        )
        if not player.is_anonymous:
            stored = await _account_name_color(ctx, player.user_id)
            if stored or name_color:
                player.name_color = stored or name_color
        # _join_socket_room notifies and disconnects any socket that was
        # holding this seat before handing it to the new one.
        await ctx.game_flow._join_socket_room(sid, room, player, is_reconnect=True)
        await _record_player_activity(ctx, player)
        return session_payload(room, player)

    if payload.reconnect_only:
        return {"ok": False, "error": "No existing session in this room"}

    try:
        identity = await resolve_identity(
            ctx,
            sid,
            payload.nickname,
            payload.colorblind_safe_colors,
        )
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
            colorblind_safe_colors=identity.colorblind_safe_colors,
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
    await _record_player_activity(ctx, player)
    return session_payload(room, player)


async def _account_name_color(ctx: HandlerContext, user_id: str | None) -> str | None:
    """The color stored on an account, if it has one."""
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
        Phase.CHOOSING_PROMPT: 1,
        Phase.DRAWING: 2,
        Phase.TURN_RESULTS: 3,
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
    except PayloadError as error:
        if error.field == "nameColor":
            return {"ok": False, "error": "Invalid player name color"}
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, player = current
    if payload.colorblind_safe_colors is not None:
        player.colorblind_safe_colors = await resolve_colorblind_safe_preference(
            ctx,
            user_id=player.user_id,
            is_anonymous=player.is_anonymous,
            requested=payload.colorblind_safe_colors,
        )
    if player.is_anonymous:
        # Grey italics is what marks a name as unclaimed; letting guests recolour
        # would erase the only cue distinguishing them from registered players.
        if payload.name_color is not None:
            player.name_color = ANONYMOUS_NAME_COLOR
            await ctx.game_flow._emit_room_state(room)
            return {"ok": False, "error": "Create an account to choose a name color"}
        await ctx.game_flow._emit_colorblind_suggestion(room)
        return {"ok": True}
    if payload.name_color is not None:
        player.name_color = normalize_name_color(payload.name_color) or player.name_color
    # Keep the account in step with the seat, so the color this player is
    # using right now is the one their profile shows. A failure here must not
    # cost the room its update: the seat has already changed color, and
    # skipping the broadcast would leave everyone else looking at the old one.
    if payload.name_color is not None and ctx.user_repo is not None and player.user_id:
        try:
            await ctx.user_repo.update_profile(
                player.user_id, name_color=player.name_color
            )
        except Exception:
            logger.exception(
                "Failed to store name color for user %s", player.user_id
            )
    if payload.name_color is not None:
        await ctx.game_flow._emit_room_state(room)
    else:
        await ctx.game_flow._emit_colorblind_suggestion(room)
    return {"ok": True}


async def dismiss_colorblind_suggestion(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[1].is_host:
        return {"ok": False, "error": "Only the host can dismiss this suggestion"}
    room, _ = current
    room.colorblind_suggestion_dismissed = True
    await ctx.game_flow._emit_colorblind_suggestion(room)
    return {"ok": True}


async def archive_persistent_room(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, player = current
    if (
        room.persistent_room_id is None
        or ctx.persistent_rooms is None
        or not player.user_id
        or player.user_id != room.persistent_owner_user_id
    ):
        return {
            "ok": False,
            "error": "Only the persistent room owner can archive it",
        }
    async with room.lock:
        try:
            await ctx.persistent_rooms.archive(room=room, owner_user_id=player.user_id)
        except PersistentRoomError as error:
            return {"ok": False, "error": str(error)}
        room.persistent_room_id = None
        room.persistent_owner_user_id = None
        room.persistent_config_version = None
    await ctx.game_flow.announce(
        room, "This persistent room was archived. This live room ends when empty."
    )
    await ctx.game_flow._emit_room_state(room)
    return {"ok": True}


async def accept_colorblind_suggestion(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[1].is_host:
        return {"ok": False, "error": "Only the host can change room colors"}
    room, _ = current
    async with room.lock:
        if room.state != "waiting" or room.game:
            return {
                "ok": False,
                "error": "Room colors can only be changed in the waiting room",
            }
        if (
            room.colorblind_suggestion_dismissed
            or room.color_mode == "colorblind_safe"
            or not any(
                player.colorblind_safe_colors and not player.is_spectator
                for player in room.players.values()
            )
        ):
            return {"ok": False, "error": "This suggestion is no longer active"}
        room.color_mode = "colorblind_safe"
        room.colorblind_suggestion_dismissed = True
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
        await ctx.remove_room_if_empty(room.id)
    else:
        await ctx.game_flow._remove_player_from_game(room, player.id)
        await ctx.sio.emit("player_left", {"playerId": player.id}, room=room.id)
        await ctx.game_flow._emit_room_state(room)


def register(ctx: HandlerContext) -> None:
    ctx.sio.on("create_room", handler=partial(create_room, ctx))
    ctx.sio.on("get_room_settings", handler=partial(get_room_settings, ctx))
    ctx.sio.on("get_custom_prompts", handler=partial(get_custom_prompts, ctx))
    ctx.sio.on("get_recap_drawing", handler=partial(get_recap_drawing, ctx))
    ctx.sio.on("update_room_settings", handler=partial(update_room_settings, ctx))
    ctx.sio.on("get_room_preview", handler=partial(get_room_preview, ctx))
    ctx.sio.on("join_room", handler=partial(join_room, ctx))
    ctx.sio.on("session_ping", handler=partial(session_ping, ctx))
    ctx.sio.on("update_player_settings", handler=partial(update_player_settings, ctx))
    ctx.sio.on(
        "archive_persistent_room",
        handler=partial(archive_persistent_room, ctx),
    )
    ctx.sio.on(
        "dismiss_colorblind_suggestion",
        handler=partial(dismiss_colorblind_suggestion, ctx),
    )
    ctx.sio.on(
        "accept_colorblind_suggestion",
        handler=partial(accept_colorblind_suggestion, ctx),
    )
    ctx.sio.on("rename_player", handler=partial(rename_player, ctx))
    ctx.sio.on("become_player", handler=partial(become_player, ctx))
    ctx.sio.on("leave_room", handler=partial(leave_room, ctx))
