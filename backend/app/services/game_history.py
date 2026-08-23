"""Turn a finished in-memory game into the rows that record it.

Kept apart from `GameFlowService` because it is pure: no sockets, no database,
no timers - just the mapping from what the room and game remember to the four
input lists `GameHistoryRepository.save_game` expects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.game import Game, competition_ranks
from app.identifiers import generate_uuid7
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    PromptOfferInput,
    TurnGuessInput,
    TurnRecordInput,
)
from app.rooms import Room

# A game needs two factual player seats to mean anything: with one, the sole
# participant is ranked first against nobody and books a win. Accountless seats
# count because they played normally even when no cookie supplied a user row.
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
    """A factual game seat, whether or not it has an account identity."""

    seat_id: str
    user_id: str | None
    display_name: str
    name_color: str | None
    is_anonymous: bool
    score: int
    present: bool
    turns_played: int = 0
    participant_id: str = ""


def _resolve_seats(room: Room, game: Game) -> dict[str, _Seat]:
    """Map every non-spectator roster token to a stable history seat."""
    seats: dict[str, _Seat] = {}
    for token in game.roster:
        player = room.players.get(token)
        if player is not None:
            if player.is_spectator:
                continue
            seats[token] = _Seat(
                seat_id=game.history_seat_ids[token],
                user_id=player.user_id,
                display_name=player.nickname,
                name_color=player.name_color,
                is_anonymous=player.is_anonymous,
                score=player.score,
                present=True,
            )
            continue
        departed = room.departed_seats.get(token)
        if departed is None or departed.is_spectator:
            continue
        seats[token] = _Seat(
            seat_id=game.history_seat_ids[token],
            user_id=departed.user_id,
            display_name=departed.nickname,
            name_color=departed.name_color,
            is_anonymous=departed.is_anonymous,
            score=departed.score,
            present=False,
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
    """Rank every factual seat, coalescing only duplicate tokens for one account.

    An account that left and rejoined mid-game holds two tokens; the seat it
    still occupies wins, since that is the one whose score kept moving. Ties
    share a rank (1, 1, 3) so that two players who genuinely drew for the lead
    both count as wins in `UserRepository.get_stats`, which filters on rank 1.
    """
    by_identity: dict[str, _Seat] = {}
    for seat in seats.values():
        identity_key = seat.user_id or f"seat:{seat.seat_id}"
        existing = by_identity.get(identity_key)
        if (
            existing is None
            or (seat.present and not existing.present)
            or (seat.present == existing.present and seat.score > existing.score)
        ):
            by_identity[identity_key] = seat

    # An account that held two seats played the turns of both.
    for identity_key, winner in by_identity.items():
        winner.participant_id = winner.seat_id
        winner.turns_played = sum(
            seat.turns_played
            for seat in seats.values()
            if (seat.user_id or f"seat:{seat.seat_id}") == identity_key
        )
        for seat in seats.values():
            if (seat.user_id or f"seat:{seat.seat_id}") == identity_key:
                seat.participant_id = winner.seat_id

    ordered = sorted(by_identity.values(), key=lambda seat: -seat.score)
    ranks = competition_ranks([seat.score for seat in ordered])
    participants: list[GameParticipantInput] = []
    for seat, rank in zip(ordered, ranks):
        participants.append(
            GameParticipantInput(
                user_id=seat.user_id,
                final_score=seat.score,
                final_rank=rank,
                turns_played=seat.turns_played,
                seat_id=seat.participant_id,
                display_name=seat.display_name,
                name_color=seat.name_color,
                is_anonymous=seat.is_anonymous,
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
            # The runtime token was never a factual player seat (for example,
            # a spectator-only token), so there is no truthful participant
            # identity or presentation snapshot to persist for this turn.
            continue
        turn_id = str(generate_uuid7())
        selected_position = (
            turn.offered_prompts.index(turn.chosen_prompt)
            if turn.chosen_prompt in turn.offered_prompts
            else 0
        )
        prompt_offers = tuple(
            PromptOfferInput(
                position=position,
                prompt=prompt,
                selected=position == selected_position,
                source_kind=(
                    turn.offered_prompt_source_kinds[position]
                    if position < len(turn.offered_prompt_source_kinds)
                    else game.prompt_source_kind(prompt)
                ),
                prompt_version_id=(
                    turn.offered_prompt_version_ids[position]
                    if position < len(turn.offered_prompt_version_ids)
                    else game.prompt_version_ids.get(prompt)
                ),
                source_revision_ids=(
                    turn.offered_prompt_source_revision_ids[position]
                    if position < len(turn.offered_prompt_source_revision_ids)
                    else game.prompt_source_revision_ids_by_answer.get(prompt, ())
                ),
            )
            for position, prompt in enumerate(turn.offered_prompts)
        )
        turns.append(
            TurnRecordInput(
                id=turn_id,
                round_number=turn.round_number,
                turn_number=turn.turn_number,
                drawer_user_id=drawer.user_id,
                drawer_seat_id=drawer.participant_id,
                prompt=turn.chosen_prompt,
                duration_seconds=turn.duration_seconds,
                prompt_version_id=(
                    turn.chosen_prompt_version_id
                    or game.prompt_version_ids.get(turn.chosen_prompt)
                ),
                prompt_source_kind=(
                    turn.offered_prompt_source_kinds[selected_position]
                    if selected_position < len(turn.offered_prompt_source_kinds)
                    else game.prompt_source_kind(turn.chosen_prompt)
                ),
                guesser_count=turn.total_guesser_count,
                prompt_auto_picked=turn.prompt_auto_picked,
                stroke_count=turn.stroke_count,
                end_reason=turn.end_reason,
                wrong_guess_count=turn.wrong_guess_count,
                near_miss_count=turn.near_miss_count,
                prompt_offers=prompt_offers,
            )
        )
        for guess in turn.guesses:
            guesser = seats.get(guess.token)
            if guesser is None:
                continue
            guesses.append(
                TurnGuessInput(
                    turn_id=turn_id,
                    user_id=guesser.user_id,
                    seat_id=guesser.participant_id,
                    points_awarded=guess.points_awarded,
                    guess_time_seconds=guess.guess_time_seconds,
                    hints_used=guess.hints_used,
                    points_spent_on_hints=guess.points_spent_on_hints,
                    wrong_guesses_before=guess.wrong_guesses_before,
                )
            )

    rule_snapshot = game.rule_snapshot()
    return GameHistoryWrite(
        record=GameRecordInput(
            id=game.id,
            room_name=room.name,
            scoring_mode=game.scoring_mode,
            hint_mode=game.hint_mode,
            drawing_seconds=int(game.drawing_seconds),
            total_rounds=game.rounds_total,
            player_count=len(participants),
            started_at=game.started_at,
            finished_at=finished_at,
            scoring_version=game.scoring_version,
            rule_snapshot_version=int(rule_snapshot["schemaVersion"]),
            rule_snapshot=rule_snapshot,
            prompt_source_mode=game.prompt_source_mode(),
            prompt_source_revision_ids=game.prompt_source_revision_ids,
        ),
        participants=participants,
        turns=turns,
        guesses=guesses,
    )
