"""Socket.IO handlers for the chat domain."""
from __future__ import annotations

from functools import partial

from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    GuessPayload,
    HintPayload,
    PayloadError,
    TextPayload,
    WheelLetterPayload,
    parse_payload,
)
from app.prompts import MAX_PROMPT_LENGTH

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
) -> dict:
    """Emit ordinary player-authored chat minus recipients who blocked them.

    Blocking is intentionally a presentation filter. Correct-guess events,
    scores, turns, votes, and room state keep their normal room-wide delivery.
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
    retained_id = None
    if retention_recipients and ctx.message_retention is not None:
        retained_id = await ctx.message_retention.record(
            room=room,
            player=player,
            text=payload["text"],
            message_kind=message_kind,
            audience=audience,
            recipient_sids=retention_recipients,
            near_miss_kind=near_miss_kind,
        )
    if retained_id is not None:
        payload = {**payload, "retainedMessageId": retained_id}
    if recipients is None and not blockers:
        await ctx.sio.emit("chat_message", payload, room=room.id)
    elif visible_to:
        await ctx.sio.emit("chat_message", payload, to=visible_to)
    return payload


async def send_chat(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(TextPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in a room"}
    room, player = current
    if room.state != "waiting":
        return {"ok": False, "error": "Waiting-room chat is unavailable during a game"}
    text = payload.text.strip()
    if not text:
        return {"ok": False, "error": "Message cannot be empty"}
    if player.is_afk and not player.is_spectator:
        player.is_afk = False
        await ctx.game_flow._emit_room_state(room)
    await _emit_player_chat(
        ctx,
        room,
        player,
        _chat_line(player, text, isSpectator=player.is_spectator),
    )
    return {"ok": True}


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
    if not player.accept_guess_id(sid, payload.id):
        # The client's one retry of a guess that did arrive. Acknowledged like
        # any other so it stops retrying, but not replayed: this is the only
        # thing standing between a retry and a second chat line, a second entry
        # in the turn's wrong-guess counts, and a second near-miss hint.
        return

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
    if (
        player.is_spectator
        or player.id in game.correct_guessers
        or not game.is_turn_eligible(player.id)
    ):
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
            hint_text = f'"{text}" is very close!' if hint == "close" else "Some words are correct"
            # The guesser should always see their own guess, even when it's
            # not broadcast to the rest of the room.
            recipients = ctx.game_flow._privileged_sids(room, game, exclude_sid=sid)
            retained_payload = await _emit_player_chat(
                ctx,
                room,
                player,
                _chat_line(player, text),
                recipients=recipients,
                message_kind="wrong_guess",
                audience="prompt_aware",
                near_miss_kind=hint,
                additional_audience_sids=[sid],
            )
            await ctx.sio.emit(
                "chat_message",
                retained_payload,
                to=sid,
            )
            await ctx.sio.emit(
                "chat_message",
                _chat_line(player, hint_text, close=True),
                to=sid,
            )
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
        "correct_guess",
        {"playerId": player.id, "nickname": player.nickname, "points": points},
        room=room.id,
    )
    hint_spend = game.hint_spend.get(player.id, 0)
    await ctx.sio.emit(
        "you_guessed_correctly",
        {
            "prompt": game.prompt,
            "points": points,
            # `points` is already net of the hints this player bought, and the
            # deduction clamps at zero, so the gross figure can't be recovered
            # client-side. Send it so the round-end breakdown adds up.
            "basePoints": points + hint_spend,
            "hintSpend": hint_spend,
        },
        to=player.sid,
    )
    recipients = ctx.game_flow._privileged_sids(room, game)
    if recipients:
        await _emit_player_chat(
            ctx,
            room,
            player,
            _chat_line(player, text, correct=True),
            recipients=recipients,
            message_kind="correct_guess",
            audience="prompt_aware",
        )

    await ctx.game_flow._end_turn_if_all_guessed(room)


async def buy_hint(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(HintPayload, data)
    except PayloadError:
        return {"ok": False, "error": "Invalid hint"}
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[0].game:
        return {"ok": False, "error": "Not in an active game"}
    room, player = current
    game = room.game
    if game.hint_mode != "purchase":
        return {"ok": False, "error": "Hint purchasing is disabled in this room"}
    cost = game.hint_cost(player.id)
    # Hints are bought on credit - nothing is charged here. The game settles
    # the turn's spend against the points a correct guess earns; this check
    # only exists to give the budget case its own message.
    if cost > game.hint_spend_remaining(player.id):
        return {"ok": False, "error": "You've reached this turn's hint spend limit"}
    if not game.buy_hint_letter(player.id, payload.slot):
        return {"ok": False, "error": "Hint unavailable"}

    hint_spend = game.hint_spend.get(player.id, 0)
    await ctx.sio.emit(
        "hint_revealed",
        {
            "maskedPrompt": game.masked_prompt(player.id),
            "hintCost": game.hint_cost(player.id),
            "hintSpend": hint_spend,
        },
        to=sid,
    )
    return {"ok": True, "cost": cost, "hintSpend": hint_spend}


async def buy_wheel_letter(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(WheelLetterPayload, data)
    except PayloadError:
        return {"ok": False, "error": "Invalid letter"}
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[0].game:
        return {"ok": False, "error": "Not in an active game"}
    room, player = current
    game = room.game
    if game.hint_mode != "wheel":
        return {"ok": False, "error": "Letter buying is disabled in this room"}
    letter = payload.letter
    cost = game.wheel_hint_cost(player.id, letter)
    if cost > game.hint_spend_remaining(player.id):
        return {"ok": False, "error": "You've reached this turn's hint spend limit"}
    if not game.buy_wheel_letter(player.id, letter):
        return {"ok": False, "error": "Letter unavailable"}

    hint_spend = game.hint_spend.get(player.id, 0)
    found_count = sum(1 for i in game.letter_positions if game.prompt[i].lower() == letter)
    await ctx.sio.emit(
        "hint_revealed",
        {
            "maskedPrompt": game.masked_prompt(player.id),
            "letterPrices": game.wheel_letter_prices(player.id),
            "hintSpend": hint_spend,
        },
        to=sid,
    )
    price = f"'{letter.upper()}' -{cost} pts"
    if found_count:
        feedback = f"{price} - found {found_count} time{'s' if found_count != 1 else ''}!"
    else:
        feedback = f"{price} - not in the prompt."
    await ctx.game_flow.announce(room, feedback, to=sid)
    return {"ok": True, "cost": cost, "found": found_count, "hintSpend": hint_spend}


def register(ctx: HandlerContext) -> None:
    ctx.on("send_chat", handler=partial(send_chat, ctx))
    ctx.on("guess", handler=partial(guess, ctx))
    ctx.on("buy_hint", handler=partial(buy_hint, ctx))
    ctx.on("buy_wheel_letter", handler=partial(buy_wheel_letter, ctx))
