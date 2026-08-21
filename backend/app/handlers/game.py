"""Socket.IO handlers for the game domain."""
from __future__ import annotations

from functools import partial

from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    PayloadError,
    SelectWordPayload,
    parse_empty_payload,
    parse_payload,
)

async def start_game(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[1].is_host:
        return {"ok": False, "error": "Only the host can start the game"}
    room, _ = current
    active_players = room.active_players()
    if len(active_players) < 2:
        return {"ok": False, "error": "Need at least 2 active non-AFK players to start"}
    if room.state == "playing":
        return {"ok": False, "error": "Game already in progress"}

    await ctx.game_flow._start_fresh_game(room, active_players)
    return {"ok": True}


async def select_word(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(SelectWordPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[0].game:
        return {"ok": False, "error": "Game is not ready for word selection"}
    room, player = current
    if not room.game.choose_word(player.id, payload.word):
        return {"ok": False, "error": "That word is no longer available"}
    ctx.timers.cancel_phase_timer(room.id)
    await ctx.game_flow._begin_drawing(room)
    return {"ok": True}


def register(ctx: HandlerContext) -> None:
    ctx.sio.on("start_game", handler=partial(start_game, ctx))
    ctx.sio.on("select_word", handler=partial(select_word, ctx))
