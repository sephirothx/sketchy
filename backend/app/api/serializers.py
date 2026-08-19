"""Shared JSON shapes for the REST surface.

camelCase throughout, matching what the frontend already consumes from
``/api/auth/me`` and ``/api/word-lists``.
"""
from __future__ import annotations

from app.repositories.interfaces import (
    GameDetail,
    GameSummary,
    UserData,
    UserStats,
)


def user_payload(user: UserData) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "nameColor": user.name_color,
        "isAnonymous": user.is_anonymous,
        "createdAt": user.created_at.isoformat() if user.created_at else None,
        "lastLoginAt": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def stats_payload(stats: UserStats) -> dict:
    return {
        "gamesPlayed": stats.games_played,
        "gamesWon": stats.games_won,
        "winRate": stats.win_rate,
        "totalScore": stats.total_score,
        "averageScore": stats.average_score,
        "roundsPlayed": stats.rounds_played,
        "wordsGuessed": stats.words_guessed,
        "drawingsMade": stats.drawings_made,
    }


def game_summary_payload(summary: GameSummary) -> dict:
    return {
        "id": summary.id,
        "roomName": summary.room_name,
        "scoringMode": summary.scoring_mode,
        "hintMode": summary.hint_mode,
        "drawingSeconds": summary.drawing_seconds,
        "totalRounds": summary.total_rounds,
        "playerCount": summary.player_count,
        "startedAt": summary.started_at.isoformat() if summary.started_at else None,
        "finishedAt": summary.finished_at.isoformat() if summary.finished_at else None,
        "participants": [
            {
                "userId": p.user_id,
                "displayName": p.display_name,
                "nameColor": p.name_color,
                "isAnonymous": p.is_anonymous,
                "finalScore": p.final_score,
                "finalRank": p.final_rank,
            }
            for p in summary.participants
        ],
    }


def game_detail_payload(detail: GameDetail) -> dict:
    return {
        **game_summary_payload(detail.summary),
        "rounds": [
            {
                "roundNumber": r.round_number,
                "turnNumber": r.turn_number,
                "drawerUserId": r.drawer_user_id,
                "drawerDisplayName": r.drawer_display_name,
                "word": r.word,
                "durationSeconds": r.duration_seconds,
                "guesses": [
                    {
                        "userId": g.user_id,
                        "displayName": g.display_name,
                        "pointsAwarded": g.points_awarded,
                        "guessTimeSeconds": g.guess_time_seconds,
                    }
                    for g in r.guesses
                ],
            }
            for r in detail.rounds
        ],
    }
