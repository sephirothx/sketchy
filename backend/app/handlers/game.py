"""Socket.IO handlers for the game domain."""
from __future__ import annotations

from functools import partial

from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    PayloadError,
    SelectPromptPayload,
    parse_empty_payload,
    parse_payload,
)
from app.services.game_flow import (
    RoomNoLongerStartableError,
    RoomPromptResolutionError,
)

async def start_game(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[1].is_host:
        return {"ok": False, "error": "Only the host can start the game"}
    room, player = current
    if ctx.shutdown is not None and ctx.shutdown.refuses_new_work:
        return ctx.shutdown.rejection_acknowledgement()
    # Waits out a settings change that is still being applied - see Room.lock.
    async with room.lock:
        active_players = room.active_players()
        if len(active_players) < 2:
            return {"ok": False, "error": "Need at least 2 active non-AFK players to start"}
        if room.state == "playing":
            return {"ok": False, "error": "Game already in progress"}

        try:
            await ctx.game_flow.refresh_room_prompt_selection(
                room, requesting_user_id=player.user_id
            )
        except RoomPromptResolutionError as error:
            return {
                "ok": False,
                "error": str(error),
                "field": "promptListSlugs",
            }

        if ctx.shutdown is not None and ctx.shutdown.refuses_new_work:
            return ctx.shutdown.rejection_acknowledgement()

        try:
            await ctx.game_flow._start_fresh_game(room, active_players)
        except RoomNoLongerStartableError as error:
            # The roster emptied out while the prompts were being drawn.
            return {"ok": False, "error": str(error)}
        except RoomPromptResolutionError as error:
            # Drawing this game's prompts is a second read of the same lists
            # the re-authorization above just made, and fails for the same
            # reasons. It is answered the same way rather than escaping the
            # handler, which would leave the host with no acknowledgement.
            return {
                "ok": False,
                "error": str(error),
                "field": "promptListSlugs",
            }
    return {"ok": True}


async def select_prompt(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(SelectPromptPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[0].game:
        return {"ok": False, "error": "Game is not ready for prompt selection"}
    room, player = current
    if not room.game.choose_prompt(player.id, payload.prompt):
        return {"ok": False, "error": "That prompt is no longer available"}
    ctx.timers.cancel_phase_timer(room.id)
    await ctx.game_flow._begin_drawing(room)
    return {"ok": True}


def register(ctx: HandlerContext) -> None:
    ctx.on("start_game", handler=partial(start_game, ctx))
    ctx.on("select_prompt", handler=partial(select_prompt, ctx))
