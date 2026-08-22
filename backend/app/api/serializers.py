"""Shared JSON shapes for the REST surface.

camelCase throughout, matching what the frontend already consumes from
``/api/auth/me`` and ``/api/prompt-lists``.
"""
from __future__ import annotations

from datetime import datetime

from app.repositories.interfaces import (
    GameDetail,
    GameSummary,
    PromptListSummary,
    PromptStatsSummary,
    UserData,
    UserStats,
)


def _timestamp(value: datetime | None) -> str | None:
    """Serialize the aware UTC values supplied by the persistence boundary."""
    if value is None:
        return None
    return value.isoformat()


def user_payload(user: UserData) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "nameColor": user.name_color,
        "isAnonymous": user.is_anonymous,
        "createdAt": _timestamp(user.created_at),
        "lastLoginAt": _timestamp(user.last_login_at),
    }


def stats_payload(stats: UserStats) -> dict:
    return {
        "gamesPlayed": stats.games_played,
        "gamesWon": stats.games_won,
        "winRate": stats.win_rate,
        "totalScore": stats.total_score,
        "averageScore": stats.average_score,
        "turnsPlayed": stats.turns_played,
        "promptsGuessed": stats.prompts_guessed,
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
        "startedAt": _timestamp(summary.started_at),
        "finishedAt": _timestamp(summary.finished_at),
        "participants": [
            {
                "seatId": p.seat_id,
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
        "turns": [
            {
                "roundNumber": r.round_number,
                "turnNumber": r.turn_number,
                "drawerUserId": r.drawer_user_id,
                "drawerDisplayName": r.drawer_display_name,
                "prompt": r.prompt,
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
            for r in detail.turns
        ],
    }


def prompt_list_payload(prompt_list: PromptListSummary) -> dict:
    return {
        "slug": prompt_list.slug,
        "name": prompt_list.name,
        "description": prompt_list.description,
        "language": prompt_list.language,
        "promptCount": prompt_list.prompt_count,
        "isBundled": prompt_list.is_bundled,
        "version": prompt_list.version,
    }


def prompt_stats_payload(stats: PromptStatsSummary) -> dict:
    return {
        "text": stats.text,
        "offerCount": stats.offer_count,
        "pickCount": stats.pick_count,
        "correctGuessCount": stats.correct_guess_count,
        "totalGuesserCount": stats.total_guesser_count,
        "pickRate": stats.pick_rate,
        "correctGuessRatio": stats.correct_guess_ratio,
    }
