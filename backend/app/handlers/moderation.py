"""Socket.IO handlers for the moderation domain."""
from __future__ import annotations

from functools import partial
import logging
from uuid import UUID

from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    PayloadError,
    ReportPlayerPayload,
    ToggleAfkPayload,
    VotePayload,
    parse_payload,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import PlayerReport
from app.domain_values import ReportStatus
from app.rooms import majority_of
from app.services.player_reports import (
    evidence_from_live_room,
    record_player_report,
)


logger = logging.getLogger(__name__)


async def toggle_afk(ctx: HandlerContext, sid, data=None):
    try:
        payload = parse_payload(ToggleAfkPayload, data, allow_none=True)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, player = current

    target_afk = not player.is_afk if payload.afk is None else payload.afk

    player.is_afk = target_afk
    await ctx.game_flow._emit_room_state(room)

    await ctx.game_flow.apply_afk_consequences(room, player)

    return {"ok": True, "isAfk": player.is_afk}


async def vote_player(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(VotePayload, data)
    except PayloadError as error:
        return error.acknowledgement()
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
    required_votes = majority_of(len(eligible_voter_ids))

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
            await ctx.game_flow.announce(room, f"{target.nickname} was kicked by vote.")
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
            await ctx.game_flow.announce(room, f"{target.nickname} was marked AFK by vote.")
            await ctx.game_flow.apply_afk_consequences(room, target)
            await ctx.game_flow._emit_room_state(room)
            return {"ok": True, "action": "afk", "executed": True}

    await ctx.game_flow._emit_room_state(room)
    return {"ok": True, "action": action, "executed": False}


async def report_player(ctx: HandlerContext, sid, data):
    """File a report about somebody in this room.

    Addressed by seat. The room never tells anyone another player's account id,
    and filing a complaint is not a reason to start: the seat is resolved here,
    against state the server already holds.

    Evidence is gathered here too, rather than accepted from the reporter. That
    is what makes the checks the REST path performs by hand - is this message
    theirs, did you actually receive it - true by construction.
    """
    try:
        payload = parse_payload(ReportPlayerPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, reporter = current

    # Who they are first, because that is advice they can act on, and it is
    # true whatever the server can do.
    if not reporter.user_id or reporter.is_anonymous:
        return {
            "ok": False,
            "error": "Create an account before reporting, so a moderator can follow up.",
        }
    if ctx.session_factory is None:
        return {"ok": False, "error": "Reporting is unavailable on this server."}

    target = room.players.get(payload.target_player_id)
    if target is None or target.id == reporter.id:
        # The same answer for "no such seat" and "that is you": a report is not
        # a way to find out who is in a room you cannot see.
        return {"ok": False, "error": "No such player in this room."}
    if not target.user_id:
        return {"ok": False, "error": "That player cannot be reported."}

    async with ctx.session_factory() as session:
        async with session.begin():
            # The same rule the REST path and content reports carry: saying it
            # again while a moderator has yet to look adds no evidence and
            # buries the queue.
            already_open = await session.scalar(
                select(PlayerReport.id).where(
                    PlayerReport.reporter_user_id == UUID(reporter.user_id),
                    PlayerReport.reported_user_id == UUID(target.user_id),
                    PlayerReport.status == ReportStatus.PENDING.value,
                )
            )
            if already_open is not None:
                return {
                    "ok": False,
                    "error": (
                        "You have already reported this player. A moderator "
                        "has not looked at it yet."
                    ),
                }
            messages = await evidence_from_live_room(
                session,
                room_instance_id=UUID(room.retention_scope_id),
                reported_user_id=UUID(target.user_id),
                reporter_user_id=UUID(reporter.user_id),
            )
            report = record_player_report(
                session,
                reporter_user_id=UUID(reporter.user_id),
                reported_user_id=UUID(target.user_id),
                # The live room's game has no history row until it is
                # persisted, so the report points at the turn and game only
                # once the evidence itself names them.
                game_id=None,
                turn_id=None,
                reason=payload.reason,
                details=payload.details,
                messages=messages,
                context_snapshot={
                    "source": "room",
                    "room_code": room.code,
                    "reported_display_name": target.nickname,
                },
            )
            try:
                await session.flush()
            except IntegrityError:
                # Two clicks in the same instant both passed the check above;
                # the partial unique index is what really decides.
                return {
                    "ok": False,
                    "error": (
                        "You have already reported this player. A moderator "
                        "has not looked at it yet."
                    ),
                }
            report_id = str(report.id)

    logger.info(
        "player report %s filed in room %s for %s",
        report_id,
        room.id,
        payload.reason,
    )
    return {"ok": True, "id": report_id, "evidenceCount": len(messages)}


def register(ctx: HandlerContext) -> None:
    ctx.on("toggle_afk", handler=partial(toggle_afk, ctx))
    ctx.on("vote_player", handler=partial(vote_player, ctx))
    ctx.on("report_player", handler=partial(report_player, ctx))
