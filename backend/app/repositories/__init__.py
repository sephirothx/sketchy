"""Repository layer for Sketchy data persistence."""
from __future__ import annotations

from app.repositories.interfaces import (
    GameDetail,
    GameHistoryRepository,
    GameParticipantInput,
    GameParticipantSummary,
    GameRecordInput,
    GameSummary,
    RoundDetail,
    RoundGuessDetail,
    RoundGuessInput,
    RoundRecordInput,
    UserData,
    UserRepository,
    UserStats,
    WordListRepository,
    WordListSummary,
    WordStatsSummary,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyWordListRepository,
)

__all__ = [
    "GameDetail",
    "GameHistoryRepository",
    "GameParticipantInput",
    "GameParticipantSummary",
    "GameRecordInput",
    "GameSummary",
    "RoundDetail",
    "RoundGuessDetail",
    "RoundGuessInput",
    "RoundRecordInput",
    "SqlAlchemyGameHistoryRepository",
    "SqlAlchemyUserRepository",
    "SqlAlchemyWordListRepository",
    "UserData",
    "UserRepository",
    "UserStats",
    "WordListRepository",
    "WordListSummary",
    "WordStatsSummary",
]
