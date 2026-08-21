"""Turn a finished in-memory game into the rows that record it.

Kept apart from `GameFlowService` because it is pure: no sockets, no database,
no timers - just the mapping from what the room and game remember to the four
input lists `GameHistoryRepository.save_game` expects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.game import Game, competition_ranks
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    TurnGuessInput,
    TurnRecordInput,
)
from app.rooms import Room

# A game needs two recordable accounts to mean anything: with one, the sole
# participant is ranked first against nobody and books a win. This is reachable
# even though starting a game needs two active players - the others may have
# been playing without an account, or without a session cookie at all.
#
# Note this counts seats that *played*, not seats still present. A player who
# leaves mid-game remains a participant, so an opponent walking out does not
# erase the turns that were genuinely played.
MIN_RECORDED_PARTICIPANTS = 2


@dataclass(frozen=True)
class GameHistoryWrite:
    """The complete argument set for a single `save_game` call."""

    record: GameRecordInput
    participants: list[GameParticipantInput]
    turns: list[TurnRecordInput]
    guesses: list[TurnGuessInput]


@dataclass
class _Seat:
    """A roster token resolved to the account and score it ends the game with."""

    user_id: str
    score: int
    present: bool
    turns_played: int = 0


def _resolve_seats(room: Room, game: Game) -> dict[str, _Seat]:
    """Map each roster token to its account, skipping seats we cannot record.

    Spectators never take a turn and would only distort ranks and averages.
    Players whose browser blocked the session cookie have no account at all
    (`Player.user_id is None`), and every history table keys on a NOT NULL user
    id, so those seats are dropped rather than written.
    """
    seats: dict[str, _Seat] = {}
    for token in game.roster:
        player = room.players.get(token)
        if player is not None:
            if player.is_spectator or not player.user_id:
                continue
            seats[token] = _Seat(
                user_id=player.user_id, score=player.score, present=True
            )
            continue
        departed = room.departed_seats.get(token)
        if departed is None or departed.is_spectator or not departed.user_id:
            continue
        seats[token] = _Seat(
            user_id=departed.user_id, score=departed.score, present=False
        )
    return seats


def _count_turns_played(seats: dict[str, _Seat], game: Game) -> None:
    """Credit each seat with the turns it was still in the rotation for."""
    for turn in game.completed_turns:
        for token in turn.present_tokens:
            seat = seats.get(token)
            if seat is not None:
                seat.turns_played += 1


def _participants(seats: dict[str, _Seat]) -> list[GameParticipantInput]:
    """Rank the recordable seats, one row per account.

    An account that left and rejoined mid-game holds two tokens; the seat it
    still occupies wins, since that is the one whose score kept moving. Ties
    share a rank (1, 1, 3) so that two players who genuinely drew for the lead
    both count as wins in `UserRepository.get_stats`, which filters on rank 1.
    """
    by_account: dict[str, _Seat] = {}
    for seat in seats.values():
        existing = by_account.get(seat.user_id)
        if (
            existing is None
            or (seat.present and not existing.present)
            or (seat.present == existing.present and seat.score > existing.score)
        ):
            by_account[seat.user_id] = seat

    # An account that held two seats played the turns of both.
    for user_id, winner in by_account.items():
        winner.turns_played = sum(
            seat.turns_played for seat in seats.values() if seat.user_id == user_id
        )

    ordered = sorted(by_account.values(), key=lambda seat: -seat.score)
    ranks = competition_ranks([seat.score for seat in ordered])
    participants: list[GameParticipantInput] = []
    for seat, rank in zip(ordered, ranks):
        participants.append(
            GameParticipantInput(
                user_id=seat.user_id,
                final_score=seat.score,
                final_rank=rank,
                turns_played=seat.turns_played,
            )
        )
    return participants


def build_game_history(
    room: Room,
    game: Game,
    *,
    finished_at: datetime,
) -> GameHistoryWrite | None:
    """Assemble the rows for a completed game, or None if it is not worth recording."""
    seats = _resolve_seats(room, game)
    _count_turns_played(seats, game)
    participants = _participants(seats)
    if len(participants) < MIN_RECORDED_PARTICIPANTS:
        return None

    turns: list[TurnRecordInput] = []
    guesses: list[TurnGuessInput] = []
    for turn in game.completed_turns:
        drawer = seats.get(turn.drawer_token)
        if drawer is None:
            # Nothing to hang the turn off: `TurnRecord.drawer_user_id` is a
            # NOT NULL foreign key. The rest of the game still persists.
            continue
        turn_index = len(turns)
        turns.append(
            TurnRecordInput(
                round_number=turn.round_number,
                turn_number=turn.turn_number,
                drawer_user_id=drawer.user_id,
                prompt=turn.chosen_prompt,
                duration_seconds=turn.duration_seconds,
                guesser_count=turn.total_guesser_count,
                prompt_auto_picked=turn.prompt_auto_picked,
                stroke_count=turn.stroke_count,
                end_reason=turn.end_reason,
                wrong_guess_count=turn.wrong_guess_count,
                near_miss_count=turn.near_miss_count,
            )
        )
        for guess in turn.guesses:
            guesser = seats.get(guess.token)
            if guesser is None:
                continue
            guesses.append(
                TurnGuessInput(
                    turn_index=turn_index,
                    user_id=guesser.user_id,
                    points_awarded=guess.points_awarded,
                    guess_time_seconds=guess.guess_time_seconds,
                    hints_used=guess.hints_used,
                    points_spent_on_hints=guess.points_spent_on_hints,
                    wrong_guesses_before=guess.wrong_guesses_before,
                )
            )

    return GameHistoryWrite(
        record=GameRecordInput(
            room_name=room.name,
            scoring_mode=game.scoring_mode,
            hint_mode=game.hint_mode,
            drawing_seconds=int(game.drawing_seconds),
            total_rounds=game.rounds_total,
            player_count=len(participants),
            started_at=game.started_at,
            finished_at=finished_at,
        ),
        participants=participants,
        turns=turns,
        guesses=guesses,
    )
