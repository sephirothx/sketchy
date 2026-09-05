"""In-memory GameHistoryRepository that records what a finished game wrote."""
from __future__ import annotations

from dataclasses import dataclass

from app.repositories.interfaces import (
    DrawingReactionResult,
    GameDetail,
    GameHistoryRepository,
    GameParticipantInput,
    GameRecordInput,
    GameSummary,
    ScoreEventInput,
    TurnDrawingDetail,
    TurnDrawingInput,
    TurnDrawingReactionDetail,
    TurnDrawingReactionInput,
    TurnGuessInput,
    TurnRecordInput,
)


@dataclass(frozen=True)
class SavedGame:
    record: GameRecordInput
    participants: list[GameParticipantInput]
    turns: list[TurnRecordInput]
    guesses: list[TurnGuessInput]
    score_events: list[ScoreEventInput]
    drawings: list[TurnDrawingInput]
    reactions: list[TurnDrawingReactionInput]


@dataclass(frozen=True)
class ReactionWrite:
    game_id: str
    turn_id: str
    requesting_user_id: str
    emoji: str | None


class FakeGameHistoryRepository(GameHistoryRepository):
    """Captures `save_game` calls so tests can assert on what was persisted."""

    def __init__(self, *, fail: bool = False) -> None:
        self.saved: list[SavedGame] = []
        self.fail = fail
        # Later reaction writes, and what the next one answers. `None` is the
        # repository's own refusal shape; a test that wants the write to
        # succeed sets `reaction_result`.
        self.reaction_writes: list[ReactionWrite] = []
        self.reaction_result: DrawingReactionResult | None = None
        self.accept_reactions = False
        self.reaction_seat_id = "seat-1"

    async def save_game(
        self,
        game_record: GameRecordInput,
        participants: list[GameParticipantInput],
        turns: list[TurnRecordInput],
        guesses: list[TurnGuessInput],
        score_events: list[ScoreEventInput] | None = None,
        drawings: list[TurnDrawingInput] | None = None,
        reactions: list[TurnDrawingReactionInput] | None = None,
    ) -> str:
        if self.fail:
            raise RuntimeError("database unavailable")
        record_id = game_record.id or f"game-{len(self.saved) + 1}"
        self.saved.append(
            SavedGame(
                record=game_record,
                participants=list(participants),
                turns=list(turns),
                guesses=list(guesses),
                score_events=list(score_events or []),
                drawings=list(drawings or []),
                reactions=list(reactions or []),
            )
        )
        return record_id

    async def set_drawing_reaction(
        self,
        game_id: str,
        turn_id: str,
        *,
        requesting_user_id: str,
        emoji: str | None,
    ) -> DrawingReactionResult | None:
        if self.fail:
            raise RuntimeError("database unavailable")
        self.reaction_writes.append(
            ReactionWrite(game_id, turn_id, requesting_user_id, emoji)
        )
        if self.reaction_result is not None:
            return self.reaction_result
        if not self.accept_reactions:
            return None
        # Echo what was asked, as if this were the only reaction on the turn.
        return DrawingReactionResult(
            turn_id=turn_id,
            seat_id=self.reaction_seat_id,
            emoji=emoji,
            reactions=(
                (TurnDrawingReactionDetail(self.reaction_seat_id, emoji),)
                if emoji
                else ()
            ),
        )

    async def get_turn_drawing(
        self,
        game_id: str,
        turn_id: str,
        *,
        requesting_user_id: str,
    ) -> TurnDrawingDetail | None:
        return None

    async def get_user_games(
        self, user_id: str, limit: int = 20, offset: int = 0
    ) -> list[GameSummary]:
        return []

    async def get_game_detail(
        self, game_id: str, requesting_user_id: str | None = None
    ) -> GameDetail | None:
        return None
