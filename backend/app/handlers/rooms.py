"""Socket.IO handlers for the rooms domain."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial

from app.announcements import Announcement
from app.game import Phase
from app.handlers.context import HandlerContext
from app.services.runtime_metrics import metrics
from app.services.telemetry import telemetry
from app.handlers.payloads import (
    CreateRoomPayload,
    QuickPlayPayload,
    JoinRoomPayload,
    LeaveRoomPayload,
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
    NAME_IN_USE_MESSAGE,
    IdentityError,
    resolve_colorblind_safe_preference,
    resolve_identity,
)
from app.presenters import editable_room_settings_payload, session_payload
from app.services.guest_names import online_guest_holding
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
from app.drawing_rules import DEFAULT_COLOR_MODE
from app.handlers.refusals import ErrorCode, refuse

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

# And one deadline for the whole entry (#879). The bound above is per call,
# and creating a room makes four in a row - forty seconds against a client
# that gives up after eight (`DEFAULT_ACK_TIMEOUT_MS`). Under a slow database
# the player was told it failed, pressed again, and the first room existed
# anyway with the socket seated in it: a spent creation allowance, one of the
# three rooms an account may hold, and after Quick play's fallback a public
# waiting room nobody would ever start. So every entry - create, join, join a
# friend - is given six seconds from arrival, the wait for the seating gate
# included; each call gets what is left, and past it the entry refuses with
# nothing created. The two seconds left over are for the answer to travel, so
# a refusal the client sees means there is no room.
ENTRY_DEADLINE_SECONDS = 6.0

# How long a `create_room` request id is remembered (#879): long enough for a
# client's retry after its own timeout, a reconnect included; short enough that
# a stale id cannot hand somebody back a room they have long since left.
CREATE_REQUEST_MEMORY_SECONDS = 60.0

_entry_deadline: ContextVar[float | None] = ContextVar("entry_deadline", default=None)


class EntryTimedOut(RuntimeError):
    """A database call on the way into a room did not answer in time."""


@contextmanager
def entry_deadline():
    """Start this entry's deadline; an enclosing one is kept, never extended."""
    if _entry_deadline.get() is not None:
        yield
        return
    token = _entry_deadline.set(asyncio.get_running_loop().time() + ENTRY_DEADLINE_SECONDS)
    try:
        yield
    finally:
        _entry_deadline.reset(token)


def entry_expired() -> bool:
    """Whether this entry has run out of time. Checked at the last instant
    before a room or a seat is made, with nothing awaited between."""
    deadline = _entry_deadline.get()
    return deadline is not None and asyncio.get_running_loop().time() >= deadline


async def _bounded(awaitable, what: str, *, within_entry: bool = True):
    """Await one entry-path call, or give up and let the entry refuse.

    Inside an entry the call gets whatever of the deadline is left, and none
    at all once it has passed. `within_entry=False` is for a cleanup that
    gives something back on the way out, which must not be skipped because
    the entry it cleans up after ran late.
    """
    timeout = ENTRY_DB_TIMEOUT_SECONDS
    deadline = _entry_deadline.get() if within_entry else None
    if deadline is not None:
        timeout = min(timeout, deadline - asyncio.get_running_loop().time())
        if timeout <= 0:
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            logger.error("Out of entry time before %s", what)
            raise EntryTimedOut(what)
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError:
        logger.error("Timed out on %s after %.1fs", what, timeout)
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
        await _bounded(
            ctx.room_codes.release_unpublished(code), "releasing a room code", within_entry=False
        )
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
            ctx.room_quotas.refund_creation(user_id),
            "returning a creation allowance",
            within_entry=False,
        )
    except EntryTimedOut:
        pass
    except Exception:
        logger.exception("Failed to refund a creation allowance for user %s", user_id)


ENDED_ACCOUNT_ACKNOWLEDGEMENT = {
    "ok": False, "errorCode": ErrorCode.ACCOUNT_ENDED,
    "error": "This account is no longer active.",
}


ACCOUNT_REQUIRED_TO_OPEN = {
    "ok": False,
    "errorCode": ErrorCode.ACCOUNT_REQUIRED,
    "error": (
        "Sketchy could not start a session for you, so it cannot open "
        "a room. Allow cookies for this site and reload."
    ),
}


BUSY_ACKNOWLEDGEMENT = {
    "ok": False, "errorCode": ErrorCode.DATABASE_BUSY,
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


_activity_writes: set[asyncio.Task] = set()


async def _record_player_activity(ctx: HandlerContext, player) -> None:
    """Best-effort retention signal for a successfully seated player.

    Run on its own rather than awaited by the entry (#980): it is a retention
    signal, nothing about the seat depends on it, and awaited it was a write
    transaction between the seat and the acknowledgement of every join.
    """
    if (
        ctx.user_repo is None
        or not player.user_id
        or player.is_spectator
    ):
        return
    try:
        # Bounded like the rest of the entry path, so a hang cannot keep the
        # task alive for ever. Nobody waits on it: it runs after the
        # acknowledgement, on its own (#980).
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
        # Not awaited, so the acknowledgement does not wait for a retention
        # signal (#980) - the same bargain `_record_last_seen` makes.
        task = asyncio.create_task(_record_player_activity(ctx, player))
        _activity_writes.add(task)
        task.add_done_callback(_activity_writes.discard)
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
    with entry_deadline():
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
        return {"ok": False, "errorCode": error.error_code, "error": str(error), "field": "nickname"}
    except EntryTimedOut:
        return BUSY_ACKNOWLEDGEMENT
    if not identity.user_id:
        # Joining stays open to a socket with no account - R-HIST-10 gives it
        # a factual seat - but creating is the command that allocates a room,
        # a code reservation and a prompt pool, and a ceiling nothing can be
        # keyed on is not a ceiling.
        return ACCOUNT_REQUIRED_TO_OPEN
    repeat = _room_already_created(ctx, identity.user_id, payload.request_id)
    if repeat is not None:
        # A retry of a creation that happened: the answer was lost, or came
        # after the client had given up. Seat this socket back in that room -
        # the account's own seat - and spend nothing.
        return await _seat_in_room(
            ctx, sid, repeat, _EnteringAs(payload), seated
        )
    key = (identity.user_id, payload.request_id) if payload.request_id else None
    if key is not None:
        leader = ctx.room_creations_in_flight.get(key)
        if leader is not None:
            # The same press arriving again on another socket while the first
            # is still being made - a retry from the replacement socket of a
            # connection that dropped mid-creation. Sockets have separate
            # seating gates, so without this both would make a room. Wait for
            # the first, then take its room; if it failed, try again here.
            try:
                made = await _bounded(asyncio.shield(leader), "waiting for the same creation")
            except EntryTimedOut:
                return BUSY_ACKNOWLEDGEMENT
            # The first copy's own room, from its own future - not the
            # account's memo, which another tab's creation may have moved on.
            repeat = ctx.room_manager.get_room(made) if made else None
            if repeat is not None and ctx.room_manager.get_player_by_user_id(repeat, identity.user_id):
                return await _seat_in_room(ctx, sid, repeat, _EnteringAs(payload), seated)
            if key in ctx.room_creations_in_flight:
                return BUSY_ACKNOWLEDGEMENT
        leader = asyncio.get_running_loop().create_future()
        ctx.room_creations_in_flight[key] = leader
    answer: dict | None = None
    try:
        answer = await _create_new_room(ctx, sid, payload, identity, seated)
        return answer
    finally:
        if key is not None:
            del ctx.room_creations_in_flight[key]
            made = answer.get("roomId") if answer and answer.get("ok") else None
            leader.set_result(made)


async def _create_new_room(ctx: HandlerContext, sid, payload, identity, seated: list):
    """Everything a creation does once it is known not to be a repeat."""
    try:
        ctx.room_quotas.check_capacity(identity.user_id)
    except RoomQuotaExceeded as error:
        return {"ok": False, "errorCode": ErrorCode.ROOM_QUOTA, "error": str(error)}
    try:
        settings = await _bounded(
            ctx.game_flow.room_settings_from_payload(
                payload, requesting_user_id=identity.user_id
            ),
            "resolving the room's prompt lists",
        )
    except RoomPromptResolutionError as error:
        return {"ok": False, "errorCode": ErrorCode.INVALID_PROMPT_LISTS, "error": str(error), "field": "promptListSlugs"}
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
        return {"ok": False, "errorCode": ErrorCode.ROOM_QUOTA, "error": str(error)}
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
                return {"ok": False, "errorCode": ErrorCode.COULD_NOT_CREATE_ROOM, "error": "Could not create the room"}
            if ctx.shutdown is not None and ctx.shutdown.refuses_new_work:
                await _give_back_code(ctx, code)
                return ctx.shutdown.rejection_acknowledgement()
        if ctx.shutdown is not None and ctx.shutdown.refuses_new_work:
            await _give_back_code(ctx, code)
            return ctx.shutdown.rejection_acknowledgement()
        # Whatever this socket sat in goes first (R-ROOM-08), before the
        # checks below rather than inside the seating that follows them, and
        # with the old room's durable teardown deferred: waited on, it could
        # hold the answer past the deadline - with the new room already made,
        # had it come after (#879).
        await ctx.game_flow.release_other_seats(sid)
        try:
            # Everything above this line awaited, and a second create_room from
            # this account may have arrived in one of those gaps. This is the last
            # instant where the answer and the room are not separated by an await.
            ctx.room_quotas.check_capacity(identity.user_id)
        except RoomQuotaExceeded as error:
            await _give_back_code(ctx, code)
            return {"ok": False, "errorCode": ErrorCode.ROOM_QUOTA, "error": str(error)}
        if ctx.is_ending(sid):
            # A ban or a deletion landed while this entry held the gate. The
            # sweep that closes this socket is waiting at that gate right now,
            # so seating here would hand the account a seat the sweep has
            # already walked past.
            await _give_back_code(ctx, code)
            return ENDED_ACCOUNT_ACKNOWLEDGEMENT
        if entry_expired():
            # The last instant before the room exists, with nothing awaited
            # after it: past the deadline the client may already have given
            # up, and a room it was told failed must not exist (#879).
            await _give_back_code(ctx, code)
            return BUSY_ACKNOWLEDGEMENT
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
        avatar_key=identity.avatar_key,
    )
    await ctx.game_flow._join_socket_room(sid, room, player, is_reconnect=False)
    if ctx.is_ending(sid):
        return await _unseat_an_ended_account(ctx, room, player)
    _remember_creation(ctx, identity.user_id, payload.request_id, room.id)
    seated.append(player)
    return session_payload(room, player)


class _EnteringAs:
    """A creation's identity fields in the shape `_seat_in_room` reads."""

    def __init__(self, payload) -> None:
        self.nickname = payload.nickname
        self.name_color = payload.name_color
        self.colorblind_safe_colors = payload.colorblind_safe_colors
        self.as_spectator = False


def _remember_creation(ctx: HandlerContext, user_id: str, request_id: str | None, room_id: str) -> None:
    now = time.monotonic()
    memory = ctx.recent_room_creations
    for account in [a for a, (_, _, until) in memory.items() if until <= now]:
        del memory[account]
    if request_id:
        memory[user_id] = (request_id, room_id, now + CREATE_REQUEST_MEMORY_SECONDS)


def _room_already_created(ctx: HandlerContext, user_id: str, request_id: str | None):
    """The room a repeat of this request made, if it is still this account's.

    Only while the account's seat is still in it: a room the creator has left
    is not theirs to be handed back, and a new one is what they are asking
    for.
    """
    if not request_id:
        return None
    remembered = ctx.recent_room_creations.get(user_id)
    if remembered is None or remembered[0] != request_id or remembered[2] <= time.monotonic():
        return None
    room = ctx.room_manager.get_room(remembered[1])
    if room is None or ctx.room_manager.get_player_by_user_id(room, user_id) is None:
        return None
    return room


async def get_room_settings(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[1].is_host:
        return {"ok": False, "errorCode": ErrorCode.HOST_ONLY, "error": "Only the host can view room rules"}
    room, _ = current
    return {"ok": True, "settings": editable_room_settings_payload(room)}


async def get_custom_prompts(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "errorCode": ErrorCode.NOT_IN_ROOM, "error": "Not in this room"}
    room, player = current
    if player.is_spectator:
        return {"ok": False, "errorCode": ErrorCode.PLAYERS_ONLY, "error": "Only players can view custom prompts"}
    if room.state != "waiting" or room.game:
        return {
            "ok": False, "errorCode": ErrorCode.WAITING_ROOM_ONLY,
            "error": "Custom prompts can only be viewed in the waiting room",
        }
    return {"ok": True, "prompts": list(room.custom_prompts)}


async def get_recap_drawing(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(RecapDrawingPayload, data)
    except PayloadError:
        return {"ok": False, "errorCode": ErrorCode.DRAWING_NOT_FOUND, "error": "Drawing not found"}
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "errorCode": ErrorCode.NOT_IN_ROOM, "error": "Not in this room"}
    room, _ = current
    if payload.index >= len(room.last_game_drawings):
        return {"ok": False, "errorCode": ErrorCode.DRAWING_NOT_FOUND, "error": "Drawing not found"}
    drawing = room.last_game_drawings[payload.index]
    if not drawing.is_available:
        # Given up to keep the room's recap inside its budget. Distinct from
        # "not found" so the client can say so plainly instead of offering a
        # retry for something that is never coming back.
        return {
            "ok": False, "errorCode": ErrorCode.DRAWING_NOT_KEPT,
            "error": "This drawing was not kept",
        }
    return {"ok": True, "drawing": drawing.payload(payload.index)}


async def update_room_settings(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(UpdateRoomSettingsPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[1].is_host:
        return {"ok": False, "errorCode": ErrorCode.HOST_ONLY, "error": "Only the host can change room rules"}
    room, player = current
    # Resolving the prompt lists reads the repository, and the host may press
    # Start while that is in the air. Under the lock the game cannot begin
    # half-way through this, so a setting that arrived first is a setting the
    # game is played with.
    async with room.lock:
        if room.state != "waiting" or room.game:
            return {"ok": False, "errorCode": ErrorCode.WAITING_ROOM_ONLY, "error": "Settings can only be changed in the waiting room"}
        try:
            settings = await ctx.game_flow.room_settings_from_payload(
                payload,
                fallback=room,
                requesting_user_id=player.user_id,
            )
        except RoomPromptResolutionError as error:
            return {"ok": False, "errorCode": ErrorCode.INVALID_PROMPT_LISTS, "error": str(error), "field": "promptListSlugs"}
        active_count = len(room.seated_players())
        if settings["max_players"] < active_count:
            # The count is a value, not a sentence: the client says how many
            # are seated in its own words (R-I18N-02).
            return refuse(
                ErrorCode.MAX_PLAYERS_BELOW_SEATED,
                f"Max players cannot be below the {active_count} players already in the room",
                params={"seated": active_count},
            )
        if not settings["custom_prompts"]:
            settings["custom_prompts_only"] = False
        try:
            ctx.room_quotas.check_retained_prompts(
                settings["custom_prompts"], replacing=room
            )
        except RoomQuotaExceeded as error:
            return {"ok": False, "errorCode": ErrorCode.INVALID_CUSTOM_PROMPTS, "error": str(error), "field": "customPrompts"}
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
                "ok": False, "errorCode": ErrorCode.ROOM_ENDED,
                "error": "This room has ended",
            }
        return {"ok": False, "errorCode": ErrorCode.ROOM_NOT_FOUND, "error": "Room not found"}
    return {
        "ok": True,
        "room": room.to_public_summary(),
        "players": room.to_public_roster(),
    }


async def join_room(ctx: HandlerContext, sid, data):
    """Seat this socket in the named room, releasing any seat it held."""
    seated: list = []
    with entry_deadline():
        async with ctx.seating(sid):
            answer = await _join_room(ctx, sid, data, seated)
        await _after_seating(ctx, seated)
    return answer


async def _join_room(ctx: HandlerContext, sid, data, seated: list):
    try:
        payload = parse_payload(JoinRoomPayload, data)
    except PayloadError as error:
        return error.acknowledgement()

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
                "ok": False, "errorCode": ErrorCode.ROOM_ENDED,
                "error": "This room has ended",
            }
        return {"ok": False, "errorCode": ErrorCode.ROOM_NOT_FOUND, "error": "Room not found"}

    return await _seat_in_room(
        ctx,
        sid,
        room,
        payload,
        seated,
        soft=payload.soft,
        reconnect_only=payload.reconnect_only,
    )


# A room that stopped being open between being ranked and being sat in. Never
# sent: `quick_play` compares it by identity and picks again (#931), and the
# deadline is what ends the picking.
QUICK_PLAY_CLOSED = {
    "ok": False,
    "errorCode": ErrorCode.ROOM_FULL,
    "error": "That room is no longer open",
}

# The refusals that are about one room rather than the player: Quick play
# tries the next room instead of answering them.
QUICK_PLAY_SKIPS = frozenset(
    {ErrorCode.ROOM_FULL, ErrorCode.ROOM_NOT_FOUND, ErrorCode.ROOM_ENDED}
)


def _open_for_quick_play(room) -> bool:
    """Public and waiting, with no game running (R-UX-14).

    Asked when the rooms are ranked and again immediately before the seat is
    added, with no await in between: the host can start the game or make the
    room private while the entry is being made.
    """
    return bool(room.is_public) and room.state == "waiting" and not room.game


async def _seat_in_room(
    ctx: HandlerContext,
    sid,
    room,
    payload,
    seated: list,
    *,
    soft: bool = False,
    reconnect_only: bool = False,
    quick_play: bool = False,
    identity=None,
):
    """Take a seat in a room that has already been resolved.

    Split out from `_join_room` so a second way in can reuse the whole seat
    lifecycle rather than re-derive it. What is in here is everything that has
    to happen once the room is known, in an order that matters: confirming a
    seat this socket already holds, rebinding an account's existing seat,
    the takeover and join rate limits with their refunds, spectator capacity,
    enrolling a mid-game arrival into the rotation, releasing whatever seat the
    socket held elsewhere (R-ROOM-08), and the `ending` checks on both sides of
    seating. Deriving that list again at a second entry point is how one of
    them goes missing.

    `payload` is anything carrying the identity fields a seat is built from -
    nickname, colour, spectator - so a second entry point does not have to
    inherit the room-naming half it has no use for. The two flags that belong
    only to the code path are named here instead of read off it: `soft` is a
    heartbeat that must not resend canvas history, and `reconnect_only` is the
    invite screen asking whether a seat is already held.

    The caller decides *which* room; this decides whether the socket may sit in
    it. Deliberately no visibility check - `_join_room` never had one either,
    because holding the code is the capability (R-ROOM-02), and #529's
    `join_friend_room` resolves the room from a friendship instead.
    """
    name_color = normalize_name_color(payload.name_color)

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
        # The canvas is the client's to ask for (#877); a soft check
        # (heartbeat, visibility) also leaves the drawer's prompt alone.
        await ctx.game_flow._sync_player_view(
            sid,
            room,
            already_joined,
            full=not soft,
        )
        # A client only rechecks its seat in a waiting room when it thinks it
        # is still playing - it missed `game_ended` - so this is when it needs
        # the recap, and it is not paid on an ordinary waiting-room tab.
        await ctx.game_flow.send_last_game(sid, room)
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
                "ok": False, "errorCode": ErrorCode.SEAT_CHANGING_TOO_FAST,
                "error": "This seat is changing hands too quickly. Try again in a minute.",
            }
        # _join_socket_room notifies and disconnects any socket that was
        # holding this seat before handing it to the new one.
        # A seat inside its reconnect grace: how long it stood empty is what
        # the 30 s grace has to cover (#881). Measured now, recorded only once
        # the seat is really taken back below. A second tab taking over a live
        # seat is not a rebind.
        empty_for = (
            time.monotonic() - player.disconnected_at
            if not player.connected and player.disconnected_at is not None
            else None
        )
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
        if empty_for is not None:
            telemetry.note_seat_rebind(empty_for)
        seated.append(player)
        return session_payload(room, player)

    if reconnect_only:
        return {"ok": False, "errorCode": ErrorCode.NO_SESSION_TO_RESUME, "error": "No existing session in this room"}

    if identity is None:
        # Quick play resolves it once and tries rooms with it (#931); an
        # ordinary join resolves it here.
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
            return {"ok": False, "errorCode": error.error_code, "error": str(error), "field": "nickname"}
        except EntryTimedOut:
            return BUSY_ACKNOWLEDGEMENT

    if payload.as_spectator and not ctx.room_capacity.admits_a_spectator(room):
        # Deliberately not `room_full`: that code is what makes the client
        # offer spectating instead, and offering it to somebody refused *as* a
        # spectator is a loop.
        return {
            "ok": False, "errorCode": ErrorCode.SPECTATORS_FULL,
            "error": "This room is not taking any more spectators.",
        }
    if not ctx.room_capacity.admits_a_join(sid):
        return {
            "ok": False, "errorCode": ErrorCode.JOINING_TOO_FAST,
            "error": "You are joining rooms too quickly. Try again in a minute.",
        }

    # Released before the last checks, as creating does, with the old room's
    # durable teardown deferred (#879).
    await ctx.game_flow.release_other_seats(sid)
    if ctx.is_ending(sid):
        return ENDED_ACCOUNT_ACKNOWLEDGEMENT
    # The last word on Quick play, with nothing awaited between it and the
    # seat: the room may have started or gone private since it was resolved.
    if quick_play and not _open_for_quick_play(room):
        ctx.room_capacity.refund_join(sid)
        return QUICK_PLAY_CLOSED
    if entry_expired():
        # As for a room: a seat the client was told it did not get must not
        # exist (#879).
        ctx.room_capacity.refund_join(sid)
        return BUSY_ACKNOWLEDGEMENT
    try:
        player = ctx.room_manager.add_player(
            room,
            identity.nickname,
            is_spectator=payload.as_spectator,
            name_color=identity.name_color or name_color,
            user_id=identity.user_id,
            is_anonymous=identity.is_anonymous,
            colorblind_safe_colors=identity.colorblind_safe_colors,
            avatar_key=identity.avatar_key,
        )
    except RoomFullError:
        # Flagged rather than left for the client to recognise by its prose:
        # the "you can still spectate" offer hangs off this exact case.
        ctx.room_capacity.refund_join(sid)
        return {"ok": False, "errorCode": ErrorCode.ROOM_FULL, "error": "Room is full"}
    except Exception:
        # Any other way seating can fail is equally not a join.
        ctx.room_capacity.refund_join(sid)
        raise

    # A game already in progress keeps running its existing turn_order -
    # joining mid-game enrolls the new player into future turns (appended to
    # the end, so everyone already playing keeps their relative order) rather
    # than blocking the join entirely, and into the turn already being drawn,
    # which they can see and may guess at.
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
    player.avatar_key = account.avatar_key
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
            return {"ok": False, "errorCode": ErrorCode.INVALID_NAME_COLOR, "error": "Invalid player name color"}
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "errorCode": ErrorCode.NOT_IN_ROOM, "error": "Not in this room"}
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
            return {"ok": False, "errorCode": ErrorCode.GUESTS_CANNOT_CHOOSE_COLOR, "error": "Create an account to choose a name color"}
        await ctx.game_flow._emit_colorblind_suggestion(room)
        return {"ok": True}
    if payload.name_color is not None:
        chosen = normalize_name_color(payload.name_color)
        if chosen is None:
            # Well-formed but unreadable on one of the panels (#571). Refused
            # rather than quietly kept as the old colour, so a client that sent
            # it is told, and nothing reaches the room or the account.
            return {"ok": False, "errorCode": ErrorCode.INVALID_NAME_COLOR, "error": "Invalid player name color"}
        player.name_color = chosen
    # Keep the account in step with the seat, so the color this player is
    # using right now is the one their profile shows. A failure here must not
    # cost the room its update: the seat has already changed color, and
    # skipping the broadcast would leave everyone else looking at the old one.
    if payload.name_color is not None and ctx.user_repo is not None and player.user_id:
        try:
            await ctx.user_repo.update_profile(
                player.user_id, name_color=player.name_color
            )
            # The lobby shows this colour too, from a cache warmed at the
            # handshake - and nothing re-handshakes after a colour change.
            ctx.presence_identities.invalidate(player.user_id)
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
        return {"ok": False, "errorCode": ErrorCode.HOST_ONLY, "error": "Only the host can dismiss this suggestion"}
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
        return {"ok": False, "errorCode": ErrorCode.HOST_ONLY, "error": "Only the host can change room colors"}
    room, _ = current
    async with room.lock:
        if room.state != "waiting" or room.game:
            return {
                "ok": False, "errorCode": ErrorCode.WAITING_ROOM_ONLY,
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
            return {"ok": False, "errorCode": ErrorCode.SUGGESTION_INACTIVE, "error": "This suggestion is no longer active"}
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
        return {"ok": False, "errorCode": ErrorCode.NOT_IN_ROOM, "error": "Not in this room"}
    room, player = current

    if not player.is_anonymous:
        return {
            "ok": False, "errorCode": ErrorCode.REGISTERED_NAME_FIXED,
            "error": "Registered players play as their username",
            "field": "nickname",
        }

    nickname = payload.nickname
    if ctx.user_repo is not None:
        owner = await ctx.user_repo.get_by_username(nickname)
        if owner is not None and not owner.is_anonymous:
            return {
                "ok": False, "errorCode": ErrorCode.NAME_TAKEN_BY_ACCOUNT,
                "error": "That name belongs to a registered player.",
                "field": "nickname",
            }
    # One guest name per person online (R-ACCT-09). Keeping the name, or only
    # its case, is a standing claim rather than a new choice.
    if await online_guest_holding(
        nickname,
        claimant_id=player.user_id,
        registry=ctx.presence,
        user_repo=ctx.user_repo,
        choosing=nickname.lower() != player.nickname.lower(),
        identities=ctx.presence_identities,
    ):
        return {
            "ok": False, "errorCode": ErrorCode.NAME_IN_USE,
            "error": NAME_IN_USE_MESSAGE,
            "field": "nickname",
        }

    previous = player.nickname
    if previous == nickname:
        return {"ok": True, "nickname": nickname}

    player.nickname = nickname
    if ctx.user_repo is not None and player.user_id:
        await ctx.user_repo.update_profile(player.user_id, display_name=nickname)
        # The name is stored on the account, so the lobby's cached copy of it
        # is now stale for every other tab this player has open.
        ctx.presence_identities.invalidate(player.user_id)

    await ctx.game_flow.announce(
        room,
        Announcement.NICKNAME_CHANGED,
        {"previous": previous, "nickname": nickname},
    )
    await ctx.game_flow._emit_room_state(room)
    return {"ok": True, "nickname": nickname}


async def become_player(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "errorCode": ErrorCode.NOT_IN_ROOM, "error": "Not in this room"}
    room, player = current
    if room.state != "waiting" or room.game:
        return {"ok": False, "errorCode": ErrorCode.WAITING_ROOM_ONLY, "error": "You can only join as a player from the waiting room"}
    if not player.is_spectator:
        return {"ok": False, "errorCode": ErrorCode.ALREADY_A_PLAYER, "error": "You are already a player"}

    active_count = len(room.seated_players())
    if active_count >= room.max_players:
        return {"ok": False, "errorCode": ErrorCode.PLAYER_SLOTS_FULL, "error": "Player slots are full"}

    player.is_spectator = False
    player.score = 0
    await ctx.game_flow.announce(
        room, Announcement.JOINED_AS_PLAYER, {"nickname": player.nickname}
    )
    await ctx.game_flow._emit_room_state(room)
    return {"ok": True}


async def leave_room(ctx: HandlerContext, sid, data=None):
    try:
        payload = parse_payload(LeaveRoomPayload, data, allow_none=True)
    except PayloadError as error:
        return error.acknowledgement()
    async with ctx.seating(sid):
        current = await ctx.game_flow.require_current_player(sid)
        if not current:
            return
        room, player = current
        if payload is not None and payload.room_id is not None and payload.room_id != room.id:
            return
        await ctx.game_flow.release_seat(sid, room, player)


async def quick_play(ctx: HandlerContext, sid, data):
    """One press from the lobby into a room (#931, R-UX-14).

    The client used to decide this from the lobby's room list and walk the
    candidates, one `join_room` each: a round trip per candidate, a dependency
    on a list that had to have arrived, and - when several visitors pressed in
    the same moment, which is what a shared link produces - a room each,
    because every one of them read the same empty list. The server holds the
    rooms, so it picks: the fullest public room that is waiting in the
    caller's language with a seat free, or a new public room on the defaults
    the create form mirrors.

    Choosing and seating are separated by awaits, so a room can fill or start
    in between; that refusal is not the caller's answer, it is the next room's
    turn. Openers of one language share the first room made: the one that
    opens it registers itself, the rest wait and then find it among the
    candidates, so twenty presses on an empty server fill rooms rather than
    opening twenty.
    """
    seated: list = []
    with entry_deadline():
        async with ctx.seating(sid):
            answer = await _quick_play(ctx, sid, data, seated)
        await _after_seating(ctx, seated)
    return answer


async def _quick_play(ctx: HandlerContext, sid, data, seated: list):
    try:
        payload = parse_payload(QuickPlayPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    if ctx.shutdown is not None and ctx.shutdown.refuses_new_work:
        return ctx.shutdown.rejection_acknowledgement()
    try:
        identity = await _bounded(
            resolve_identity(ctx, sid, payload.nickname, payload.colorblind_safe_colors),
            "resolving who is entering",
        )
    except IdentityError as error:
        return {"ok": False, "errorCode": error.error_code, "error": str(error), "field": "nickname"}
    except EntryTimedOut:
        return BUSY_ACKNOWLEDGEMENT

    entering = _EnteringAs(payload)
    while not entry_expired():
        for room in _quick_play_candidates(ctx, payload.prompt_language):
            answer = await _seat_in_room(
                ctx, sid, room, entering, seated, quick_play=True, identity=identity
            )
            if answer is QUICK_PLAY_CLOSED or answer.get("errorCode") in QUICK_PLAY_SKIPS:
                continue
            return {**answer, "created": False} if answer.get("ok") else answer
        opening = ctx.quick_play_openings.get(payload.prompt_language)
        if opening is not None:
            # Somebody is already opening a room for this language: take a
            # seat in theirs rather than opening a second one beside it.
            try:
                await _bounded(asyncio.shield(opening), "waiting for a room to open")
            except EntryTimedOut:
                return BUSY_ACKNOWLEDGEMENT
            continue
        return await _open_a_quick_play_room(ctx, sid, payload, identity, seated)
    return BUSY_ACKNOWLEDGEMENT


def _quick_play_candidates(ctx: HandlerContext, language: str) -> list:
    """The rooms worth trying, fullest first (R-UX-14).

    Only this language - a room in another would hand the player words they
    can neither draw nor guess - and never a game already under way. Fullest
    first, because the room one seat short of a game is the one worth filling.
    """
    # Seated rather than active: a seat held by somebody disconnected inside
    # their grace, or marked AFK, is still taken - `add_player` counts those,
    # and ranking by anything else offers a room that would refuse the seat.
    open_rooms = [
        room
        for room in ctx.room_manager.rooms.values()
        if _open_for_quick_play(room)
        and room.prompt_language == language
        and len(room.seated_players()) < room.max_players
    ]
    return sorted(open_rooms, key=lambda room: (-len(room.seated_players()), room.id))


async def _open_a_quick_play_room(
    ctx: HandlerContext, sid, payload, identity, seated: list
):
    """Open the room Quick play falls back to, and let others in behind it."""
    if not identity.user_id:
        # The same boundary `create_room` draws: joining is open to a socket
        # with no account, opening a room is not, because the ceilings are
        # keyed on one.
        return ACCOUNT_REQUIRED_TO_OPEN
    language = payload.prompt_language
    opening = asyncio.get_running_loop().create_future()
    ctx.quick_play_openings[language] = opening
    answer: dict | None = None
    try:
        answer = await _create_new_room(
            ctx, sid, _quick_play_room(payload), identity, seated
        )
        return {**answer, "created": True} if answer.get("ok") else answer
    finally:
        del ctx.quick_play_openings[language]
        opening.set_result(answer.get("roomId") if answer and answer.get("ok") else None)


def _quick_play_room(payload) -> CreateRoomPayload:
    """The room Quick play opens: the payload's own defaults, public, in the
    caller's language, and colour-safe when they are (R-UX-14).

    Server-side on purpose (#931): the rule that picks a room and the room it
    opens when none fits are one decision, and a client cannot ask Quick play
    for something else. The name is left empty, so the room is given one.
    """
    return CreateRoomPayload(
        nickname=payload.nickname,
        nameColor=payload.name_color,
        colorblindSafeColors=payload.colorblind_safe_colors,
        isPublic=True,
        promptLanguage=payload.prompt_language,
        colorMode="colorblind_safe" if payload.colorblind_safe_colors else DEFAULT_COLOR_MODE,
    )


def register(ctx: HandlerContext) -> None:
    ctx.on("create_room", handler=partial(create_room, ctx))
    ctx.on("quick_play", handler=partial(quick_play, ctx))
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
