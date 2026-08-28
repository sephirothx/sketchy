"""Socket.IO handlers for majority-approved active-game restarts."""
from __future__ import annotations

import asyncio
import time
from functools import partial

from app.game import Phase
from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    PayloadError,
    RestartVotePayload,
    parse_empty_payload,
    parse_payload,
)
from app.flow_timing import timing
from app.rooms import RestartVote, Room


def _eligible_players(room: Room):
    """Active players who are in this game's rotation, so may vote to restart it."""
    game = room.game
    if not game:
        return []
    participants = set(game.turn_order)
    return [p for p in room.active_players() if p.id in participants]


async def _reject_vote(
    ctx: HandlerContext,
    room: Room,
    vote: RestartVote,
    message: str,
    *,
    cancel_timer: bool = True,
) -> None:
    if cancel_timer:
        ctx.timers.cancel_restart_timer(room.id)
    if room.restart_vote is not vote:
        return
    room.restart_vote = None
    room.restart_vote_cooldown_until = time.time() + timing.restart_vote_cooldown_seconds
    await ctx.game_flow.announce(room, message)
    await ctx.game_flow._emit_room_state(room)


def _schedule_expiry(ctx: HandlerContext, room: Room, vote: RestartVote) -> None:
    async def _expire() -> None:
        try:
            await asyncio.sleep(timing.restart_vote_seconds)
        except asyncio.CancelledError:
            return
        if room.restart_vote is not vote or vote.status != "voting":
            return
        await _reject_vote(
            ctx,
            room,
            vote,
            "The restart vote expired without passing.",
            cancel_timer=False,
        )

    ctx.timers.replace_restart_timer(room.id, asyncio.create_task(_expire()))


def _schedule_restart(ctx: HandlerContext, room: Room, vote: RestartVote) -> None:
    async def _restart() -> None:
        try:
            await asyncio.sleep(timing.restart_delay_seconds)
        except asyncio.CancelledError:
            return
        if room.restart_vote is not vote or vote.status != "approved":
            return

        if ctx.shutdown is not None and ctx.shutdown.refuses_new_work:
            room.restart_vote = None
            room.restart_vote_cooldown_until = (
                time.time() + timing.restart_vote_cooldown_seconds
            )
            room.state = "waiting"
            room.game = None
            ctx.shutdown.notify_game_state_changed()
            await ctx.game_flow.announce(
                room, "The restart was cancelled because a server update is in progress."
            )
            await ctx.game_flow._emit_room_state(room)
            return

        active_players = room.active_players()
        if len(active_players) < 2:
            room.restart_vote = None
            room.restart_vote_cooldown_until = (
                time.time() + timing.restart_vote_cooldown_seconds
            )
            room.state = "waiting"
            room.game = None
            await ctx.game_flow.announce(
                room, "The restart was cancelled because fewer than two active players remain."
            )
            await ctx.game_flow._emit_room_state(room)
            return

        await ctx.game_flow._start_fresh_game(
            room,
            active_players,
            restarted=True,
        )

    ctx.timers.replace_restart_timer(room.id, asyncio.create_task(_restart()))


async def propose_restart_vote(ctx: HandlerContext, sid, data=None):
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    if ctx.shutdown is not None and ctx.shutdown.refuses_new_work:
        return ctx.shutdown.rejection_acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, proposer = current
    if room.state != "playing" or not room.game:
        return {"ok": False, "error": "There is no active game to restart"}
    if room.game.current_drawer is None:
        return {"ok": False, "error": "The game is still starting"}
    if proposer not in _eligible_players(room):
        return {
            "ok": False,
            "error": "Only active, non-AFK players can propose a restart",
        }
    if room.restart_vote:
        return {"ok": False, "error": "A restart vote is already active"}

    now = time.time()
    if room.restart_vote_cooldown_until > now:
        remaining = max(1, round(room.restart_vote_cooldown_until - now))
        # The remaining seconds are already in the message; nothing reads a
        # separate timestamp.
        return {
            "ok": False,
            "error": f"Another restart vote can be proposed in {remaining}s",
        }

    eligible_players = _eligible_players(room)
    if len(eligible_players) < 2:
        return {"ok": False, "error": "Need at least two active players to vote"}
    vote = RestartVote(
        proposer_id=proposer.id,
        proposer_nickname=proposer.nickname,
        eligible_voter_ids=tuple(player.id for player in eligible_players),
        votes={proposer.id: True},
        expires_at=now + timing.restart_vote_seconds,
    )
    room.restart_vote = vote
    await ctx.game_flow.announce(
        room, f"{proposer.nickname} started a vote to restart the game."
    )
    await ctx.game_flow._emit_room_state(room)
    _schedule_expiry(ctx, room, vote)
    return {"ok": True, "restartVote": vote.payload()}


async def cast_restart_vote(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(RestartVotePayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    if ctx.shutdown is not None and ctx.shutdown.refuses_new_work:
        return ctx.shutdown.rejection_acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, player = current
    vote = room.restart_vote
    if room.state != "playing" or not room.game or not vote:
        return {"ok": False, "error": "There is no active restart vote"}
    if vote.status != "voting":
        return {"ok": False, "error": "The restart vote is already closed"}
    if (
        player.id not in vote.eligible_voter_ids
        or not player.connected
        or player.is_afk
        or player.is_spectator
    ):
        return {"ok": False, "error": "You are not eligible to vote"}

    vote.votes[player.id] = payload.vote
    yes_votes = sum(1 for value in vote.votes.values() if value)
    if yes_votes < vote.required_votes:
        no_votes = sum(1 for value in vote.votes.values() if not value)
        rejection_threshold = len(vote.eligible_voter_ids) - vote.required_votes + 1
        if no_votes >= rejection_threshold:
            await _reject_vote(
                ctx,
                room,
                vote,
                "The restart vote was rejected.",
            )
            return {"ok": True, "approved": False, "rejected": True}
        await ctx.game_flow._emit_room_state(room)
        return {
            "ok": True,
            "approved": False,
            "rejected": False,
            "restartVote": vote.payload(),
        }

    active_players = _eligible_players(room)
    if len(active_players) < 2:
        ctx.timers.cancel_restart_timer(room.id)
        room.restart_vote = None
        room.restart_vote_cooldown_until = (
            time.time() + timing.restart_vote_cooldown_seconds
        )
        await ctx.game_flow.announce(
            room, "The restart vote was cancelled because fewer than two active players remain."
        )
        await ctx.game_flow._emit_room_state(room)
        return {
            "ok": True,
            "approved": False,
            "error": "Need at least two active players to restart",
        }

    ctx.timers.cancel_restart_timer(room.id)
    ctx.timers.cancel_phase_timer(room.id)
    ctx.timers.cancel_hint_timers(room.id)
    room.game.phase = Phase.GAME_END
    vote.status = "approved"
    vote.restart_at = time.time() + timing.restart_delay_seconds
    await ctx.game_flow.announce(
        room, f"The restart vote passed. Restarting in {timing.restart_delay_seconds} seconds."
    )
    await ctx.game_flow._emit_room_state(room)
    _schedule_restart(ctx, room, vote)
    return {"ok": True, "approved": True, "restartVote": vote.payload()}


def register(ctx: HandlerContext) -> None:
    ctx.on(
        "propose_restart_vote",
        handler=partial(propose_restart_vote, ctx),
    )
    ctx.on("cast_restart_vote", handler=partial(cast_restart_vote, ctx))
