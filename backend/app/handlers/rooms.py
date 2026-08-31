"""Socket.IO handlers for the rooms domain."""
from __future__ import annotations

import asyncio
import logging
from functools import partial

from app.game import Phase
from app.handlers.context import HandlerContext
from app.services.runtime_metrics import metrics
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
from app.domain_values import RuntimeEventType
from app.services.game_flow import RoomPromptResolutionError
from app.services.room_quotas import RoomQuotaExceeded
from app.rooms import (
    _metrics_user_id as metrics_user_id,
    ANONYMOUS_NAME_COLOR,
    RoomFullError,
    generate_random_room_name,
    generate_random_name_color,
    normalize_name_color,
)

logger = logging.getLogger("sketchy.handlers.rooms")

# Nothing bounded the database work on the way into a room, and since #480
# that is worse than a slow join: seat transitions hold the socket's seating
# gate, and its disconnect queues at the same gate so that a socket dropping
# mid-entry reconciles against a seat that already exists. An entry that never
# returns therefore holds the gate for ever, and a socket that drops during it
# never reconciles - the seat keeps `connected` and its sid, its room never
# counts as empty, and the leak #480 closed is open again by way of a stall.
#
# The same ten seconds the finished-game write already allows: long enough for
# a healthy write on a loaded server, short enough that a hung database cannot
# pin the coroutine that seats a player.
ENTRY_DB_TIMEOUT_SECONDS = 10


class EntryTimedOut(RuntimeError):
    """A database call on the way into a room did not answer in time."""


async def _bounded(awaitable, what: str):
    """Await one entry-path call, or give up and let the entry refuse."""
    try:
        return await asyncio.wait_for(awaitable, timeout=ENTRY_DB_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.error("Timed out on %s after %ss", what, ENTRY_DB_TIMEOUT_SECONDS)
        raise EntryTimedOut(what) from None


async def _give_back_code(ctx: HandlerContext, code: str | None) -> None:
    """Release a reservation the room never used, without hanging on it.

    On the failure path, and still inside the seating gate: a cleanup that
    hangs turns a refused entry into a pinned one. A reservation left behind
    because this timed out is reclaimed by `retire_orphaned_ephemeral` at
    startup, the same sweep that handles one left claimed by a crash.
    """
    if code is None or ctx.room_codes is None:
        return
    try:
        await _bounded(ctx.room_codes.release_unpublished(code), "releasing a room code")
    except EntryTimedOut:
        pass
    except Exception:
        # Best-effort, like every cleanup here: this one runs while an earlier
        # failure is still on its way up, and raising over it would lose the
        # real error and leave the client with no acknowledgement at all.
        logger.exception("Failed to release room code %s", code)


async def _give_back_allowance(ctx: HandlerContext, user_id) -> None:
    """Return a creation allowance the room never used, best-effort."""
    if not user_id:
        return
    try:
        await _bounded(
            ctx.room_quotas.refund_creation(user_id), "returning a creation allowance"
        )
    except EntryTimedOut:
        pass
    except Exception:
        logger.exception("Failed to refund a creation allowance for user %s", user_id)


ENDED_ACCOUNT_ACKNOWLEDGEMENT = {
    "ok": False,
    "error": "This account is no longer active.",
}


BUSY_ACKNOWLEDGEMENT = {
    "ok": False,
    "error": "Sketchy is having trouble reaching its database. Please try again.",
}


async def _seat_colour_preference(ctx: HandlerContext, player, requested: bool) -> bool:
    """Resolve a returning seat's colour preference, keeping it on a stall.

    Falling back to what the client asked for would let a payload set a
    registered account's preference for as long as the database is slow, which
    is the spoof `resolve_colorblind_safe_preference` exists to prevent. The
    seat already carries the resolved value, so keeping it is both safe and
    right. A guest has nothing stored - their payload is the authority, and
    their resolution never reaches the database to stall in the first place.
    """
    try:
        return await _bounded(
            resolve_colorblind_safe_preference(
                ctx,
                user_id=player.user_id,
                is_anonymous=player.is_anonymous,
                requested=requested,
            ),
            "reading a colour preference",
        )
    except EntryTimedOut:
        return requested if player.is_anonymous else player.colorblind_safe_colors


async def _record_player_activity(ctx: HandlerContext, player) -> None:
    """Best-effort retention signal for a successfully seated player."""
    if (
        ctx.user_repo is None
        or not player.user_id
        or player.is_spectator
    ):
        return
    try:
        # Bounded like the rest of the entry path. It runs outside the gate,
        # so a hang here no longer strands a seat - but it still holds up the
        # acknowledgement the player is waiting for.
        await _bounded(
            ctx.user_repo.touch_last_active(player.user_id), "recording activity"
        )
    except EntryTimedOut:
        pass
    except Exception:
        logger.exception("Failed to record activity for user %s", player.user_id)

async def _unseat_an_ended_account(ctx: HandlerContext, room, player) -> dict:
    """Take back a seat the account lost the right to while taking it.

    The check before seating is not enough on its own: `_join_socket_room`
    awaits, and the sweep marking this socket can land in one of those gaps.
    Refusing without removing the seat would leave the account seated until
    the disconnect queued at this gate ran it down through the reconnect
    grace, which is the window R-BAN-02 exists to close.
    """
    await ctx.evict_player(room, player.id)
    return ENDED_ACCOUNT_ACKNOWLEDGEMENT


async def _after_seating(ctx: HandlerContext, seated: list) -> None:
    """The database work a new seat causes, once the gate has been released.

    Deliberately after the gate rather than before: the seat already exists by
    then, and none of this is part of making it. Held inside, it would keep a
    disconnect - a dropped connection, or the sweep closing this socket after
    a ban - waiting behind writes that have nothing to do with the seat.
    """
    for player in seated:
        await _record_player_activity(ctx, player)
        await _warm_block_filter(ctx, player)


async def _warm_block_filter(ctx: HandlerContext, player) -> None:
    """Read this player's blockers now, so no message of theirs has to.

    The chat path filters every line by who has muted the sender, and a cold
    read there would be felt as the room going quiet. The cost is paid here
    instead, where waiting is what entering a room already does.
    """
    if ctx.block_service is None or not player.user_id:
        return
    try:
        await _bounded(ctx.block_service.warm(player.user_id), "reading blocks")
    except EntryTimedOut:
        pass
    except Exception:
        logger.exception("Failed to warm the block filter for user %s", player.user_id)


async def create_room(ctx: HandlerContext, sid, data):
    """Open a room and seat this socket in it, releasing any seat it held."""
    seated: list = []
    async with ctx.seating(sid):
        answer = await _create_room(ctx, sid, data, seated)
    await _after_seating(ctx, seated)
    return answer


async def _create_room(ctx: HandlerContext, sid, data, seated: list):
    try:
        payload = parse_payload(CreateRoomPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    if ctx.shutdown is not None and ctx.shutdown.refuses_new_work:
        return ctx.shutdown.rejection_acknowledgement()
    try:
        identity = await _bounded(
            resolve_identity(
                ctx,
                sid,
                payload.nickname,
                payload.colorblind_safe_colors,
            ),
            "resolving who is entering",
        )
    except IdentityError as error:
        return {"ok": False, "error": str(error), "field": "nickname"}
    except EntryTimedOut:
        return BUSY_ACKNOWLEDGEMENT
    if not identity.user_id:
        # Joining stays open to a socket with no account - R-HIST-10 gives it
        # a factual seat - but creating is the command that allocates a room,
        # a code reservation and a prompt pool, and a ceiling nothing can be
        # keyed on is not a ceiling.
        return {
            "ok": False,
            "error": (
                "Sketchy could not start a session for you, so it cannot open "
                "a room. Allow cookies for this site and reload."
            ),
        }
    try:
        ctx.room_quotas.check_capacity(identity.user_id)
    except RoomQuotaExceeded as error:
        return {"ok": False, "error": str(error)}
    try:
        settings = await _bounded(
            ctx.game_flow.room_settings_from_payload(
                payload, requesting_user_id=identity.user_id
            ),
            "resolving the room's prompt lists",
        )
    except RoomPromptResolutionError as error:
        return {"ok": False, "error": str(error), "field": "promptListSlugs"}
    except EntryTimedOut:
        return BUSY_ACKNOWLEDGEMENT
    try:
        ctx.room_quotas.check_retained_prompts(settings["custom_prompts"])
        # Last of the four, because it is the only one that writes: an attempt
        # refused by a ceiling above should not also spend an allowance.
        await _bounded(
            ctx.room_quotas.check_creation_rate(identity.user_id),
            "checking the room-creation allowance",
        )
    except RoomQuotaExceeded as error:
        return {"ok": False, "error": str(error)}
    except EntryTimedOut:
        # Deliberately not refunded. The attempt may have been recorded before
        # the wait was cut short, and a refund that guesses wrong hands back
        # an allowance nobody spent - which raises a ceiling rather than
        # lowering one. Costing this caller one of their own hourly attempts
        # is the cheaper mistake.
        return BUSY_ACKNOWLEDGEMENT
    # From here on the allowance has been spent, and everything below can
    # still refuse: a drain beginning, an allocation failing, the capacity
    # re-check losing its race. An attempt that opens no room gives it back.
    created = False
    try:
        if ctx.shutdown is not None and ctx.shutdown.refuses_new_work:
            return ctx.shutdown.rejection_acknowledgement()

        if not settings["name"]:
            settings["name"] = generate_random_room_name()
        code = None
        if ctx.room_codes is not None:
            try:
                code = await _bounded(
                    ctx.room_codes.allocate(), "allocating a room code"
                )
            except EntryTimedOut:
                # The reservation may or may not have committed before the
                # wait was cut short. `retire_orphaned_ephemeral` at startup
                # is what reclaims a code left claimed this way, exactly as it
                # does for one left claimed by a crash.
                return BUSY_ACKNOWLEDGEMENT
            except Exception:
                logger.exception("Failed to allocate a room code")
                return {"ok": False, "error": "Could not create the room"}
            if ctx.shutdown is not None and ctx.shutdown.refuses_new_work:
                await _give_back_code(ctx, code)
                return ctx.shutdown.rejection_acknowledgement()
        if ctx.shutdown is not None and ctx.shutdown.refuses_new_work:
            await _give_back_code(ctx, code)
            return ctx.shutdown.rejection_acknowledgement()
        try:
            # Everything above this line awaited, and a second create_room from
            # this account may have arrived in one of those gaps. This is the last
            # instant where the answer and the room are not separated by an await.
            ctx.room_quotas.check_capacity(identity.user_id)
        except RoomQuotaExceeded as error:
            await _give_back_code(ctx, code)
            return {"ok": False, "error": str(error)}
        if ctx.is_ending(sid):
            # A ban or a deletion landed while this entry held the gate. The
            # sweep that closes this socket is waiting at that gate right now,
            # so seating here would hand the account a seat the sweep has
            # already walked past.
            await _give_back_code(ctx, code)
            return ENDED_ACCOUNT_ACKNOWLEDGEMENT
        try:
            room = ctx.room_manager.create_room(
                **settings,
                code=code,
                created_by_user_id=identity.user_id,
            )
        except Exception:
            await _give_back_code(ctx, code)
            raise
        created = True
    finally:
        if not created:
            # In a `finally`, so a raise here would replace whatever sent us
            # down this path; the helper swallows and logs instead.
            await _give_back_allowance(ctx, identity.user_id)
    player = ctx.room_manager.add_player(
        room,
        identity.nickname,
        name_color=identity.name_color or normalize_name_color(payload.name_color),
        user_id=identity.user_id,
        is_anonymous=identity.is_anonymous,
        colorblind_safe_colors=identity.colorblind_safe_colors,
    )
    await ctx.game_flow._join_socket_room(sid, room, player, is_reconnect=False)
    if ctx.is_ending(sid):
        return await _unseat_an_ended_account(ctx, room, player)
    seated.append(player)
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
        try:
            ctx.room_quotas.check_retained_prompts(
                settings["custom_prompts"], replacing=room
            )
        except RoomQuotaExceeded as error:
            return {"ok": False, "error": str(error), "field": "customPrompts"}
        for key, value in settings.items():
            if key == "custom_prompts":
                ctx.room_manager.set_custom_prompts(room, value)
                continue
            setattr(room, key, value)
        # No announcement: settings save as the host touches them, so a line per
        # change would bury the lobby's conversation. Everyone sees the new
        # values in the room state this broadcast carries.
        await ctx.game_flow._emit_room_state(room)
    return {"ok": True}


async def get_room_preview(ctx: HandlerContext, sid, data):
    """Return invite-screen metadata, and who is seated, without joining.

    The roster is answered here rather than in the polled room list: one room,
    when somebody asks, instead of every public room every few seconds.
    """
    try:
        payload = parse_payload(RoomPreviewPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    room = ctx.room_manager.get_room_by_code(payload.code)
    if not room:
        try:
            retired = ctx.room_codes is not None and await _bounded(
                ctx.room_codes.is_retired(payload.code), "reading the room code"
            )
        except EntryTimedOut:
            return BUSY_ACKNOWLEDGEMENT
        if retired:
            return {
                "ok": False,
                "error": "This room has ended",
                "codeRetired": True,
            }
        return {"ok": False, "error": "Room not found"}
    return {
        "ok": True,
        "room": room.to_public_summary(),
        "players": room.to_public_roster(),
    }


async def join_room(ctx: HandlerContext, sid, data):
    """Seat this socket in the named room, releasing any seat it held."""
    seated: list = []
    async with ctx.seating(sid):
        answer = await _join_room(ctx, sid, data, seated)
    await _after_seating(ctx, seated)
    return answer


async def _join_room(ctx: HandlerContext, sid, data, seated: list):
    try:
        payload = parse_payload(JoinRoomPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    name_color = normalize_name_color(payload.name_color)

    room = ctx.room_manager.get_room(payload.room_id)
    if room is None and payload.code:
        room = ctx.room_manager.get_room_by_code(payload.code)
    if not room:
        try:
            retired = (
                payload.code
                and ctx.room_codes is not None
                and await _bounded(
                    ctx.room_codes.is_retired(payload.code), "reading the room code"
                )
            )
        except EntryTimedOut:
            return BUSY_ACKNOWLEDGEMENT
        if retired:
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
        already_joined.colorblind_safe_colors = await _seat_colour_preference(
            ctx, already_joined, payload.colorblind_safe_colors
        )
        already_joined.sid = sid
        already_joined.connected = True
        ctx.timers.cancel_disconnect_timer(already_joined.id)
        # This confirmation is the only entry that does not pass through
        # `_join_socket_room`, and a client heartbeats through it. Reconciling
        # here too is what lets a seat stranded elsewhere - by an older build,
        # or by a crash between the two halves of a move - be reclaimed
        # without waiting for the socket to drop.
        await ctx.game_flow.release_other_seats(
            sid, keep=(room.id, already_joined.id)
        )
        # Soft checks (heartbeat/visibility) must not dump full canvas history.
        await ctx.game_flow._sync_player_view(
            sid,
            room,
            already_joined,
            sync_canvas=not payload.soft,
        )
        if ctx.is_ending(sid):
            return await _unseat_an_ended_account(ctx, room, already_joined)
        seated.append(already_joined)
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
        player.colorblind_safe_colors = await _seat_colour_preference(
            ctx, player, payload.colorblind_safe_colors
        )
        if not player.is_anonymous:
            stored = await _account_name_color(ctx, player.user_id)
            if stored or name_color:
                player.name_color = stored or name_color
        if not ctx.room_capacity.admits_a_takeover(player.id):
            return {
                "ok": False,
                "error": "This seat is changing hands too quickly. Try again in a minute.",
            }
        # _join_socket_room notifies and disconnects any socket that was
        # holding this seat before handing it to the new one.
        metrics.record(
            RuntimeEventType.PLAYER_RECONNECTED,
            room_id=room.id,
            user_id=metrics_user_id(player.user_id),
        )
        if ctx.is_ending(sid):
            return ENDED_ACCOUNT_ACKNOWLEDGEMENT
        await ctx.game_flow._join_socket_room(sid, room, player, is_reconnect=True)
        if ctx.is_ending(sid):
            return await _unseat_an_ended_account(ctx, room, player)
        seated.append(player)
        return session_payload(room, player)

    if payload.reconnect_only:
        return {"ok": False, "error": "No existing session in this room"}

    try:
        identity = await _bounded(
            resolve_identity(
                ctx,
                sid,
                payload.nickname,
                payload.colorblind_safe_colors,
            ),
            "resolving who is entering",
        )
    except IdentityError as error:
        return {"ok": False, "error": str(error), "field": "nickname"}
    except EntryTimedOut:
        return BUSY_ACKNOWLEDGEMENT

    if payload.as_spectator and not ctx.room_capacity.admits_a_spectator(room):
        # Deliberately without `roomFull`: that flag is what makes the client
        # offer spectating instead, and offering it to somebody refused *as* a
        # spectator is a loop.
        return {
            "ok": False,
            "error": "This room is not taking any more spectators.",
        }
    if not ctx.room_capacity.admits_a_join(sid):
        return {
            "ok": False,
            "error": "You are joining rooms too quickly. Try again in a minute.",
        }

    if ctx.is_ending(sid):
        return ENDED_ACCOUNT_ACKNOWLEDGEMENT
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
        ctx.room_capacity.refund_join(sid)
        return {"ok": False, "error": "Room is full", "roomFull": True}
    except Exception:
        # Any other way seating can fail is equally not a join.
        ctx.room_capacity.refund_join(sid)
        raise

    # A game already in progress keeps running its existing turn_order -
    # joining mid-game just enrolls the new player into future turns
    # (appended to the end, so everyone already playing keeps their
    # relative order) rather than blocking the join entirely.
    if room.game and not player.is_spectator:
        room.game.add_player_to_rotation(player.id)

    await ctx.game_flow._join_socket_room(sid, room, player, is_reconnect=False)
    if ctx.is_ending(sid):
        return await _unseat_an_ended_account(ctx, room, player)
    seated.append(player)
    return session_payload(room, player)


async def _account_name_color(ctx: HandlerContext, user_id: str | None) -> str | None:
    """The color stored on an account, if it has one."""
    if ctx.user_repo is None or not user_id:
        return None
    try:
        account = await _bounded(
            ctx.user_repo.get_by_id(user_id), "reading an account's colour"
        )
    except EntryTimedOut:
        return None
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
    try:
        account = await _bounded(
            ctx.user_repo.get_by_id(player.user_id), "refreshing a seat's identity"
        )
    except EntryTimedOut:
        # The seat keeps the name it has. Worth less than the entry it would
        # otherwise hold up.
        return
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
    async with ctx.seating(sid):
        current = await ctx.game_flow.require_current_player(sid)
        if not current:
            return
        room, player = current
        await ctx.game_flow.release_seat(sid, room, player)


def register(ctx: HandlerContext) -> None:
    ctx.on("create_room", handler=partial(create_room, ctx))
    ctx.on("get_room_settings", handler=partial(get_room_settings, ctx))
    ctx.on("get_custom_prompts", handler=partial(get_custom_prompts, ctx))
    ctx.on("get_recap_drawing", handler=partial(get_recap_drawing, ctx))
    ctx.on("update_room_settings", handler=partial(update_room_settings, ctx))
    ctx.on("get_room_preview", handler=partial(get_room_preview, ctx))
    ctx.on("join_room", handler=partial(join_room, ctx))
    ctx.on("session_ping", handler=partial(session_ping, ctx))
    ctx.on("update_player_settings", handler=partial(update_player_settings, ctx))
    ctx.on(
        "dismiss_colorblind_suggestion",
        handler=partial(dismiss_colorblind_suggestion, ctx),
    )
    ctx.on(
        "accept_colorblind_suggestion",
        handler=partial(accept_colorblind_suggestion, ctx),
    )
    ctx.on("rename_player", handler=partial(rename_player, ctx))
    ctx.on("become_player", handler=partial(become_player, ctx))
    ctx.on("leave_room", handler=partial(leave_room, ctx))
