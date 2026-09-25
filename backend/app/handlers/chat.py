"""Socket.IO handlers for the chat domain."""
from __future__ import annotations

import asyncio
from functools import partial

from app.announcements import Announcement
from app.game import Phase
from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    GuessPayload,
    HintPayload,
    PayloadError,
    TextPayload,
    WheelLetterPayload,
    parse_payload,
)
from app.presenters import (
    correct_guess_payload,
    guessed_receipt,
    system_chat_message,
)
from app.prompts import MAX_PROMPT_LENGTH
from app.handlers.refusals import ErrorCode
from app.services.telemetry import telemetry

def _chat_line(player, text: str, **extra) -> dict:
    """A chat line attributed to `player`, plus any per-case flags."""
    return {
        "playerId": player.id,
        "nickname": player.nickname,
        "text": text,
        "correct": False,
        **extra,
    }


async def _emit_player_chat(
    ctx: HandlerContext,
    room,
    player,
    payload: dict,
    *,
    recipients: list[str] | None = None,
    message_kind: str = "chat",
    audience: str = "room",
    near_miss_kind: str | None = None,
    additional_audience_sids: list[str] | None = None,
) -> None:
    """Emit ordinary player-authored chat minus recipients who blocked them.

    Blocking is intentionally a presentation filter. Correct-guess events,
    scores, turns, votes, and room state keep their normal room-wide delivery.

    The line is retained for moderation, but its retained id stays on the
    server: nothing in a room cites a line (`report_player` selects its own
    evidence), and a UUIDv7's random half was 39% of a viewer's wire bytes
    (#869). Only lobby lines carry one, because a lobby report cites the line.
    """
    blockers = (
        await ctx.block_service.blockers_of(player.user_id)
        if ctx.block_service is not None
        else frozenset()
    )
    candidate_sids = (
        recipients
        if recipients is not None
        else [
            candidate.sid
            for candidate in room.players.values()
            if candidate.connected and candidate.sid
        ]
    )
    players_by_sid = {
        candidate.sid: candidate
        for candidate in room.players.values()
        if candidate.connected and candidate.sid
    }
    visible_to = list(dict.fromkeys(candidate_sids))
    if blockers:
        visible_to = [
            candidate_sid
            for candidate_sid in visible_to
            if candidate_sid == player.sid
            or players_by_sid.get(candidate_sid) is None
            or players_by_sid[candidate_sid].user_id not in blockers
        ]
    retention_recipients = list(
        dict.fromkeys([*visible_to, *(additional_audience_sids or [])])
    )
    if retention_recipients and ctx.message_retention is not None:
        await ctx.message_retention.record(
            room=room,
            player=player,
            text=payload["text"],
            message_kind=message_kind,
            audience=audience,
            recipient_sids=retention_recipients,
            near_miss_kind=near_miss_kind,
        )
    if recipients is None and not blockers:
        await ctx.sio.emit("chat_message", payload, room=room.id)
    elif visible_to:
        await ctx.sio.emit("chat_message", payload, to=visible_to)


async def send_chat(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(TextPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "errorCode": ErrorCode.NOT_IN_ROOM, "error": "Not in a room"}
    room, player = current
    text = payload.text.strip()
    if not text:
        return {"ok": False, "errorCode": ErrorCode.EMPTY_MESSAGE, "error": "Message cannot be empty"}
    game = room.game
    if game is not None and game.phase == Phase.DRAWING:
        # While something is being drawn, what a seat may say depends on
        # whether it may still guess (#1008). A seat that may is scored and
        # delivered as a guess whatever event carried the line: letting it
        # broadcast chat instead would put the prompt in front of every
        # guesser with no guess check in the way. Everybody else - the
        # drawer, spectators, correct guessers, seats the turn froze out -
        # talks to the prompt-aware audience only (R-SPEC-04).
        if not _prompt_aware(game, player):
            answer = await _accepted_guess(ctx, sid, room, player, text)
            return {"ok": True, **(answer or {})}
        await _wake(ctx, room, player)
        recipients = ctx.game_flow._privileged_sids(room, game)
        if player.sid not in recipients:
            recipients = [*recipients, player.sid]
        await _emit_player_chat(
            ctx,
            room,
            player,
            _chat_line(
                player, text, restricted=True, isSpectator=player.is_spectator
            ),
            recipients=recipients,
            audience="prompt_aware",
        )
        return {"ok": True}
    # The waiting room, a drawer choosing a prompt, the turn's results, the
    # end of a game: nothing to spoil, so the whole room hears it.
    await _wake(ctx, room, player)
    await _emit_player_chat(
        ctx,
        room,
        player,
        _chat_line(player, text, isSpectator=player.is_spectator),
    )
    return {"ok": True}


def _prompt_aware(game, player) -> bool:
    """Whether this seat already knows, or may not guess, this turn's prompt."""
    return (
        player.is_spectator
        or player.id in game.correct_guessers
        or not game.is_turn_eligible(player.id)
    )


async def _wake(ctx: HandlerContext, room, player) -> None:
    """Saying something is activity; a seat marked AFK is back."""
    if player.is_afk and not player.is_spectator:
        player.is_afk = False
        await ctx.game_flow._emit_room_state(room)


async def guess(ctx: HandlerContext, sid, data):
    """Handle one guess, acknowledging that it arrived.

    The acknowledgement is the whole of the delivery guarantee: `guess` is
    emitted volatile, which drops the packet whenever the transport is briefly
    unwritable, and returning at all tells the client its guess landed. Every
    path below returns, including the ones that deliberately ignore the guess -
    a guess the server chose not to act on is not one worth resending. What the
    client must never be told is that a guess arrived when it did not, so
    nothing here is acknowledged early.
    """
    try:
        payload = parse_payload(GuessPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[0].game:
        return
    room, player = current
    text = payload.text.strip()
    if not text:
        return
    # Scope before anything else (#599): a guess that names another room or
    # another turn is a retry that outlived the moment it was made in - the
    # seat moved on while the packet was in flight. Acknowledged so the client
    # stops, and otherwise as if it never arrived: no dedup entry, no AFK
    # change, no chat line, no score.
    if payload.code is not None and payload.code != room.code:
        telemetry.note_guess_out_of_scope("room")
        return
    if payload.turn_id is not None and payload.turn_id != room.game.current_turn_id:
        telemetry.note_guess_out_of_scope("turn")
        return
    if not player.accept_guess_id(sid, payload.id):
        # The client's one retry of a guess that did arrive. Acknowledged like
        # any other so it stops retrying, but not replayed: this is the only
        # thing standing between a retry and a second chat line, a second entry
        # in the turn's wrong-guess counts, and a second near-miss hint. It is
        # answered with what the first attempt was (#884): the retry exists
        # because that answer did not arrive, and it carried the result.
        pending = ctx.guesses_in_flight.get((sid, payload.id))
        if pending is not None:
            return await asyncio.shield(pending)
        return player.guess_answer(payload.id)

    if payload.id is None:
        return await _accepted_guess(ctx, sid, room, player, text)
    # In flight until answered (#884): the client's retry can arrive while
    # this attempt is still awaiting an emit, and must be given this answer,
    # not an empty one it would take for "nothing to say".
    key = (sid, payload.id)
    pending = asyncio.get_running_loop().create_future()
    ctx.guesses_in_flight[key] = pending
    answer = None
    try:
        answer = await _accepted_guess(ctx, sid, room, player, text)
        return answer
    finally:
        if answer is not None:
            player.remember_guess_answer(payload.id, answer)
        ctx.guesses_in_flight.pop(key, None)
        if not pending.done():
            pending.set_result(answer)


async def _accepted_guess(ctx: HandlerContext, sid, room, player, text: str) -> dict | None:
    """Act on a guess the seat has not made before; say what only it sees."""
    if player.is_afk:
        player.is_afk = False
        await ctx.game_flow._emit_room_state(room)

    game = room.game

    # Once a player has already found the prompt this turn, anything else
    # they type could spoil it for players who haven't guessed yet (or
    # just be confusing out-of-context chatter). Keep the rest of their
    # messages for the round visible only to the drawer and other
    # players who've also already guessed correctly, flagged so the
    # client can render a clear "restricted visibility" indicator.
    # Spectators, seats the turn froze out (AFK or disconnected when drawing
    # began), and players who already guessed can chat, but only the
    # prompt-aware audience may see those messages.
    if _prompt_aware(game, player):
        recipients = ctx.game_flow._privileged_sids(room, game)
        if player.sid not in recipients:
            recipients = [*recipients, player.sid]
        await _emit_player_chat(
            ctx,
            room,
            player,
            _chat_line(
                player, text, restricted=True, isSpectator=player.is_spectator
            ),
            recipients=recipients,
            audience="prompt_aware",
        )
        return

    if len(text) > MAX_PROMPT_LENGTH:
        await _emit_player_chat(
            ctx,
            room,
            player,
            _chat_line(player, text),
        )
        return

    correct, points = game.submit_guess(player.id, text)
    if not correct:
        hint = game.guess_hint(player.id, text)
        if hint:
            # The guesser should always see their own guess, even when it's
            # not broadcast to the rest of the room.
            recipients = ctx.game_flow._privileged_sids(room, game, exclude_sid=sid)
            line = _chat_line(player, text)
            await _emit_player_chat(
                ctx,
                room,
                player,
                line,
                recipients=recipients,
                message_kind="wrong_guess",
                audience="prompt_aware",
                near_miss_kind=hint,
                additional_audience_sids=[sid],
            )
            # The guesser's own line and the verdict ride the acknowledgement
            # (#884): both are theirs alone, and the ack was going to them
            # anyway - one message where there were three. The verdict is the
            # announcement a chat_message used to carry, written the same way.
            answer = {
                "line": line,
                "verdict": system_chat_message(
                    Announcement.GUESS_VERY_CLOSE
                    if hint == "close"
                    else Announcement.GUESS_SOME_WORDS_CORRECT,
                    {"text": text} if hint == "close" else None,
                    close=True,
                ),
            }
            return answer
        else:
            await _emit_player_chat(
                ctx,
                room,
                player,
                _chat_line(player, text),
                message_kind="wrong_guess",
            )
        return

    player.score += points
    await ctx.sio.emit(
        "correct_guess", correct_guess_payload(game, player, points), room=room.id
    )
    # The receipt and the guesser's own line ride the acknowledgement (#884),
    # where `you_guessed_correctly` and a chat_message used to follow it. The
    # line still reaches the prompt-aware room, and is still retained with
    # the guesser in its audience.
    line = _chat_line(player, text, correct=True)
    recipients = ctx.game_flow._privileged_sids(room, game, exclude_sid=sid)
    await _emit_player_chat(
        ctx,
        room,
        player,
        line,
        recipients=recipients,
        message_kind="correct_guess",
        audience="prompt_aware",
        additional_audience_sids=[sid],
    )
    answer = {"correct": guessed_receipt(game, player.id), "line": line}

    await ctx.game_flow._end_turn_if_all_guessed(room)
    return answer


async def buy_hint(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(HintPayload, data)
    except PayloadError:
        return {"ok": False, "errorCode": ErrorCode.INVALID_HINT, "error": "Invalid hint"}
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[0].game:
        return {"ok": False, "errorCode": ErrorCode.NOT_IN_GAME, "error": "Not in an active game"}
    room, player = current
    game = room.game
    if game.hint_mode != "purchase":
        return {"ok": False, "errorCode": ErrorCode.HINTS_DISABLED, "error": "Hint purchasing is disabled in this room"}
    cost = game.hint_cost(player.id)
    # Hints are bought on credit - nothing is charged here. The game settles
    # the turn's spend against the points a correct guess earns; this check
    # only exists to give the budget case its own message.
    if cost > game.hint_spend_remaining(player.id):
        return {"ok": False, "errorCode": ErrorCode.HINT_SPEND_LIMIT, "error": "You've reached this turn's hint spend limit"}
    if not game.buy_hint_letter(player.id, payload.slot):
        return {"ok": False, "errorCode": ErrorCode.HINT_UNAVAILABLE, "error": "Hint unavailable"}

    hint_spend = game.hint_spend.get(player.id, 0)
    # The revealed prompt rides the acknowledgement (#884): `hint_revealed`
    # is left to the timed hints, which answer no command.
    return {
        "ok": True,
        "cost": cost,
        "hintSpend": hint_spend,
        "maskedPrompt": game.masked_prompt(player.id),
        "hintCost": game.hint_cost(player.id),
    }


async def buy_wheel_letter(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(WheelLetterPayload, data)
    except PayloadError:
        return {"ok": False, "errorCode": ErrorCode.INVALID_LETTER, "error": "Invalid letter"}
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[0].game:
        return {"ok": False, "errorCode": ErrorCode.NOT_IN_GAME, "error": "Not in an active game"}
    room, player = current
    game = room.game
    if game.hint_mode != "wheel":
        return {"ok": False, "errorCode": ErrorCode.HINTS_DISABLED, "error": "Letter buying is disabled in this room"}
    letter = payload.letter
    cost = game.wheel_hint_cost(player.id, letter)
    if cost > game.hint_spend_remaining(player.id):
        return {"ok": False, "errorCode": ErrorCode.HINT_SPEND_LIMIT, "error": "You've reached this turn's hint spend limit"}
    if not game.buy_wheel_letter(player.id, letter):
        return {"ok": False, "errorCode": ErrorCode.HINT_UNAVAILABLE, "error": "Letter unavailable"}

    hint_spend = game.hint_spend.get(player.id, 0)
    found_count = sum(1 for i in game.letter_positions if game.prompt[i].lower() == letter)
    # All of it rides the acknowledgement (#884) - the revealed prompt and
    # prices `hint_revealed` carried, and the line: the letter, its price and
    # how often it landed, three values the client says in the reader's
    # language with the plural right (R-I18N-03). One message where three were.
    return {
        "ok": True,
        "cost": cost,
        "found": found_count,
        "hintSpend": hint_spend,
        "maskedPrompt": game.masked_prompt(player.id),
        "letterPrices": game.wheel_letter_prices(player.id),
        "line": system_chat_message(
            Announcement.HINT_LETTER_FOUND if found_count else Announcement.HINT_LETTER_MISSING,
            {"letter": letter.upper(), "cost": cost, **({"count": found_count} if found_count else {})},
        ),
    }


def register(ctx: HandlerContext) -> None:
    ctx.on("send_chat", handler=partial(send_chat, ctx))
    ctx.on("guess", handler=partial(guess, ctx))
    ctx.on("buy_hint", handler=partial(buy_hint, ctx))
    ctx.on("buy_wheel_letter", handler=partial(buy_wheel_letter, ctx))
