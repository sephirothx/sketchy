"""Socket.IO handlers for the moderation domain."""
from __future__ import annotations

from functools import partial

from app.game import Phase
from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    PayloadError,
    ToggleAfkPayload,
    VotePayload,
    parse_payload,
)

async def toggle_afk(ctx: HandlerContext, sid, data=None):
    try:
        payload = parse_payload(ToggleAfkPayload, data, allow_none=True)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, player = current

    target_afk = not player.is_afk if payload.afk is None else payload.afk

    player.is_afk = target_afk
    await ctx.game_flow._emit_room_state(room)

    if room.game and room.state == "playing":
        if player.is_afk and player.id == room.game.current_drawer:
            if room.game.phase == Phase.CHOOSING_WORD:
                await ctx.game_flow._start_turn(room)
            elif room.game.phase == Phase.DRAWING:
                await ctx.game_flow._end_round(room)
        else:
            await ctx.game_flow._end_round_if_all_guessed(room)

    return {"ok": True, "isAfk": player.is_afk}


async def vote_player(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(VotePayload, data)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, voter = current

    if voter.is_spectator:
        return {"ok": False, "error": "Spectators cannot vote"}

    target_token = payload.target_player_id
    action = payload.action

    target = room.players.get(target_token)
    if not target or target.id == voter.id:
        return {"ok": False, "error": "Cannot vote on yourself or non-existent player"}
    if target.is_spectator:
        return {"ok": False, "error": "Spectators cannot be moderation targets"}

    eligible_voter_ids = {player.id for player in room.moderation_voters()}
    target.kick_votes.intersection_update(eligible_voter_ids)
    target.afk_votes.intersection_update(eligible_voter_ids)
    required_votes = (len(eligible_voter_ids) // 2) + 1

    if action == "kick":
        if voter.id in target.kick_votes:
            target.kick_votes.remove(voter.id)
        else:
            target.kick_votes.add(voter.id)

        if len(target.kick_votes) >= required_votes:
            target_sid = target.sid
            ctx.timers.cancel_disconnect_timer(target.id)
            ctx.room_manager.remove_player(room, target.id)
            if target_sid:
                await ctx.sio.emit("kicked", {"reason": "You were kicked from the room by vote."}, to=target_sid)
                await ctx.sio.leave_room(target_sid, room.id)
            await ctx.sio.emit(
                "chat_message",
                {"playerId": "", "nickname": "", "text": f"{target.nickname} was kicked by vote.", "correct": False, "system": True},
                room=room.id,
            )
            if room.game and room.state == "playing":
                await ctx.game_flow._remove_player_from_game(room, target.id)
            await ctx.game_flow._emit_room_state(room)
            return {"ok": True, "action": "kick", "executed": True}

    elif action == "afk":
        if voter.id in target.afk_votes:
            target.afk_votes.remove(voter.id)
        else:
            target.afk_votes.add(voter.id)

        if len(target.afk_votes) >= required_votes:
            target.is_afk = True
            target.afk_votes.clear()
            if target.sid:
                await ctx.sio.emit("voted_afk", {"message": "You were marked AFK by room vote."}, to=target.sid)
            await ctx.sio.emit(
                "chat_message",
                {"playerId": "", "nickname": "", "text": f"{target.nickname} was marked AFK by vote.", "correct": False, "system": True},
                room=room.id,
            )
            if room.game and room.state == "playing":
                if target.id == room.game.current_drawer:
                    if room.game.phase == Phase.CHOOSING_WORD:
                        await ctx.game_flow._start_turn(room)
                    elif room.game.phase == Phase.DRAWING:
                        await ctx.game_flow._end_round(room)
                else:
                    await ctx.game_flow._end_round_if_all_guessed(room)
            await ctx.game_flow._emit_room_state(room)
            return {"ok": True, "action": "afk", "executed": True}

    await ctx.game_flow._emit_room_state(room)
    return {"ok": True, "action": action, "executed": False}


def register(ctx: HandlerContext) -> None:
    ctx.sio.on("toggle_afk", handler=partial(toggle_afk, ctx))
    ctx.sio.on("vote_player", handler=partial(vote_player, ctx))
