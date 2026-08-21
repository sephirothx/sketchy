"""Socket.IO handlers for the chat domain."""
from __future__ import annotations

from functools import partial

from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    HintPayload,
    PayloadError,
    TextPayload,
    WheelLetterPayload,
    parse_payload,
)
from app.words import MAX_WORD_LENGTH

def _chat_line(player, text: str, **extra) -> dict:
    """A chat line attributed to `player`, plus any per-case flags."""
    return {
        "playerId": player.id,
        "nickname": player.nickname,
        "text": text,
        "correct": False,
        **extra,
    }


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
    await ctx.sio.emit(
        "chat_message",
        _chat_line(player, text, isSpectator=player.is_spectator),
        room=room.id,
    )
    return {"ok": True}


async def guess(ctx: HandlerContext, sid, data):
    try:
        payload = parse_payload(TextPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[0].game:
        return
    room, player = current
    text = payload.text.strip()
    if not text:
        return

    if player.is_afk:
        player.is_afk = False
        await ctx.game_flow._emit_room_state(room)

    game = room.game

    # Once a player has already found the word this round, anything else
    # they type could spoil it for players who haven't guessed yet (or
    # just be confusing out-of-context chatter). Keep the rest of their
    # messages for the round visible only to the drawer and other
    # players who've also already guessed correctly, flagged so the
    # client can render a clear "restricted visibility" indicator.
    # Spectators and players who have already guessed correctly can chat,
    # but their messages are restricted to the drawer, other correct guessers, and spectators.
    if player.is_spectator or player.id in game.correct_guessers:
        recipients = ctx.game_flow._privileged_sids(room, game)
        if recipients:
            await ctx.sio.emit(
                "chat_message",
                _chat_line(
                    player, text, restricted=True, isSpectator=player.is_spectator
                ),
                to=recipients,
            )
        return

    if len(text) > MAX_WORD_LENGTH:
        await ctx.sio.emit(
            "chat_message",
            _chat_line(player, text),
            room=room.id,
        )
        return

    correct, points = game.submit_guess(player.id, text)
    if not correct:
        hint = game.guess_hint(player.id, text)
        if hint:
            hint_text = f'"{text}" is very close!' if hint == "close" else "Some words are correct"
            # The guesser should always see their own guess, even when it's
            # not broadcast to the rest of the room.
            await ctx.sio.emit(
                "chat_message",
                _chat_line(player, text),
                to=sid,
            )
            await ctx.sio.emit(
                "chat_message",
                _chat_line(player, hint_text, close=True),
                to=sid,
            )
            recipients = ctx.game_flow._privileged_sids(room, game, exclude_sid=sid)
            if recipients:
                await ctx.sio.emit(
                    "chat_message",
                    _chat_line(player, text),
                    to=recipients,
                )
        else:
            await ctx.sio.emit(
                "chat_message",
                _chat_line(player, text),
                room=room.id,
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
            "word": game.word,
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
        await ctx.sio.emit(
            "chat_message",
            _chat_line(player, text, correct=True),
            to=recipients,
        )

    await ctx.game_flow._end_round_if_all_guessed(room)


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
        return {"ok": False, "error": "You've used up this turn's hint budget"}
    if not game.buy_hint_letter(player.id, payload.slot):
        return {"ok": False, "error": "Hint unavailable"}

    hint_spend = game.hint_spend.get(player.id, 0)
    await ctx.sio.emit(
        "hint_revealed",
        {
            "maskedWord": game.masked_word(player.id),
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
        return {"ok": False, "error": "You've used up this turn's hint budget"}
    if not game.buy_wheel_letter(player.id, letter):
        return {"ok": False, "error": "Letter unavailable"}

    hint_spend = game.hint_spend.get(player.id, 0)
    found_count = sum(1 for i in game.letter_positions if game.word[i].lower() == letter)
    await ctx.sio.emit(
        "hint_revealed",
        {
            "maskedWord": game.masked_word(player.id),
            "letterPrices": game.wheel_letter_prices(player.id),
            "hintSpend": hint_spend,
        },
        to=sid,
    )
    price = f"'{letter.upper()}' -{cost} pts"
    if found_count:
        feedback = f"{price} - found {found_count} time{'s' if found_count != 1 else ''}!"
    else:
        feedback = f"{price} - not in the word."
    await ctx.game_flow.announce(room, feedback, to=sid)
    return {"ok": True, "cost": cost, "found": found_count, "hintSpend": hint_spend}


def register(ctx: HandlerContext) -> None:
    ctx.sio.on("send_chat", handler=partial(send_chat, ctx))
    ctx.sio.on("guess", handler=partial(guess, ctx))
    ctx.sio.on("buy_hint", handler=partial(buy_hint, ctx))
    ctx.sio.on("buy_wheel_letter", handler=partial(buy_wheel_letter, ctx))
