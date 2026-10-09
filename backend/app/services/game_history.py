"""Turn a finished in-memory game into the rows that record it.

Kept apart from `GameFlowService` because it is pure: no sockets, no database,
no timers - just the mapping from what the room and game remember to the four
input lists `GameHistoryRepository.save_game` expects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain_values import (
    DRAWING_UNAVAILABLE_RECAP_BUDGET,
    GameOutcome,
    GameVisibility,
    RuntimeEventType,
    REACTION_SET_VERSION,
)
from app.services.runtime_metrics import metrics
from app.game import (
    CompletedTurnStats,
    Game,
    TurnParticipantOutcomeRecord,
    competition_ranks,
)
from app.identifiers import generate_uuid7
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    PromptOfferInput,
    ScoreEventInput,
    TurnDrawingInput,
    TurnDrawingReactionInput,
    TurnDrawingShareInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.rooms import RecordedSeat, Room

# A game needs two factual player seats to mean anything: with one, the sole
# participant is ranked first against nobody and books a win. Accountless seats
# count because they played normally even when no cookie supplied a user row.
#
# Note this counts seats that *played*, not seats still present. A player who
# leaves mid-game remains a participant, so an opponent walking out does not
# erase the turns that were genuinely played.
MIN_RECORDED_PARTICIPANTS = 2
SCORE_LEDGER_VERSION = 1


@dataclass(frozen=True)
class GameHistoryWrite:
    """The complete argument set for a single `save_game` call."""

    record: GameRecordInput
    participants: list[GameParticipantInput]
    turns: list[TurnRecordInput]
    score_events: list[ScoreEventInput]
    # Captured here rather than read later because the room reverts to an
    # editable waiting room the moment this function returns, for the same
    # reason the scores and highlights above are captured.
    drawings: list[TurnDrawingInput]
    reactions: list[TurnDrawingReactionInput]
    # What was shared to the Gallery from the turn results (#1430), and the
    # turns whose drawer took theirs back out. Defaults, so a write built by
    # hand without them means "nothing was shared".
    shares: list[TurnDrawingShareInput] = field(default_factory=list)
    withdrawn_turn_ids: list[str] = field(default_factory=list)
    # Every seat token -> the participant seat it was written as, for the
    # room to read the recap's shares back from the rows (#1430).
    recorded_seats: dict[str, RecordedSeat] = field(default_factory=dict)


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
    # Seated and connected at the end: there to see what happened in the room.
    connected: bool = False
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
                connected=player.connected,
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


def _participants(
    seats: dict[str, _Seat], *, ranked: bool
) -> list[GameParticipantInput]:
    """Rank every factual seat, coalescing only duplicate tokens for one account.

    An account that left and rejoined mid-game holds two tokens; the seat it
    still occupies is the one recorded, and it carries the points of both.
    The ledger attributes every award to the one seat written (R-HIST-12), so
    a rejoined seat written at its own score alone - zero, most days - was a
    row the writer refused, and the game with it (#992). Ties share a rank
    (1, 1, 3) so that two players who genuinely drew for the lead both count
    as wins in `UserRepository.get_stats`, which filters on rank 1.
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

    # An account that held two seats played the turns of both, and scored
    # the points of both.
    for identity_key, winner in by_identity.items():
        winner.participant_id = winner.seat_id
        own = [
            seat
            for seat in seats.values()
            if (seat.user_id or f"seat:{seat.seat_id}") == identity_key
        ]
        winner.turns_played = sum(seat.turns_played for seat in own)
        winner.score = sum(seat.score for seat in own)
        for seat in seats.values():
            if (seat.user_id or f"seat:{seat.seat_id}") == identity_key:
                seat.participant_id = winner.seat_id

    ordered = sorted(by_identity.values(), key=lambda seat: -seat.score)
    # A rank is a claim about how a game ended; a game that did not end gets
    # none (R-HIST-06). The row says so, rather than storing a score-order
    # artifact every reader has to know to suppress.
    ranks = (
        competition_ranks([seat.score for seat in ordered])
        if ranked
        else [None] * len(ordered)
    )
    participants: list[GameParticipantInput] = []
    for seat, rank in zip(ordered, ranks, strict=True):
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


def _guesser_count(
    turn: CompletedTurnStats, outcomes: tuple[TurnParticipantOutcomeInput, ...]
) -> int:
    """The eligible guessers of a turn as the written rows count them.

    Falls back to the live count only for a turn that recorded no outcomes
    (a game from before #548), where there is nothing to disagree with.
    """
    if not outcomes:
        return turn.total_guesser_count
    return sum(1 for outcome in outcomes if outcome.eligible)


def _turn_participant_outcomes(
    turn: CompletedTurnStats,
    seats: dict[str, _Seat],
) -> tuple[TurnParticipantOutcomeInput, ...]:
    """Resolve runtime tokens to one factual outcome per historical seat.

    The net award of a correct guess rides on the outcome (#548); a seat
    that guessed right under more than one token in the turn keeps the sum.
    """
    grouped: dict[str, list[TurnParticipantOutcomeRecord]] = {}
    for outcome in turn.participant_outcomes:
        seat = seats.get(outcome.token)
        if seat is not None:
            grouped.setdefault(seat.participant_id, []).append(outcome)
    awarded: dict[str, int] = {}
    for guess in turn.guesses:
        guesser = seats.get(guess.token)
        if guesser is not None:
            awarded[guesser.participant_id] = (
                awarded.get(guesser.participant_id, 0) + guess.points_awarded
            )

    outcome_priority = {
        "ineligible": 0,
        "no_attempt": 1,
        "incorrect": 2,
        "correct": 3,
    }
    terminal_priority = {
        "left": 1,
        "disconnected": 2,
        "afk": 3,
        "active": 4,
    }
    representatives = {
        seat.participant_id: seat
        for seat in seats.values()
        if seat.seat_id == seat.participant_id
    }
    resolved: list[TurnParticipantOutcomeInput] = []
    for seat_id, records in grouped.items():
        seat = representatives[seat_id]
        eligible = any(record.eligible for record in records)
        outcome = max(records, key=lambda row: outcome_priority[row.outcome]).outcome
        terminal_state = max(
            records, key=lambda row: terminal_priority[row.terminal_state]
        ).terminal_state
        correct_times = [
            record.correct_guess_time_seconds
            for record in records
            if record.correct_guess_time_seconds is not None
        ]
        resolved.append(
            TurnParticipantOutcomeInput(
                seat_id=seat_id,
                user_id=seat.user_id,
                eligible=eligible,
                eligibility_reason=(
                    "eligible"
                    if eligible
                    else max(
                        records,
                        key=lambda row: outcome_priority[row.outcome],
                    ).eligibility_reason
                ),
                outcome=outcome,
                terminal_state=terminal_state,
                correct_guess_time_seconds=(
                    min(correct_times) if correct_times else None
                ),
                wrong_guess_count=sum(row.wrong_guess_count for row in records),
                near_miss_count=sum(row.near_miss_count for row in records),
                hints_used=sum(row.hints_used for row in records),
                points_spent_on_hints=sum(
                    row.points_spent_on_hints for row in records
                ),
                points_awarded=(
                    awarded.get(seat_id, 0) if outcome == "correct" else None
                ),
            )
        )
    return tuple(sorted(resolved, key=lambda row: row.seat_id))


def _drawings(room: Room, turn_ids: set[str]) -> list[TurnDrawingInput]:
    """Pair this game's recap entries with the turns actually being recorded.

    A turn whose drawer was never a factual seat is not persisted, so its
    drawing is not either - filtering on the turn ids that survived the loop
    above is what keeps a drawing from outliving its turn.
    """

    drawings: list[TurnDrawingInput] = []
    for entry in room.last_game_drawings:
        if entry.turn_id not in turn_ids:
            continue
        # Whether the recap budget is big enough for real drawings, and how
        # big real drawings actually are, were both guesses until now.
        if entry.is_available:
            metrics.record(
                RuntimeEventType.DRAWING_STORED,
                room_id=room.id,
                value=len(entry.canvas_history or b""),
            )
        else:
            metrics.record(
                RuntimeEventType.RECAP_BUDGET_DROPPED, room_id=room.id
            )
        drawings.append(
            TurnDrawingInput(
                turn_id=entry.turn_id,
                payload=entry.canvas_history,
                unavailable_reason=(
                    None
                    if entry.is_available
                    else DRAWING_UNAVAILABLE_RECAP_BUDGET
                ),
            )
        )
    return drawings


def _reactions(
    room: Room, seats: dict[str, _Seat], turns: list[TurnRecordInput]
) -> list[TurnDrawingReactionInput]:
    """Pair the live reactions with the turns and seats actually being recorded.

    Filtered the same way `_drawings` is, and for the same reason: a reaction on
    a turn that did not survive, or from a token that never became a factual
    seat, has nothing truthful to hang off. Two tokens of one account (a
    reactor who left and rejoined) coalesce onto one participant seat, so the
    later token wins; and a drawer who reacted from a second token to their
    own turn is dropped here rather than refused by the database.
    """
    reactions: dict[tuple[str, str], TurnDrawingReactionInput] = {}
    for turn in turns:
        for token, emoji in room.drawing_reactions.get(turn.id, {}).items():
            seat = seats.get(token)
            if seat is None or seat.user_id is None or seat.is_anonymous:
                continue
            if seat.participant_id == turn.drawer_seat_id:
                continue
            reactions[(turn.id, seat.participant_id)] = TurnDrawingReactionInput(
                turn_id=turn.id,
                seat_id=seat.participant_id,
                user_id=seat.user_id,
                emoji=emoji,
                set_version=REACTION_SET_VERSION,
            )
    return list(reactions.values())


def _shares(
    room: Room,
    seats: dict[str, _Seat],
    turns: list[TurnRecordInput],
    kept: set[str],
) -> tuple[list[TurnDrawingShareInput], list[str]]:
    """Pair the live shares with the turns and seats actually being recorded.

    Filtered as the reactions are, and further: only a drawing that was kept
    can be in the Gallery (`kept`), and a seat with no account has nothing to
    hang a share off. Two tokens of one account coalesce onto one seat, the
    earlier moment kept. The room already refused what the rules refuse
    (R-SHARE-02); the write checks again against what it is writing. A share
    the drawer did not see happen - their seat gone or disconnected by the
    end, the recap's own test (`drawer_is_watching`) - is one they are told
    about afterwards (R-SHARE-09).
    """
    drawer_present = {
        seat.participant_id for seat in seats.values() if seat.present and seat.connected
    }
    shares: dict[tuple[str, str], TurnDrawingShareInput] = {}
    withdrawn: list[str] = []
    for turn in turns:
        if turn.id in room.drawing_share_withdrawn:
            withdrawn.append(turn.id)
        if turn.id not in kept or turn.stroke_count <= 0:
            continue
        for token, when in room.drawing_shares.get(turn.id, {}).items():
            seat = seats.get(token)
            if seat is None or seat.user_id is None:
                continue
            key = (turn.id, seat.participant_id)
            if key in shares and shares[key].shared_at <= when:
                continue
            shares[key] = TurnDrawingShareInput(
                turn_id=turn.id,
                seat_id=seat.participant_id,
                user_id=seat.user_id,
                shared_at=when,
                notify_drawer=(
                    seat.participant_id != turn.drawer_seat_id
                    and turn.drawer_seat_id not in drawer_present
                ),
            )
    return list(shares.values()), withdrawn


def build_game_history(
    room: Room,
    game: Game,
    *,
    finished_at: datetime,
    outcome: str = GameOutcome.FINISHED.value,
) -> GameHistoryWrite | None:
    """Assemble the rows for a game that has stopped, finished or not.

    `finished_at` is when it stopped; `outcome` says whether it reached an end.
    A game nobody stayed for is still made of turns that were drawn and guesses
    that were made, and discarding it is why the games most worth looking at
    were the ones that left no trace.
    """
    seats = _resolve_seats(room, game)
    _count_turns_played(seats, game)
    participants = _participants(
        seats, ranked=outcome == GameOutcome.FINISHED.value
    )
    if len(participants) < MIN_RECORDED_PARTICIPANTS:
        return None

    turns: list[TurnRecordInput] = []
    score_events: list[ScoreEventInput] = []
    score_event_order = 0
    rule_snapshot = game.rule_snapshot()
    for turn in game.completed_turns:
        drawer = seats.get(turn.drawer_token)
        if drawer is None:
            # The runtime token was never a factual player seat (for example,
            # a spectator-only token), so there is no truthful participant
            # identity or presentation snapshot to persist for this turn.
            continue
        turn_id = turn.id or str(generate_uuid7())
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
                    else game.prompt_source_kind(game.key_for(prompt))
                ),
                prompt_version_id=(
                    turn.offered_prompt_version_ids[position]
                    if position < len(turn.offered_prompt_version_ids)
                    else game.prompt_version_ids.get(game.key_for(prompt))
                ),
                source_list_ids=(
                    turn.offered_prompt_source_list_ids[position]
                    if position < len(turn.offered_prompt_source_list_ids)
                    else game.prompt_source_list_ids_by_key.get(game.key_for(prompt), ())
                ),
            )
            for position, prompt in enumerate(turn.offered_prompts)
        )
        participant_outcomes = _turn_participant_outcomes(turn, seats)
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
                    or game.prompt_version_ids.get(game.key_for(turn.chosen_prompt))
                ),
                prompt_source_kind=(
                    turn.offered_prompt_source_kinds[selected_position]
                    if selected_position < len(turn.offered_prompt_source_kinds)
                    else game.prompt_source_kind(game.key_for(turn.chosen_prompt))
                ),
                # Counted over the rows that are written, not the runtime
                # seats the turn counted: an account that left and re-entered
                # mid-turn held two eligible seats and is one participant here,
                # and the repository refuses a turn whose count disagrees with
                # its rows - which lost the whole game's history.
                guesser_count=_guesser_count(turn, participant_outcomes),
                prompt_auto_picked=turn.prompt_auto_picked,
                stroke_count=turn.stroke_count,
                end_reason=turn.end_reason,
                wrong_guess_count=turn.wrong_guess_count,
                near_miss_count=turn.near_miss_count,
                prompt_offers=prompt_offers,
                participant_outcomes=participant_outcomes,
            )
        )
        for guess in turn.guesses:
            guesser = seats.get(guess.token)
            if guesser is None:
                continue
            if game.scoring_mode != "none":
                gross_award = guess.points_awarded + guess.points_spent_on_hints
                if gross_award > 0:
                    score_event_order += 1
                    score_events.append(
                        ScoreEventInput(
                            participant_seat_id=guesser.participant_id,
                            participant_user_id=guesser.user_id,
                            turn_id=turn_id,
                            event_order=score_event_order,
                            event_type="guess_award",
                            points_delta=gross_award,
                        )
                    )
                if guess.points_spent_on_hints > 0:
                    score_event_order += 1
                    score_events.append(
                        ScoreEventInput(
                            participant_seat_id=guesser.participant_id,
                            participant_user_id=guesser.user_id,
                            turn_id=turn_id,
                            event_order=score_event_order,
                            event_type="hint_charge",
                            points_delta=-guess.points_spent_on_hints,
                        )
                    )
        drawer_bonus = sum(guess.points_awarded for guess in turn.guesses)
        if game.scoring_mode != "none" and drawer_bonus > 0:
            score_event_order += 1
            score_events.append(
                ScoreEventInput(
                    participant_seat_id=drawer.participant_id,
                    participant_user_id=drawer.user_id,
                    turn_id=turn_id,
                    event_order=score_event_order,
                    event_type="drawer_bonus",
                    points_delta=drawer_bonus,
                )
            )

    drawings = _drawings(room, {turn.id for turn in turns})
    shares, withdrawn_turn_ids = _shares(
        room,
        seats,
        turns,
        {drawing.turn_id for drawing in drawings if drawing.is_kept},
    )
    return GameHistoryWrite(
        drawings=drawings,
        reactions=_reactions(room, seats, turns),
        shares=shares,
        withdrawn_turn_ids=withdrawn_turn_ids,
        recorded_seats={
            token: RecordedSeat(seat_id=seat.participant_id, user_id=seat.user_id)
            for token, seat in seats.items()
        },
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
            score_ledger_version=SCORE_LEDGER_VERSION,
            rule_snapshot_version=int(rule_snapshot["schemaVersion"]),
            rule_snapshot=rule_snapshot,
            prompt_source_mode=game.prompt_source_mode(),
            prompt_source_list_ids=game.prompt_source_list_ids,
            outcome=outcome,
            visibility=(
                GameVisibility.PUBLIC.value
                if room.is_public
                else GameVisibility.PRIVATE.value
            ),
        ),
        participants=participants,
        turns=turns,
        score_events=score_events,
    )
