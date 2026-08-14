"""Socket.IO handlers for the game domain."""
from __future__ import annotations

from functools import partial

from app.game import Game
from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    PayloadError,
    SelectWordPayload,
    parse_empty_payload,
    parse_payload,
)
from app.rooms import STARTING_SCORE

async def start_game(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[1].is_host:
        return {"ok": False, "error": "Only the host can start the game"}
    room, _ = current
    active_players = [p for p in room.connected_players() if not p.is_spectator and not p.is_afk]
    if len(active_players) < 2:
        return {"ok": False, "error": "Need at least 2 active non-AFK players to start"}
    if room.state == "playing":
        return {"ok": False, "error": "Game already in progress"}

    room.last_game_scores = []
    room.last_game_drawings = []
    for p in room.player_list():
        p.score = 0 if p.is_spectator else (STARTING_SCORE if room.scoring_mode == "default" else 0)
    room.state = "playing"
    room.game = Game(
        turn_order=[p.id for p in active_players],
        rounds_total=room.rounds,
        word_pool=room.effective_word_pool(),
        drawing_seconds=room.drawing_seconds,
        hint_mode=room.hint_mode,
        scoring_mode=room.scoring_mode,
        hide_masked_prompt=room.hide_masked_prompt,
    )
    await ctx.game_flow._emit_room_state(room)
    await ctx.sio.emit("game_started", {}, room=room.id)
    await ctx.game_flow._start_turn(room)
    return {"ok": True}


async def select_word(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(SelectWordPayload, data)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
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
