"""Sharing a drawing to the Gallery from the room (#1430)."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from functools import partial

from app.handlers.context import HandlerContext
from app.handlers.payloads import PayloadError, ShareDrawingPayload, parse_payload
from app.handlers.refusals import ErrorCode
from app.services.drawing_reactions import recap_entry_for
from app.services.drawing_shares import (
    NOT_ACCEPTED,
    NOT_RECORDED,
    NOT_SHAREABLE,
    NOT_VISIBLE,
    PRIVATE_ROOM,
    STILL_SAVING,
    WITHDRAWN,
    apply_recorded_shares,
    drawer_is_watching,
    is_drawer,
    live_share_refusal,
    recap_share_refusal,
    share_broadcast,
)
from app.services.game_flow import HISTORY_WRITE_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

# The service answers with the sentence it wants the player to read; the code
# the client keys on is decided here, next to the sentences.
SHARE_CODES = {
    NOT_VISIBLE: ErrorCode.SHARE_NOT_VISIBLE,
    NOT_SHAREABLE: ErrorCode.SHARE_NOT_ALLOWED,
    PRIVATE_ROOM: ErrorCode.SHARE_NOT_ALLOWED,
    WITHDRAWN: ErrorCode.SHARE_WITHDRAWN,
    STILL_SAVING: ErrorCode.GAME_STILL_SAVING,
    NOT_RECORDED: ErrorCode.GAME_NOT_RECORDED,
    NOT_ACCEPTED: ErrorCode.SHARE_NOT_ACCEPTED,
}
SPECTATORS_CANNOT_SHARE = "Spectators can't share drawings."


def _refused(sentence: str) -> dict:
    return {"ok": False, "errorCode": SHARE_CODES[sentence], "error": sentence}


async def share_drawing(ctx: HandlerContext, sid, data):
    """Share one drawing to the Gallery, or take the share back.

    Validation, then authorization, then mutation. The drawing is named by
    turn id and the sharer by their seat, so neither the payload nor the
    broadcast carries an account id (R-ROOM-07).

    Two kinds of drawing, as for a reaction. The current turn's, from its
    results while the game is live: the share lives on the room until the
    game's history is written. And one from the recap, after the game ended:
    the row exists, so the share goes to the repository first - the same
    method the REST routes use - and only then into the room's memory, which
    must not promise a share the database refused. What goes into the room
    is what the rows hold after the write, not this press alone.

    Guests may share: a share is not a reaction, and a guest who played the
    game saw the drawing as plainly as anyone. A seat with no account at all
    has nothing a share could be kept against.
    """
    try:
        payload = parse_payload(ShareDrawingPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "errorCode": ErrorCode.NOT_IN_ROOM, "error": "Not in this room"}
    room, player = current
    if player.is_spectator:
        return {
            "ok": False,
            "errorCode": ErrorCode.SPECTATORS_CANNOT_SHARE,
            "error": SPECTATORS_CANNOT_SHARE,
        }
    if not player.user_id:
        return _refused(NOT_SHAREABLE)

    game = room.game
    if game is not None:
        refusal = live_share_refusal(room, game, player, payload.turn_id, payload.shared)
        if refusal:
            return _refused(refusal)
        entry = recap_entry_for(room, payload.turn_id)
        assert entry is not None  # the refusal above checked it
        _apply(room, entry, player, payload.shared)
        await ctx.sio.emit(
            "drawing_shared", share_broadcast(room, payload.turn_id), room=room.id
        )
        return _accepted(room, payload.turn_id)

    entry = recap_entry_for(room, payload.turn_id)
    if entry is None:
        return _refused(NOT_VISIBLE)
    refusal = recap_share_refusal(room, player, entry, payload.shared)
    if refusal:
        return _refused(refusal)
    repo = ctx.game_history_repo
    assert repo is not None and room.last_game_id is not None  # recorded implies both
    try:
        result = await asyncio.wait_for(
            repo.set_drawing_share(
                room.last_game_id,
                payload.turn_id,
                requesting_user_id=player.user_id,
                shared=payload.shared,
                notify_drawer=not drawer_is_watching(room, entry),
            ),
            timeout=HISTORY_WRITE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error("Timed out writing a share for room %s", room.id)
        return _refused(NOT_ACCEPTED)
    except Exception:
        logger.exception("Failed to write a share for room %s", room.id)
        return _refused(NOT_ACCEPTED)
    if result is None:
        return _refused(NOT_ACCEPTED)
    # What the rows hold now, not this one press applied to the room's memory:
    # shares made from history, a pin or the Gallery never passed through it.
    apply_recorded_shares(room, result)
    await ctx.sio.emit(
        "drawing_shared", share_broadcast(room, payload.turn_id), room=room.id
    )
    if ctx.on_gallery_changed is not None:
        ctx.on_gallery_changed()
    if result.notify_user_id and ctx.on_inbox_changed is not None:
        try:
            await ctx.on_inbox_changed(result.notify_user_id)
        except Exception:  # noqa: BLE001 - the share stands; the visit catches up
            logger.exception("Failed to push a share notice for room %s", room.id)
    return _accepted(room, payload.turn_id)


def _apply(room, entry, player, shared: bool) -> None:
    """The room's memory of one accepted share or withdrawal in a live game.
    Taking a share back takes it back from every token of the account: one
    made before leaving and coming back is still this player's."""
    drawer = is_drawer(room, entry, player)
    if shared:
        if drawer:
            room.drawing_share_withdrawn.discard(entry.turn_id)
        room.set_drawing_share(entry.turn_id, player.id, True)
    elif drawer:
        room.withdraw_drawing(entry.turn_id)
    else:
        for token in room.own_tokens(player):
            room.set_drawing_share(entry.turn_id, token, False)


async def refresh_recaps(ctx: HandlerContext, turn_ids: Iterable[str]) -> None:
    """Carry a share write made outside the room - from history, a pin or
    the Gallery - into the room whose recap shows that drawing (#1430).

    The recap's share state is a copy of the rows, and only writes through
    the room kept it current: somebody sharing the same drawing from their
    profile left the recap saying it was not in the Gallery, and the drawer
    offered Share where Take out belonged. Read back per drawing, and only for
    a room still showing that game: one that started another while the read
    was in the air has nothing of it left to correct.
    """
    repo = ctx.game_history_repo
    wanted = set(turn_ids)
    if repo is None or not wanted:
        return
    for room in list(ctx.room_manager.rooms.values()):
        if room.game is not None or room.last_game_history != "recorded":
            continue
        game_id = room.last_game_id
        for turn_id in [e.turn_id for e in room.last_game_drawings if e.turn_id in wanted]:
            try:
                state = await repo.get_drawing_share_state(turn_id)
            except Exception:  # noqa: BLE001 - the write stands; the recap is a view
                logger.exception("Failed to read a share state for room %s", room.id)
                continue
            if state is None or room.game is not None or room.last_game_id != game_id:
                continue
            apply_recorded_shares(room, state)
            await ctx.sio.emit("drawing_shared", share_broadcast(room, turn_id), room=room.id)


def _accepted(room, turn_id: str) -> dict:
    return {"ok": True, "turnId": turn_id, **room.drawing_share_state(turn_id)}


def register(ctx: HandlerContext) -> None:
    ctx.on("share_drawing", handler=partial(share_drawing, ctx))
