"""Pure construction of Socket.IO response and broadcast payloads."""
from __future__ import annotations

from app.game import Game, ROUND_END_SECONDS
from app.rooms import Player, Room


def room_state_payload(room: Room) -> dict:
    return room.to_state_payload()


def editable_room_settings_payload(room: Room) -> dict:
    return {
        "name": room.name,
        "isPublic": room.is_public,
        "maxPlayers": room.max_players,
        "rounds": room.rounds,
        "drawingSeconds": room.drawing_seconds,
        "customWords": "\n".join(room.custom_words),
        "customWordsOnly": room.custom_words_only,
        "hintMode": room.hint_mode,
        "scoringMode": room.scoring_mode,
        "spectatorsSeeSolution": room.spectators_see_solution,
        "hideMaskedPrompt": room.hide_masked_prompt,
        "wordListSlugs": list(room.word_list_slugs),
    }


def session_payload(room: Room, player: Player) -> dict:
    return {
        "ok": True,
        "roomId": room.id,
        "code": room.code,
        "playerId": player.id,
    }


def turn_payload(
    game: Game,
    player: Player | None = None,
    spectators_see_solution: bool = False,
) -> dict:
    player_id = player.id if player else None
    return {
        "phase": game.phase.value,
        "drawerId": game.current_drawer,
        "maskedWord": game.masked_word(
            player_id,
            is_spectator=player.is_spectator if player else False,
            spectators_see_solution=spectators_see_solution,
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
    }


def round_ended_payload(room: Room, drawer_bonus: int | None = None) -> dict:
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
    previous_ranks = {
        player.id: rank
        for rank, player in enumerate(
            sorted(players, key=lambda item: -previous_scores[item.id]), start=1
        )
    }
    ranked = sorted(players, key=lambda player: -player.score)
    new_ranks = {
        player.id: rank for rank, player in enumerate(ranked, start=1)
    }
    return {
        "word": game.word,
        "drawerId": game.current_drawer,
        "drawerBonus": drawer_bonus,
        "seconds": (
            round(game.remaining_seconds())
            if game.phase_deadline
            else ROUND_END_SECONDS
        ),
        "guesses": [
            {
                "playerId": player.id,
                "nickname": player.nickname,
                "nameColor": player.name_color,
                "isAnonymous": player.is_anonymous,
                "seconds": game.guess_times[player.id],
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
                "isAnonymous": player.is_anonymous,
                "score": player.score,
                "delta": deltas[player.id],
                "previousRank": previous_ranks[player.id],
                "newRank": new_ranks[player.id],
            }
            for player in ranked
        ],
    }
