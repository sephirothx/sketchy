"""Reactions to drawings: one emoji per registered seat per drawing (#520)."""
from __future__ import annotations

import asyncio
import logging
from functools import partial

from app.handlers.context import HandlerContext
from app.handlers.payloads import PayloadError, ReactToDrawingPayload, parse_payload
from app.services.drawing_reactions import (
    NOT_ACCEPTED,
    NOT_VISIBLE,
    live_reaction_refusal,
    reaction_broadcast,
    reaction_tally,
    recap_entry_for,
    recap_reaction_refusal,
)
from app.services.game_flow import HISTORY_WRITE_TIMEOUT_SECONDS
from app.services.game_highlights import refresh_reaction_highlight

logger = logging.getLogger(__name__)

GUESTS_CANNOT_REACT = "Create an account to react to drawings."
SPECTATORS_CANNOT_REACT = "Spectators can't react to drawings."


async def react_to_drawing(ctx: HandlerContext, sid, data):
    """Set, change or remove this seat's reaction to one drawing.

    Validation, then authorization, then mutation. The drawing is named by
    turn id and the reactor by their seat, so the payload carries no account
    id and the room broadcast carries none back (R-ROOM-07).

    Two kinds of drawing can be on a player's screen. The current turn's,
    while the game is live: that reaction lives on the room until the game's
    history is written. And one from the recap, after the game ended: the row
    already exists, so the reaction goes to the same repository method the
    REST route uses, and only then into the room's memory - the memory copy
    is what late arrivals to the waiting room are shown, and it must not
    promise a reaction the database refused.
    """
    try:
        payload = parse_payload(ReactToDrawingPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, player = current
    if player.is_spectator:
        return {"ok": False, "error": SPECTATORS_CANNOT_REACT}
    # Who they are before what they can do: the advice is the same whatever
    # the drawing turns out to be, and it is advice they can act on.
    if not player.user_id or player.is_anonymous:
        return {"ok": False, "error": GUESTS_CANNOT_REACT}

    game = room.game
    if game is not None:
        refusal = live_reaction_refusal(room, game, player, payload.turn_id)
        if refusal:
            return {"ok": False, "error": refusal}
        room.set_drawing_reaction(payload.turn_id, player.id, payload.emoji)
        await ctx.sio.emit(
            "drawing_reaction",
            reaction_broadcast(room, player, payload.turn_id, payload.emoji),
            room=room.id,
        )
        return _accepted(room, payload.turn_id, payload.emoji)

    entry = recap_entry_for(room, payload.turn_id)
    if entry is None:
        return {"ok": False, "error": NOT_VISIBLE}
    refusal = recap_reaction_refusal(room, player, entry)
    if refusal:
        return {"ok": False, "error": refusal}
    repo = ctx.game_history_repo
    assert repo is not None and room.last_game_id is not None  # recorded implies both
    try:
        result = await asyncio.wait_for(
            repo.set_drawing_reaction(
                room.last_game_id,
                payload.turn_id,
                requesting_user_id=player.user_id,
                emoji=payload.emoji,
            ),
            timeout=HISTORY_WRITE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error("Timed out writing a reaction for room %s", room.id)
        return {"ok": False, "error": NOT_ACCEPTED}
    except Exception:
        logger.exception("Failed to write a reaction for room %s", room.id)
        return {"ok": False, "error": NOT_ACCEPTED}
    if result is None:
        return {"ok": False, "error": NOT_ACCEPTED}
    room.set_drawing_reaction(payload.turn_id, player.id, payload.emoji)
    # The most-reacted highlight is derived from these counts, and the room
    # state is what carries both to the waiting room; broadcast the reaction
    # first so the tally moves before the card does.
    refresh_reaction_highlight(room)
    await ctx.sio.emit(
        "drawing_reaction",
        reaction_broadcast(room, player, payload.turn_id, payload.emoji),
        room=room.id,
    )
    await ctx.game_flow._emit_room_state(room)
    return _accepted(room, payload.turn_id, payload.emoji)


def _accepted(room, turn_id: str, emoji: str | None) -> dict:
    return {
        "ok": True,
        "turnId": turn_id,
        "emoji": emoji,
        "tally": reaction_tally(room.drawing_reactions.get(turn_id, {})),
    }


def register(ctx: HandlerContext) -> None:
    ctx.on("react_to_drawing", handler=partial(react_to_drawing, ctx))
