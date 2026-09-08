"""Shared JSON shapes for the REST surface.

camelCase throughout, matching what the frontend already consumes from
``/api/auth/me`` and ``/api/prompt-lists``.
"""
from __future__ import annotations

from datetime import datetime

from app.auth.avatars import avatar_url
from app.repositories.interfaces import (
    GameDetail,
    GameSummary,
    OwnedPromptList,
    PromptListSummary,
    SharedPromptList,
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
        "avatarUrl": avatar_url(None if user.is_anonymous else user.avatar_key),
        "isAnonymous": user.is_anonymous,
        # The client needs this to decide whether to offer the operator and
        # moderation entries at all. It is not the authorization - every one of
        # those endpoints checks the role again for itself - it is what stops
        # the app showing a door that will not open.
        "role": user.role,
        # What is waiting on them, if anything: a staff role that has been
        # offered and takes effect when they enrol a second factor. The client
        # shows the prompt and the Settings entry from this, and nothing else
        # is shown to an account with no offer and no role (R-AUTH-20).
        "pendingRole": user.pending_role,
        "createdAt": _timestamp(user.created_at),
        "lastLoginAt": _timestamp(user.last_login_at),
    }


def public_user_payload(user: UserData, *, online: bool) -> dict:
    """The account as anyone may see it: what a seat in a room already shows.

    Deliberately not `user_payload` (#469). That one is the caller's own
    account and carries the role and the username - the first names staff to
    whoever is looking for them, the second is the login identifier the
    nickname lookup is throttled to protect. A profile opened by id gets the
    presentation the player list shows, the day the account was made, and
    whether the player is here: online now, or when they were last - the
    lobby already shows who is online, so a profile saying so is nothing new.
    """
    return {
        "id": user.id,
        "displayName": user.display_name,
        "nameColor": user.name_color,
        "avatarUrl": avatar_url(None if user.is_anonymous else user.avatar_key),
        "isAnonymous": user.is_anonymous,
        "createdAt": _timestamp(user.created_at),
        "isOnline": online,
        "lastSeenAt": _timestamp(user.last_seen_at),
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
        "reactionsReceived": stats.reactions_received,
    }


def game_summary_payload(summary: GameSummary) -> dict:
    return {
        "id": summary.id,
        "roomName": summary.room_name,
        "scoringMode": summary.scoring_mode,
        "scoringVersion": summary.scoring_version,
        "scoreLedgerVersion": summary.score_ledger_version,
        "ruleSnapshotVersion": summary.rule_snapshot_version,
        "promptSourceMode": summary.prompt_source_mode,
        "hintMode": summary.hint_mode,
        "drawingSeconds": summary.drawing_seconds,
        "totalRounds": summary.total_rounds,
        "playerCount": summary.player_count,
        "startedAt": _timestamp(summary.started_at),
        "finishedAt": _timestamp(summary.finished_at),
        "outcome": summary.outcome,
        "visibility": summary.visibility,
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
        "ruleSnapshot": detail.summary.rule_snapshot,
        "mySeatId": detail.my_seat_id,
        "scoreEvents": [
            {
                "participantSeatId": event.participant_seat_id,
                "participantUserId": event.participant_user_id,
                "turnId": event.turn_id,
                "eventOrder": event.event_order,
                "eventType": event.event_type,
                "pointsDelta": event.points_delta,
                "scoringVersion": event.scoring_version,
                "ruleSnapshotVersion": event.rule_snapshot_version,
                "correctsEventOrder": event.corrects_event_order,
            }
            for event in detail.score_events
        ],
        "turns": [
            {
                "id": r.id,
                "roundNumber": r.round_number,
                "turnNumber": r.turn_number,
                "drawerUserId": r.drawer_user_id,
                "drawerSeatId": r.drawer_seat_id,
                "drawerDisplayName": r.drawer_display_name,
                "drawerNameColor": r.drawer_name_color,
                "drawerIsAnonymous": r.drawer_is_anonymous,
                "prompt": r.prompt,
                "promptVersionId": r.prompt_version_id,
                "promptSourceKind": r.prompt_source_kind,
                "durationSeconds": r.duration_seconds,
                "strokeCount": r.stroke_count,
                "drawingStatus": r.drawing_status,
                "promptOffers": [
                    {
                        "position": offer.position,
                        "prompt": offer.prompt,
                        "selected": offer.selected,
                        "sourceKind": offer.source_kind,
                        "promptVersionId": offer.prompt_version_id,
                        "sourceRevisionIds": list(offer.source_revision_ids),
                    }
                    for offer in r.prompt_offers
                ],
                "participantOutcomes": [
                    {
                        "seatId": outcome.seat_id,
                        "eligible": outcome.eligible,
                        "eligibilityReason": outcome.eligibility_reason,
                        "outcome": outcome.outcome,
                        "terminalState": outcome.terminal_state,
                        "correctGuessTimeSeconds": (
                            outcome.correct_guess_time_seconds
                        ),
                        "wrongGuessCount": outcome.wrong_guess_count,
                        "nearMissCount": outcome.near_miss_count,
                        "hintsUsed": outcome.hints_used,
                        "pointsSpentOnHints": outcome.points_spent_on_hints,
                        "pointsAwarded": outcome.points_awarded,
                    }
                    for outcome in r.participant_outcomes
                ],
                "reactions": [
                    {"seatId": reaction.seat_id, "emoji": reaction.emoji}
                    for reaction in r.reactions
                ],
            }
            for r in detail.turns
        ],
    }


def prompt_list_payload(prompt_list: PromptListSummary) -> dict:
    return {
        "id": prompt_list.id,
        "slug": prompt_list.slug,
        "name": prompt_list.name,
        "description": prompt_list.description,
        "language": prompt_list.language,
        "promptCount": prompt_list.prompt_count,
        "isBundled": prompt_list.is_bundled,
        "version": prompt_list.version,
    }


def owned_prompt_list_payload(prompt_list: OwnedPromptList) -> dict:
    return {
        "id": prompt_list.id,
        "slug": prompt_list.slug,
        "name": prompt_list.name,
        "description": prompt_list.description,
        "language": prompt_list.language,
        "isBundled": False,
        "visibility": prompt_list.visibility,
        "shareCode": prompt_list.share_code,
        "moderationState": prompt_list.moderation_state,
        "version": prompt_list.version,
        "promptCount": prompt_list.prompt_count,
        "createdAt": _timestamp(prompt_list.created_at),
        "updatedAt": _timestamp(prompt_list.updated_at),
        "prompts": [
            {
                "conceptId": entry.concept_id,
                "promptVersionId": entry.prompt_version_id,
                "prompt": entry.answer,
                "aliases": list(entry.aliases),
                "moderationState": entry.moderation_state,
            }
            for entry in prompt_list.prompts
        ],
    }


def shared_prompt_list_payload(prompt_list: SharedPromptList) -> dict:
    """Expose report targets without returning the bearer share code or owner."""
    return {
        **prompt_list_payload(prompt_list),
        "prompts": [
            {
                "promptVersionId": entry.prompt_version_id,
                "prompt": entry.answer,
            }
            for entry in prompt_list.prompts
        ],
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
