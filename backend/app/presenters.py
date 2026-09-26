"""Pure construction of Socket.IO response and broadcast payloads."""
from __future__ import annotations

from typing import Mapping

from app.announcements import Announcement
from app.auth.avatars import avatar_url
from app.flow_timing import timing
from app.game import Game, MAX_HINT_SPEND, competition_ranks
from app.rooms import Player, Room


def system_chat_message(
    code: Announcement, params: Mapping[str, object] | None = None, **flags: object
) -> dict:
    """A chat line spoken by the room itself.

    Authorless by construction, so no caller can accidentally attribute one to
    a player - and **wordless**, so no caller can accidentally write it in one
    language for a room that does not share one. The code and its parameters
    are the line; the client renders it (R-I18N-03).
    """
    payload: dict = {
        "playerId": "",
        "nickname": "",
        "code": str(code),
        "correct": False,
        "system": True,
    }
    if params:
        payload["params"] = dict(params)
    payload.update(flags)
    return payload


def room_state_payload(room: Room) -> dict:
    return room.to_state_payload()


def editable_room_settings_payload(room: Room) -> dict:
    return {
        "name": room.name,
        "isPublic": room.is_public,
        "maxPlayers": room.max_players,
        "rounds": room.rounds,
        "drawingSeconds": room.drawing_seconds,
        "customPrompts": "\n".join(room.custom_prompts),
        "customPromptsOnly": room.custom_prompts_only,
        "hintMode": room.hint_mode,
        "scoringMode": room.scoring_mode,
        "spectatorsSeePrompt": room.spectators_see_prompt,
        "hideMaskedPrompt": room.hide_masked_prompt,
        "allowedTools": list(room.allowed_tools),
        "colorMode": room.color_mode,
        "promptLanguage": room.prompt_language,
        "promptListSlugs": list(room.prompt_list_slugs),
    }


def session_payload(room: Room, player: Player) -> dict:
    """Acknowledge a join. Carries no credential: the session cookie is the
    identity, and it is never readable from JavaScript."""
    return {
        "ok": True,
        "roomId": room.id,
        "code": room.code,
        "playerId": player.id,
        "isAnonymous": player.is_anonymous,
    }


def turn_payload(
    game: Game,
    player: Player | None = None,
    spectators_see_prompt: bool = False,
    reactions: list[dict] | None = None,
    drawer_transport: str | None = None,
) -> dict:
    player_id = player.id if player else None
    return {
        "phase": game.phase.value,
        # Which transport the drawing seat is on, so this socket plays each
        # batch out over the interval that produced it rather than its own
        # (R-DRAW-01). The transport rather than the milliseconds, because the
        # milliseconds are a `client_config` value that an administrator can
        # move mid-turn and every client is told about at once; sending the
        # resolved number left every viewer pacing at the old one until the
        # next turn. Passed in: this module does no I/O, and which transport a
        # socket is on is a socket fact.
        "drawerTransport": drawer_transport,
        # The turn's durable id, so a reaction can name the drawing it is
        # about; and the reactions so far, so a reconnect sees the tally and
        # its own pick rather than an empty control.
        "turnId": game.current_turn_id,
        "reactions": list(reactions or []),
        "drawerId": game.current_drawer,
        "maskedPrompt": game.masked_prompt(
            player_id,
            is_spectator=player.is_spectator if player else False,
            spectators_see_prompt=spectators_see_prompt,
        ),
        "roundNumber": game.round_number,
        "totalRounds": game.rounds_total,
        "remainingSeconds": round(game.remaining_seconds()),
        "hintCost": game.hint_cost(player_id) if player_id else None,
        "letterPrices": (
            game.wheel_letter_prices(player_id)
            if player_id and game.hint_mode == "wheel"
            else None
        ),
        # What this player has committed to hints so far this turn, and the
        # ceiling on it. Private: only ever sent on a per-socket emit.
        "hintSpend": game.hint_spend.get(player_id, 0) if player_id else 0,
        "maxHintSpend": MAX_HINT_SPEND,
        # Who has already guessed, in the order they did, with the seconds
        # into the drawing each took - what `correct_guess` told the room one
        # event at a time. A socket that resyncs mid-turn missed some of those
        # events, and every tab that comes back into view resyncs (#870).
        "correctGuessers": [
            [token, guess_seconds(game, token)] for token in game.guess_points
        ],
        # This seat's own `you_guessed_correctly`, restored the same way, so
        # its guess input stays closed and the breakdown adds up. Private:
        # sync_game is only ever a per-socket emit.
        "guessed": guessed_receipt(game, player_id),
    }


def guess_time_on_wire(seconds: float) -> float:
    """A guess time as every payload carries it: tenths of a second.

    The client shows tenths, and a payload that sent more let it round a
    second time - 3.249 went out as 3.25 on a highlight and read 3.3s there
    while the chat said 3.2s. Rounded once, here, every surface agrees."""
    return round(seconds, 1)


def guess_seconds(game: Game, token: str) -> float:
    """How far into the drawing `token` guessed, as every surface shows it.

    One number for the chat line, the players panel, a resync and the results
    card, so the same guess never reads 0:04 in one place and 3.6s in another:
    each client used to time `correct_guess` on its own clock, rounded to
    whole seconds. Tenths, because that is what the results card shows and
    anything finer is noise in the event loop's own latency."""
    return guess_time_on_wire(game.guess_times.get(token, 0.0))


def correct_guess_payload(game: Game, player: Player, points: int) -> dict:
    """What the room is told when `player` guesses the prompt: the points it
    earned (net of hints) and the server's `seconds` into the drawing."""
    return {
        "playerId": player.id,
        "nickname": player.nickname,
        "points": points,
        "seconds": guess_seconds(game, player.id),
    }


def guessed_receipt(game: Game, player_id: str | None) -> dict | None:
    """What `you_guessed_correctly` tells a seat, or None if it has not.

    `points` is already net of the hints this player bought, and the deduction
    clamps at zero, so the gross figure can't be recovered client-side; it is
    sent so the round-end breakdown adds up. Hints cannot be bought after a
    correct guess, so the spend here is the one the guess was charged."""
    if player_id is None or player_id not in game.guess_points:
        return None
    points = game.guess_points[player_id]
    hint_spend = game.hint_spend.get(player_id, 0)
    return {
        # In the guesser's own language (#1182): the word they were playing.
        "prompt": game.prompt_for(player_id),
        "points": points,
        "basePoints": points + hint_spend,
        "hintSpend": hint_spend,
    }


def turn_ended_payload(room: Room, drawer_bonus: int | None = None) -> dict:
    game = room.game
    assert game is not None
    players = room.player_list()
    if drawer_bonus is None:
        drawer_bonus = sum(game.guess_points.values())
    deltas = {
        player.id: game.guess_points.get(player.id, 0)
        + (drawer_bonus if player.id == game.current_drawer else 0)
        for player in players
    }
    previous_scores = {
        player.id: player.score - deltas[player.id] for player in players
    }
    previously_ranked = sorted(players, key=lambda item: -previous_scores[item.id])
    previous_ranks = {
        player.id: rank
        for player, rank in zip(
            previously_ranked,
            competition_ranks([previous_scores[p.id] for p in previously_ranked]),
            strict=True,
        )
    }
    ranked = sorted(players, key=lambda player: -player.score)
    new_ranks = {
        player.id: rank
        for player, rank in zip(
            ranked,
            competition_ranks([player.score for player in ranked]),
            strict=True,
        )
    }
    spellings = game.prompt_spellings()
    return {
        "prompt": game.prompt,
        # One payload for the whole room (R-I18N-03), so a mixed-language room
        # (#1182) sends the prompt in every language and each client shows its
        # own seat's; `prompt` stays the drawer's, which is what was drawn and
        # what history keeps. Absent wherever `prompt` is everyone's.
        **({"prompts": spellings} if spellings else {}),
        # end_turn has appended this turn, and current_turn_id is never
        # cleared, so it still names the turn whose results these are.
        "turnId": game.current_turn_id,
        "reactions": room.drawing_reactions_for(game.current_turn_id),
        "drawerId": game.current_drawer,
        "drawerBonus": drawer_bonus,
        "seconds": (
            round(game.remaining_seconds())
            if game.phase_deadline
            else timing.turn_results_seconds
        ),
        "guesses": [
            {
                "playerId": player.id,
                "nickname": player.nickname,
                "nameColor": player.name_color,
                "avatarUrl": avatar_url(player.avatar_key),
                "isAnonymous": player.is_anonymous,
                "seconds": guess_seconds(game, player.id),
            }
            for player in sorted(
                players,
                key=lambda item: game.guess_times.get(item.id, float("inf")),
            )
            if player.id in game.guess_times
        ],
        "scores": [
            {
                "playerId": player.id,
                "nickname": player.nickname,
                "nameColor": player.name_color,
                "avatarUrl": avatar_url(player.avatar_key),
                "isAnonymous": player.is_anonymous,
                "score": player.score,
                "delta": deltas[player.id],
                "previousRank": previous_ranks[player.id],
                "newRank": new_ranks[player.id],
            }
            for player in ranked
        ],
    }
