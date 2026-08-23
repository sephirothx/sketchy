"""In-memory GameHistoryRepository that records what a finished game wrote."""
from __future__ import annotations

from dataclasses import dataclass

from app.repositories.interfaces import (
    GameDetail,
    GameHistoryRepository,
    GameParticipantInput,
    GameRecordInput,
    GameSummary,
    ScoreEventInput,
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


class FakeGameHistoryRepository(GameHistoryRepository):
    """Captures `save_game` calls so tests can assert on what was persisted."""

    def __init__(self, *, fail: bool = False) -> None:
        self.saved: list[SavedGame] = []
        self.fail = fail

    async def save_game(
        self,
        game_record: GameRecordInput,
        participants: list[GameParticipantInput],
        turns: list[TurnRecordInput],
        guesses: list[TurnGuessInput],
        score_events: list[ScoreEventInput] | None = None,
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
            )
        )
        return record_id

    async def get_user_games(
        self, user_id: str, limit: int = 20, offset: int = 0
    ) -> list[GameSummary]:
        return []

    async def get_game_detail(
        self, game_id: str, requesting_user_id: str | None = None
    ) -> GameDetail | None:
        return None
