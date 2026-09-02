"""Versioned account exports and history-safe account anonymization."""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.db import async_engine, async_session_factory, init_db
from app.db.models import (
    AuditEvent,
    AuthSession,
    AuthToken,
    Friendship,
    DataExport,
    EmailOutboxEntry,
    ExternalIdentity,
    GameParticipant,
    GameRecord,
    IdentityAlias,
    BugReport,
    PlayerReport,
    PlayerReportMessageEvidence,
    RoomPreset,
    PromptConcept,
    PromptContentReport,
    PromptList,
    PromptListRevision,
    PromptListRevisionItem,
    PromptVersion,
    PromptVersionAlias,
    RoomMessage,
    ScoreEvent,
    TurnDrawing,
    TurnGuess,
    TurnParticipantOutcome,
    TurnPromptOffer,
    TurnRecord,
    UploadedAvatarAsset,
    User,
    UserBan,
    UserBlock,
    UserSettings,
    generate_uuid,
)
from app.domain_values import (
    DataExportArtifactEncoding,
    AccountState,
    EmailOutboxState,
    AuditTargetType,
    DataExportStatus,
    TurnDrawingStatus,
    UserRole,
)


# Bumped to 2 when friendships joined the export. Additive counts: the
# document's field surface changed, and a reader that keys off the version
# should be able to tell which shape it has.
EXPORT_SCHEMA_VERSION = 2
EXPORT_TTL = timedelta(days=7)
STALE_PROCESSING_AFTER = timedelta(minutes=15)
DELETED_DISPLAY_NAME = "Deleted player"
# Not an address anyone owns, and not empty, so the not-null column keeps
# saying a message went somewhere without saying where.
DELETED_EMAIL_ADDRESS = "deleted@invalid"
DEFAULT_EXPORT_BATCH_SIZE = 25

logger = logging.getLogger(__name__)


class AccountDataError(RuntimeError):
    """Raised when an export or deletion cannot apply to an account."""


@dataclass(frozen=True)
class AccountDeletionResult:
    user_id: str
    identities_anonymized: int
    sessions_revoked: int
    #: Accounts that lost a friendship or a pending request to this deletion,
    #: so the caller can tell them their lists moved. Never the deleted
    #: identities themselves - their sockets are already being closed.
    friends_notified: tuple[str, ...] = ()


def _entity_id(value: str | UUID) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(value)
    except (ValueError, TypeError, AttributeError) as error:
        raise AccountDataError("invalid account identifier") from error


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _identity_rows(
    session: AsyncSession, user_id: UUID
) -> tuple[User, list[tuple[IdentityAlias, User]]]:
    """Resolve a canonical account and each guest identity merged into it."""
    target_id = await session.scalar(
        select(IdentityAlias.target_user_id).where(
            IdentityAlias.source_user_id == user_id
        )
    )
    canonical = await session.get(User, target_id or user_id)
    if canonical is None:
        raise AccountDataError("account not found")
    aliases = list(
        (
            await session.execute(
                select(IdentityAlias, User)
                .join(User, User.id == IdentityAlias.source_user_id)
                .where(IdentityAlias.target_user_id == canonical.id)
                .order_by(IdentityAlias.created_at, IdentityAlias.source_user_id)
            )
        ).all()
    )
    return canonical, aliases


async def create_data_export(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str | UUID,
    now: datetime | None = None,
) -> DataExport:
    """Persist a pending job before any potentially expensive export queries."""
    requested_at = now or datetime.now(timezone.utc)
    db_user_id = _entity_id(user_id)
    async with session_factory() as session:
        async with session.begin():
            user = await session.get(User, db_user_id)
            if user is None or user.state == AccountState.DELETED.value:
                raise AccountDataError("account not found")
            await session.execute(
                delete(DataExport).where(
                    DataExport.user_id == db_user_id,
                    DataExport.expires_at <= requested_at,
                )
            )
            job = DataExport(
                id=generate_uuid(),
                user_id=db_user_id,
                status=DataExportStatus.PENDING.value,
                schema_version=EXPORT_SCHEMA_VERSION,
                created_at=requested_at,
                expires_at=requested_at + EXPORT_TTL,
            )
            session.add(job)
            session.add(
                AuditEvent(
                    id=generate_uuid(),
                    event_type="account.export_requested",
                    actor_user_id=db_user_id,
                    target_user_id=db_user_id,
                    target_type=AuditTargetType.USER.value,
                    target_id=str(db_user_id),
                    details={
                        "export_id": str(job.id),
                        "schema_version": EXPORT_SCHEMA_VERSION,
                    },
                )
            )
        return job


def encode_export_artifact(document: dict) -> tuple[bytes, str]:
    """Compress a finished export, returning the bytes and their encoding.

    Export documents are long, repetitive JSON and live for seven days; the
    compressed form is what gets stored, and the encoding travels with it so a
    later format needs no migration.
    """
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    return (
        gzip.compress(payload),
        DataExportArtifactEncoding.GZIP_JSON.value,
    )


def decode_export_artifact(job: DataExport) -> bytes:
    """The stored document as the JSON bytes a download should serve."""
    if job.artifact is None:
        raise AccountDataError("export has no stored document")
    if job.artifact_encoding != DataExportArtifactEncoding.GZIP_JSON.value:
        raise AccountDataError(
            f"export document has unreadable encoding {job.artifact_encoding!r}"
        )
    try:
        document = gzip.decompress(job.artifact)
    except (OSError, EOFError, zlib.error) as error:
        # Truncated or corrupt bytes: a stored document the server cannot read
        # is a server fault, and the caller needs it as one rather than as an
        # unhandled crash.
        raise AccountDataError("export document could not be decompressed") from error
    if not document:
        # gzip decompresses empty input to empty output without complaint, and
        # an empty body is not the JSON this claims to be.
        raise AccountDataError("export document decoded to nothing")
    return document


async def _build_export_artifact(
    session: AsyncSession, *, user_id: UUID, generated_at: datetime
) -> dict:
    """Build a requester-only document without credentials or third-party bodies."""
    account, aliases = await _identity_rows(session, user_id)
    identity_users = [account, *(source for _, source in aliases)]
    identity_ids = [user.id for user in identity_users]

    sessions = list(
        (
            await session.scalars(
                select(AuthSession)
                .where(AuthSession.user_id.in_(identity_ids))
                .order_by(AuthSession.created_at, AuthSession.id)
            )
        ).all()
    )
    participations = list(
        (
            await session.execute(
                select(GameParticipant, GameRecord)
                .join(GameRecord, GameRecord.id == GameParticipant.game_id)
                .where(GameParticipant.user_id.in_(identity_ids))
                .order_by(GameRecord.finished_at, GameParticipant.id)
            )
        ).all()
    )
    drawings = list(
        (
            await session.scalars(
                select(TurnRecord)
                .where(TurnRecord.drawer_user_id.in_(identity_ids))
                .options(
                    selectinload(TurnRecord.prompt_offers).selectinload(
                        TurnPromptOffer.sources
                    )
                )
                .order_by(TurnRecord.game_id, TurnRecord.round_number, TurnRecord.turn_number)
            )
        ).all()
    )
    guesses = list(
        (
            await session.execute(
                # The attempt/hint numbers live on the outcome row alone now;
                # the export keeps its fields by reading them through the join.
                select(TurnGuess, TurnRecord, TurnParticipantOutcome)
                .join(TurnRecord, TurnRecord.id == TurnGuess.turn_id)
                .join(
                    TurnParticipantOutcome,
                    TurnParticipantOutcome.id == TurnGuess.outcome_id,
                )
                .where(TurnGuess.user_id.in_(identity_ids))
                .order_by(TurnRecord.game_id, TurnRecord.round_number, TurnRecord.turn_number)
            )
        ).all()
    )
    turn_outcomes = list(
        (
            await session.execute(
                select(TurnParticipantOutcome, TurnRecord)
                .join(TurnRecord, TurnRecord.id == TurnParticipantOutcome.turn_id)
                .join(
                    GameParticipant,
                    GameParticipant.id == TurnParticipantOutcome.participant_id,
                )
                .where(GameParticipant.user_id.in_(identity_ids))
                .order_by(
                    TurnRecord.game_id,
                    TurnRecord.round_number,
                    TurnRecord.turn_number,
                )
            )
        ).all()
    )
    score_events = list(
        (
            await session.execute(
                select(ScoreEvent, GameParticipant)
                .join(
                    GameParticipant,
                    GameParticipant.id == ScoreEvent.participant_id,
                )
                .where(GameParticipant.user_id.in_(identity_ids))
                .order_by(ScoreEvent.game_id, ScoreEvent.event_order)
            )
        ).all()
    )
    audit_events = list(
        (
            await session.scalars(
                select(AuditEvent)
                .where(
                    or_(
                        AuditEvent.actor_user_id.in_(identity_ids),
                        AuditEvent.target_user_id.in_(identity_ids),
                    )
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        ).all()
    )
    submitted_reports = list(
        (
            await session.scalars(
                select(PlayerReport)
                .where(PlayerReport.reporter_user_id.in_(identity_ids))
                .options(selectinload(PlayerReport.message_evidence))
                .order_by(PlayerReport.created_at, PlayerReport.id)
            )
        ).all()
    )
    retained_messages = list(
        (
            await session.scalars(
                select(RoomMessage)
                .where(
                    RoomMessage.sender_user_id.in_(identity_ids),
                    RoomMessage.expires_at > generated_at,
                )
                .order_by(RoomMessage.created_at, RoomMessage.id)
            )
        ).all()
    )
    submitted_prompt_content_reports = list(
        (
            await session.scalars(
                select(PromptContentReport)
                .where(PromptContentReport.reporter_user_id.in_(identity_ids))
                .order_by(PromptContentReport.created_at, PromptContentReport.id)
            )
        ).all()
    )
    submitted_bug_reports = list(
        (
            await session.scalars(
                select(BugReport)
                .where(BugReport.reporter_user_id.in_(identity_ids))
                .order_by(BugReport.created_at, BugReport.id)
            )
        ).all()
    )
    suspensions = list(
        (
            await session.scalars(
                select(UserBan)
                .where(UserBan.user_id.in_(identity_ids))
                .order_by(UserBan.created_at, UserBan.id)
            )
        ).all()
    )
    blocks = list(
        (
            await session.scalars(
                select(UserBlock)
                .where(UserBlock.blocker_user_id.in_(identity_ids))
                .order_by(UserBlock.created_at, UserBlock.blocked_user_id)
            )
        ).all()
    )
    friendships = list(
        (
            await session.scalars(
                select(Friendship)
                .where(
                    or_(
                        Friendship.user_low_id.in_(identity_ids),
                        Friendship.user_high_id.in_(identity_ids),
                    )
                )
                .order_by(Friendship.created_at, Friendship.user_low_id)
            )
        ).all()
    )
    export_jobs = list(
        (
            await session.scalars(
                select(DataExport)
                .where(DataExport.user_id == account.id)
                .order_by(DataExport.created_at, DataExport.id)
            )
        ).all()
    )
    settings = await session.get(UserSettings, account.id)
    prompt_lists = list(
        (
            await session.scalars(
                select(PromptList)
                .where(PromptList.owner_user_id.in_(identity_ids))
                .options(
                    selectinload(PromptList.revisions)
                    .selectinload(PromptListRevision.items)
                    .selectinload(PromptListRevisionItem.prompt_version)
                    .selectinload(PromptVersion.version_aliases)
                    .selectinload(PromptVersionAlias.alias)
                )
                .order_by(PromptList.created_at, PromptList.id)
            )
        ).all()
    )
    room_presets = list(
        (
            await session.scalars(
                select(RoomPreset)
                .where(RoomPreset.owner_user_id.in_(identity_ids))
                .order_by(RoomPreset.created_at, RoomPreset.id)
            )
        ).all()
    )

    return {
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "generatedAt": _timestamp(generated_at),
        "account": {
            "id": str(account.id),
            "username": account.username,
            "email": account.email,
            "emailVerifiedAt": _timestamp(account.email_verified_at),
            "displayName": account.display_name,
            "nameColor": account.name_color,
            "avatarKey": account.avatar_key,
            "state": account.state,
            "role": account.role,
            "createdAt": _timestamp(account.created_at),
            "updatedAt": _timestamp(account.updated_at),
            "lastLoginAt": _timestamp(account.last_login_at),
            "lastActiveAt": _timestamp(account.last_active_at),
        },
        "settings": (
            {
                "theme": settings.theme,
                "soundEffects": settings.sound_effects,
                "confettiEffects": settings.confetti_effects,
                "volume": settings.sound_effects_volume,
                "brushCursor": settings.brush_cursor,
                "keyBindings": settings.key_bindings,
                "colorblindSafeColors": settings.colorblind_safe_colors,
                "autoClearChatOnGuess": settings.auto_clear_chat_on_guess,
                "customBrushPresets": settings.custom_brush_presets,
                "createdAt": _timestamp(settings.created_at),
                "updatedAt": _timestamp(settings.updated_at),
            }
            if settings is not None
            else None
        ),
        "promptLists": [
            {
                "id": str(prompt_list.id),
                "slug": prompt_list.slug,
                "name": prompt_list.name,
                "description": prompt_list.description,
                "language": prompt_list.language,
                "visibility": prompt_list.visibility,
                "shareCode": prompt_list.share_code,
                "moderationState": prompt_list.moderation_state,
                "version": prompt_list.version,
                "createdAt": _timestamp(prompt_list.created_at),
                "updatedAt": _timestamp(prompt_list.updated_at),
                "revisions": [
                    {
                        "id": str(revision.id),
                        "version": revision.version,
                        "language": revision.language,
                        "contentHash": revision.content_hash,
                        "createdAt": _timestamp(revision.created_at),
                        "prompts": [
                            {
                                "conceptId": str(item.prompt_version.concept_id),
                                "promptVersionId": str(item.prompt_version.id),
                                "promptVersion": item.prompt_version.version,
                                "prompt": item.prompt_version.canonical_answer,
                                "aliases": sorted(
                                    link.alias.answer
                                    for link in item.prompt_version.version_aliases
                                ),
                                "position": item.position,
                            }
                            for item in revision.items
                        ],
                    }
                    for revision in sorted(
                        prompt_list.revisions, key=lambda item: item.version
                    )
                ],
            }
            for prompt_list in prompt_lists
        ],
        "roomPresets": [
            {
                "id": str(preset.id),
                "name": preset.name,
                "roomName": preset.room_name,
                "isPublic": preset.is_public,
                "maxPlayers": preset.max_players,
                "rounds": preset.rounds,
                "drawingSeconds": preset.drawing_seconds,
                "hintMode": preset.hint_mode,
                "scoringMode": preset.scoring_mode,
                "spectatorsSeePrompt": preset.spectators_see_prompt,
                "hideMaskedPrompt": preset.hide_masked_prompt,
                "allowedTools": preset.allowed_tools,
                "colorMode": preset.color_mode,
                "promptListIds": preset.prompt_list_ids,
                "version": preset.version,
                "createdAt": _timestamp(preset.created_at),
                "updatedAt": _timestamp(preset.updated_at),
            }
            for preset in room_presets
        ],
        "linkedIdentities": [
            {
                "id": str(source.id),
                "displayName": source.display_name,
                "nameColor": source.name_color,
                "avatarKey": source.avatar_key,
                "state": source.state,
                "createdAt": _timestamp(source.created_at),
                "mergedAt": _timestamp(alias.created_at),
            }
            for alias, source in aliases
        ],
        "sessions": [
            {
                "id": str(record.id),
                "deviceLabel": record.device_label,
                "rotatedFromId": (
                    str(record.rotated_from_id) if record.rotated_from_id else None
                ),
                "createdAt": _timestamp(record.created_at),
                "lastUsedAt": _timestamp(record.last_used_at),
                "expiresAt": _timestamp(record.expires_at),
                "revokedAt": _timestamp(record.revoked_at),
            }
            for record in sessions
        ],
        "gameParticipations": [
            {
                "game": {
                    "id": str(game.id),
                    "roomName": game.room_name,
                    "scoringMode": game.scoring_mode,
                    "scoringVersion": game.scoring_version,
                    "scoreLedgerVersion": game.score_ledger_version,
                    "ruleSnapshotVersion": game.rule_snapshot_version,
                    "ruleSnapshot": game.rule_snapshot,
                    "promptSourceMode": game.prompt_source_mode,
                    "hintMode": game.hint_mode,
                    "drawingSeconds": game.drawing_seconds,
                    "totalRounds": game.total_rounds,
                    "playerCount": game.player_count,
                    "startedAt": _timestamp(game.started_at),
                    "finishedAt": _timestamp(game.finished_at),
                },
                "participation": {
                    "seatId": str(seat.id),
                    "identityId": str(seat.user_id) if seat.user_id else None,
                    "displayName": seat.display_name_snapshot,
                    "nameColor": seat.name_color_snapshot,
                    "wasAnonymous": seat.is_anonymous_snapshot,
                    "finalScore": seat.final_score,
                    "finalRank": seat.final_rank,
                    "turnsPlayed": seat.turns_played,
                },
            }
            for seat, game in participations
        ],
        "drawnTurns": [
            {
                "turnId": str(turn.id),
                "gameId": str(turn.game_id),
                "identityId": str(turn.drawer_user_id) if turn.drawer_user_id else None,
                "participantSeatId": (
                    str(turn.drawer_participant_id)
                    if turn.drawer_participant_id
                    else None
                ),
                "roundNumber": turn.round_number,
                "turnNumber": turn.turn_number,
                "prompt": turn.prompt,
                "promptVersionId": (
                    str(turn.prompt_version_id) if turn.prompt_version_id else None
                ),
                "promptSourceKind": turn.prompt_source_kind,
                "durationSeconds": turn.duration_seconds,
                "guesserCount": turn.guesser_count,
                "promptAutoPicked": turn.prompt_auto_picked,
                "strokeCount": turn.stroke_count,
                "endReason": turn.end_reason,
                "wrongGuessCount": turn.wrong_guess_count,
                "nearMissCount": turn.near_miss_count,
                "promptOffers": [
                    {
                        "position": offer.position,
                        "prompt": offer.prompt_snapshot,
                        "selected": offer.selected,
                        "sourceKind": offer.source_kind,
                        "promptVersionId": (
                            str(offer.prompt_version_id)
                            if offer.prompt_version_id
                            else None
                        ),
                        "sourceRevisionIds": [
                            str(source.prompt_list_revision_id)
                            for source in offer.sources
                        ],
                    }
                    for offer in turn.prompt_offers
                ],
            }
            for turn in drawings
        ],
        "correctGuesses": [
            {
                "guessId": str(guess.id),
                "turnId": str(turn.id),
                "gameId": str(turn.game_id),
                "identityId": str(guess.user_id) if guess.user_id else None,
                "participantSeatId": (
                    str(guess.participant_id) if guess.participant_id else None
                ),
                "roundNumber": turn.round_number,
                "turnNumber": turn.turn_number,
                "prompt": turn.prompt,
                "pointsAwarded": guess.points_awarded,
                "guessTimeSeconds": guess.guess_time_seconds,
                "hintsUsed": outcome.hints_used,
                "pointsSpentOnHints": outcome.points_spent_on_hints,
                "wrongGuessesBefore": outcome.wrong_guess_count,
            }
            for guess, turn, outcome in guesses
        ],
        "turnOutcomes": [
            {
                "outcomeId": str(outcome.id),
                "turnId": str(turn.id),
                "gameId": str(turn.game_id),
                "participantSeatId": str(outcome.participant_id),
                "roundNumber": turn.round_number,
                "turnNumber": turn.turn_number,
                "prompt": turn.prompt,
                "eligible": outcome.eligible,
                "eligibilityReason": outcome.eligibility_reason,
                "outcome": outcome.outcome,
                "terminalState": outcome.terminal_state,
                "correctGuessTimeSeconds": outcome.correct_guess_time_seconds,
                "wrongGuessCount": outcome.wrong_guess_count,
                "nearMissCount": outcome.near_miss_count,
                "hintsUsed": outcome.hints_used,
                "pointsSpentOnHints": outcome.points_spent_on_hints,
            }
            for outcome, turn in turn_outcomes
        ],
        "scoreEvents": [
            {
                "eventId": str(event.id),
                "gameId": str(event.game_id),
                "turnId": str(event.turn_id) if event.turn_id else None,
                "participantSeatId": str(event.participant_id),
                "identityId": (
                    str(participant.user_id) if participant.user_id else None
                ),
                "eventOrder": event.event_order,
                "eventType": event.event_type,
                "pointsDelta": event.points_delta,
                "scoringVersion": event.scoring_version,
                "ruleSnapshotVersion": event.rule_snapshot_version,
                "correctsEventId": (
                    str(event.corrects_event_id)
                    if event.corrects_event_id
                    else None
                ),
                "createdAt": _timestamp(event.created_at),
            }
            for event, participant in score_events
        ],
        "retainedMessages": [
            {
                "messageId": str(message.id),
                "gameId": str(message.game_id) if message.game_id else None,
                "turnId": str(message.turn_id) if message.turn_id else None,
                "participantSeatId": (
                    str(message.sender_seat_id) if message.sender_seat_id else None
                ),
                "messageKind": message.message_kind,
                "audience": message.audience,
                "nearMissKind": message.near_miss_kind,
                "text": message.text,
                "createdAt": _timestamp(message.created_at),
                "expiresAt": _timestamp(message.expires_at),
            }
            for message in retained_messages
        ],
        # A reporter's own text and submitted evidence belongs in their export.
        # The reported account id, reviewer id, and internal resolution note do
        # not: those are other people's or moderation-workflow data.
        "reportsSubmitted": [
            {
                "id": str(report.id),
                "gameId": str(report.game_id) if report.game_id else None,
                "turnId": str(report.turn_id) if report.turn_id else None,
                "reason": report.reason,
                "details": report.details,
                "contextSnapshot": report.context_snapshot,
                "messageEvidence": [
                    {
                        "sourceMessageId": str(
                            evidence.source_message_snapshot_id
                        ),
                        "gameId": (
                            str(evidence.game_id_snapshot)
                            if evidence.game_id_snapshot
                            else None
                        ),
                        "turnId": (
                            str(evidence.turn_id_snapshot)
                            if evidence.turn_id_snapshot
                            else None
                        ),
                        "messageKind": evidence.message_kind,
                        "audience": evidence.audience,
                        "nearMissKind": evidence.near_miss_kind,
                        "text": evidence.text_snapshot,
                        "messageCreatedAt": _timestamp(
                            evidence.message_created_at
                        ),
                    }
                    for evidence in report.message_evidence
                ],
                "status": report.status,
                "createdAt": _timestamp(report.created_at),
                "updatedAt": _timestamp(report.updated_at),
                "reviewedAt": _timestamp(report.reviewed_at),
            }
            for report in submitted_reports
        ],
        # The requester gets their own report text and immutable evidence
        # snapshots. Owner/reviewer identities and internal notes stay private.
        "promptContentReportsSubmitted": [
            {
                "id": str(report.id),
                "promptListId": (
                    str(report.prompt_list_id) if report.prompt_list_id else None
                ),
                "promptVersionId": (
                    str(report.prompt_version_id)
                    if report.prompt_version_id
                    else None
                ),
                "targetType": report.target_type,
                "listName": report.list_name_snapshot,
                "prompt": report.prompt_snapshot,
                "reason": report.reason,
                "details": report.details,
                "status": report.status,
                "moderationState": report.resolution_moderation_state,
                "createdAt": _timestamp(report.created_at),
                "updatedAt": _timestamp(report.updated_at),
                "reviewedAt": _timestamp(report.reviewed_at),
            }
            for report in submitted_prompt_content_reports
        ],
        # A bug report is the requester's own words about the software plus the
        # diagnostics their browser volunteered, so all of it comes back. The
        # administrator's note and identity do not: those are the operator's
        # record of what was done, the same line the suspensions block draws.
        # The screenshot is reported by shape rather than embedded - it is
        # erased when the report is decided, and an export is not a way to keep
        # a copy of it alive.
        "bugReportsSubmitted": [
            {
                "id": str(report.id),
                "area": report.area,
                "severity": report.severity,
                "summary": report.summary,
                "details": report.details,
                "buildSha": report.build_sha,
                "route": report.route,
                "roomCode": report.room_code,
                "clientContext": report.client_context,
                "screenshotStatus": report.screenshot_status,
                "screenshotByteSize": report.screenshot_byte_size,
                "status": report.status,
                "createdAt": _timestamp(report.created_at),
                "updatedAt": _timestamp(report.updated_at),
                "reviewedAt": _timestamp(report.reviewed_at),
            }
            for report in submitted_bug_reports
        ],
        # Suspension history is requester data, but moderator identities and
        # internal revocation notes remain private.
        "suspensions": [
            {
                "id": str(ban.id),
                "reason": ban.reason,
                "expiresAt": _timestamp(ban.expires_at),
                "isActive": ban.is_active and (
                    ban.expires_at is None or ban.expires_at > generated_at
                ),
                "createdAt": _timestamp(ban.created_at),
                "revokedAt": _timestamp(ban.revoked_at),
            }
            for ban in suspensions
        ],
        "blocks": [
            {
                "blockedUserId": str(block.blocked_user_id),
                "createdAt": _timestamp(block.created_at),
            }
            for block in blocks
        ],
        "friends": [
            {
                "userId": str(
                    friendship.user_high_id
                    if friendship.user_low_id in identity_ids
                    else friendship.user_low_id
                ),
                "status": friendship.status,
                # A boolean rather than the requester's id. Which of the two
                # asked is a fact about this pair and the reader is one of
                # them, but a raw third-party account id in a downloadable
                # document travels further than it needs to - the blocks
                # export above avoids the same thing.
                "requestedByMe": friendship.requested_by_id in identity_ids,
                "createdAt": _timestamp(friendship.created_at),
                "respondedAt": _timestamp(friendship.responded_at)
                if friendship.responded_at
                else None,
            }
            for friendship in friendships
        ],
        # Audit details and other actor identifiers are deliberately omitted:
        # they can contain moderator or third-party data. This still exposes
        # every security event in which the requester participated.
        "accountEvents": [
            {
                "id": str(event.id),
                "eventType": event.event_type,
                "requesterWasActor": event.actor_user_id in identity_ids,
                "requesterWasTarget": event.target_user_id in identity_ids,
                "createdAt": _timestamp(event.created_at),
            }
            for event in audit_events
        ],
        "exportRequests": [
            {
                "id": str(job.id),
                "status": job.status,
                "schemaVersion": job.schema_version,
                "createdAt": _timestamp(job.created_at),
                "startedAt": _timestamp(job.started_at),
                "completedAt": _timestamp(job.completed_at),
                "expiresAt": _timestamp(job.expires_at),
            }
            for job in export_jobs
        ],
    }


async def process_data_export(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    export_id: str | UUID,
    now: datetime | None = None,
    retry_stale: bool = False,
) -> bool:
    """Claim and complete one job; a crash leaves a durable retryable record."""
    processed_at = now or datetime.now(timezone.utc)
    db_export_id = _entity_id(export_id)
    async with session_factory() as session:
        async with session.begin():
            job = await session.scalar(
                select(DataExport)
                .where(DataExport.id == db_export_id)
                .with_for_update()
            )
            stale = (
                retry_stale
                and job is not None
                and job.status == DataExportStatus.PROCESSING.value
                and job.started_at is not None
                and job.started_at <= processed_at - STALE_PROCESSING_AFTER
            )
            if job is None or (
                job.status != DataExportStatus.PENDING.value and not stale
            ):
                return False
            if job.expires_at <= processed_at:
                await session.delete(job)
                return False
            job.status = DataExportStatus.PROCESSING.value
            job.started_at = processed_at
            job.completed_at = None
            job.failure_code = None
            owner_id = job.user_id

    try:
        async with session_factory() as session:
            artifact = await _build_export_artifact(
                session, user_id=owner_id, generated_at=processed_at
            )
        async with session_factory() as session:
            async with session.begin():
                job = await session.scalar(
                    select(DataExport)
                    .where(DataExport.id == db_export_id)
                    .with_for_update()
                )
                if job is None or job.status != DataExportStatus.PROCESSING.value:
                    return False
                completed_at = (
                    processed_at if now is not None else datetime.now(timezone.utc)
                )
                job.artifact, job.artifact_encoding = encode_export_artifact(
                    artifact
                )
                job.status = DataExportStatus.READY.value
                job.completed_at = completed_at
                job.failure_code = None
        return True
    except Exception:
        logger.exception("Account data export %s failed", db_export_id)
        async with session_factory() as session:
            async with session.begin():
                job = await session.get(DataExport, db_export_id)
                if job is not None and job.status == DataExportStatus.PROCESSING.value:
                    job.artifact = None
                    job.artifact_encoding = None
                    job.status = DataExportStatus.FAILED.value
                    job.completed_at = (
                        processed_at if now is not None else datetime.now(timezone.utc)
                    )
                    job.failure_code = "generation_failed"
        return False


async def process_pending_data_exports(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    limit: int = DEFAULT_EXPORT_BATCH_SIZE,
) -> int:
    """Process one bounded batch, including jobs orphaned by a crashed worker."""
    if limit < 1:
        raise ValueError("limit must be positive")
    checked_at = now or datetime.now(timezone.utc)
    async with session_factory() as session:
        job_ids = list(
            (
                await session.scalars(
                    select(DataExport.id)
                    .where(
                        DataExport.expires_at > checked_at,
                        or_(
                            DataExport.status == DataExportStatus.PENDING.value,
                            (
                                DataExport.status
                                == DataExportStatus.PROCESSING.value
                            )
                            & (
                                DataExport.started_at
                                <= checked_at - STALE_PROCESSING_AFTER
                            ),
                        ),
                    )
                    .order_by(DataExport.created_at, DataExport.id)
                    .limit(limit)
                )
            ).all()
        )
    completed = 0
    for job_id in job_ids:
        completed += int(
            await process_data_export(
                session_factory,
                export_id=job_id,
                now=checked_at,
                retry_stale=True,
            )
        )
    return completed


async def get_data_export(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    export_id: str | UUID,
    user_id: str | UUID,
) -> DataExport | None:
    async with session_factory() as session:
        return await session.scalar(
            select(DataExport).where(
                DataExport.id == _entity_id(export_id),
                DataExport.user_id == _entity_id(user_id),
            )
        )


async def list_data_exports(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str | UUID,
    limit: int = 20,
) -> list[DataExport]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(DataExport)
                    .where(DataExport.user_id == _entity_id(user_id))
                    .order_by(DataExport.created_at.desc(), DataExport.id.desc())
                    .limit(limit)
                )
            ).all()
        )


async def anonymize_account(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str | UUID,
    now: datetime | None = None,
) -> AccountDeletionResult:
    """Erase identity while retaining shared scores and immutable game structure."""
    deleted_at = now or datetime.now(timezone.utc)
    db_user_id = _entity_id(user_id)
    async with session_factory() as session:
        async with session.begin():
            account = await session.scalar(
                select(User).where(User.id == db_user_id).with_for_update()
            )
            if account is None or account.state == AccountState.DELETED.value:
                raise AccountDataError("account not found")
            if account.state == AccountState.MERGED.value:
                raise AccountDataError("merged identities must be deleted through their account")

            source_ids = list(
                (
                    await session.scalars(
                        select(IdentityAlias.source_user_id).where(
                            IdentityAlias.target_user_id == account.id
                        )
                    )
                ).all()
            )
            identity_ids = [account.id, *source_ids]
            friends_of: set[str] = set()

            owned_concept_ids = list(
                (
                    await session.scalars(
                        select(PromptVersion.concept_id)
                        .join(
                            PromptListRevisionItem,
                            PromptListRevisionItem.prompt_version_id
                            == PromptVersion.id,
                        )
                        .join(
                            PromptListRevision,
                            PromptListRevision.id
                            == PromptListRevisionItem.revision_id,
                        )
                        .join(
                            PromptList,
                            PromptList.id == PromptListRevision.prompt_list_id,
                        )
                        .where(PromptList.owner_user_id.in_(identity_ids))
                        .distinct()
                    )
                ).all()
            )

            sessions = await session.execute(
                update(AuthSession)
                .where(
                    AuthSession.user_id.in_(identity_ids),
                    AuthSession.revoked_at.is_(None),
                )
                .values(revoked_at=deleted_at)
            )
            await session.execute(
                update(GameParticipant)
                .where(GameParticipant.user_id.in_(identity_ids))
                .values(
                    display_name_snapshot=DELETED_DISPLAY_NAME,
                    name_color_snapshot=None,
                    is_anonymous_snapshot=True,
                )
            )
            await session.execute(
                update(TurnRecord)
                .where(TurnRecord.drawer_user_id.in_(identity_ids))
                .values(
                    drawer_display_name_snapshot=DELETED_DISPLAY_NAME,
                    drawer_name_color_snapshot=None,
                    drawer_is_anonymous_snapshot=True,
                )
            )
            # A drawing is authored content, so it goes rather than being
            # anonymised like the turn around it. The row stays behind saying
            # so, which keeps an erased drawing distinguishable from one the
            # recap dropped and from a turn nobody drew on.
            await session.execute(
                update(TurnDrawing)
                .where(
                    TurnDrawing.turn_id.in_(
                        select(TurnRecord.id).where(
                            TurnRecord.drawer_user_id.in_(identity_ids)
                        )
                    )
                )
                .values(
                    status=TurnDrawingStatus.DELETED.value,
                    payload=None,
                    object_key=None,
                    checksum_sha256=None,
                    byte_size=None,
                    format_magic=None,
                    format_version=None,
                    deleted_at=deleted_at,
                    updated_at=deleted_at,
                )
            )
            await session.execute(
                update(TurnGuess)
                .where(TurnGuess.user_id.in_(identity_ids))
                .values(
                    display_name_snapshot=DELETED_DISPLAY_NAME,
                    name_color_snapshot=None,
                    is_anonymous_snapshot=True,
                )
            )
            # Ordinary retained messages are short-lived user content and are
            # erased immediately on account deletion. Evidence already copied
            # into a report survives with neutral presentation.
            await session.execute(
                delete(RoomMessage).where(RoomMessage.sender_user_id.in_(identity_ids))
            )
            await session.execute(
                update(PlayerReportMessageEvidence)
                .where(
                    PlayerReportMessageEvidence.sender_user_id.in_(identity_ids)
                )
                .values(
                    sender_display_name_snapshot=DELETED_DISPLAY_NAME,
                    sender_name_color_snapshot=None,
                    sender_is_anonymous_snapshot=True,
                )
            )
            # A bug report outlives the account that filed it - a defect is not
            # un-found by an erasure, and the foreign key detaches the reporter.
            # The screenshot does not: it is a picture of somebody's screen, and
            # nothing about keeping the bug report needs it.
            await session.execute(
                update(BugReport)
                .where(
                    BugReport.reporter_user_id.in_(identity_ids),
                    BugReport.screenshot_status == "ready",
                )
                .values(screenshot_payload=None, screenshot_status="erased")
            )
            await session.execute(
                delete(UploadedAvatarAsset).where(
                    UploadedAvatarAsset.user_id.in_(identity_ids)
                )
            )
            await session.execute(
                delete(ExternalIdentity).where(
                    ExternalIdentity.user_id.in_(identity_ids)
                )
            )
            await session.execute(
                delete(DataExport).where(DataExport.user_id.in_(identity_ids))
            )
            await session.execute(
                delete(UserSettings).where(UserSettings.user_id.in_(identity_ids))
            )
            await session.execute(
                delete(RoomPreset).where(RoomPreset.owner_user_id.in_(identity_ids))
            )
            # Player-authored lists are private account data, unlike shared game
            # history. Remove their revisions and then their now-unreferenced
            # prompt concepts instead of leaving ownerless content behind.
            await session.execute(
                delete(PromptList).where(PromptList.owner_user_id.in_(identity_ids))
            )
            if owned_concept_ids:
                await session.execute(
                    delete(PromptConcept).where(PromptConcept.id.in_(owned_concept_ids))
                )
            await session.execute(
                delete(UserBlock).where(
                    or_(
                        UserBlock.blocker_user_id.in_(identity_ids),
                        UserBlock.blocked_user_id.in_(identity_ids),
                    )
                )
            )
            # Read before they go: the accounts on the other side of these
            # rows are about to lose something from their own lists, and after
            # the delete there is nothing left to say who they were.
            for low, high in (
                await session.execute(
                    select(Friendship.user_low_id, Friendship.user_high_id).where(
                        or_(
                            Friendship.user_low_id.in_(identity_ids),
                            Friendship.user_high_id.in_(identity_ids),
                        )
                    )
                )
            ).all():
                friends_of.update(
                    str(side)
                    for side in (low, high)
                    if side not in identity_ids
                )
            # Both halves, and every status: a refusal this account sent or
            # received is as much a fact about them as an accepted friendship.
            await session.execute(
                delete(Friendship).where(
                    or_(
                        Friendship.user_low_id.in_(identity_ids),
                        Friendship.user_high_id.in_(identity_ids),
                    )
                )
            )
            # A live reset link is a way into an account that no longer
            # exists, and both tables hold an address the erasure is supposed
            # to remove. Queued messages go with them: a verification mail
            # delivered after deletion would be addressed to somebody whose
            # account is gone. Messages already sent keep their row, with the
            # link back to the account dropped by ON DELETE SET NULL - that a
            # message was sent is a fact about the message.
            await session.execute(
                delete(AuthToken).where(AuthToken.user_id.in_(identity_ids))
            )
            await session.execute(
                delete(EmailOutboxEntry).where(
                    EmailOutboxEntry.user_id.in_(identity_ids),
                    EmailOutboxEntry.state == EmailOutboxState.PENDING.value,
                )
            )
            await session.execute(
                update(EmailOutboxEntry)
                .where(EmailOutboxEntry.user_id.in_(identity_ids))
                .values(to_address=DELETED_EMAIL_ADDRESS, user_id=None)
            )

            for identity in (
                await session.scalars(select(User).where(User.id.in_(identity_ids)))
            ).all():
                identity.username = None
                identity.password_hash = None
                identity.email = None
                identity.email_verified_at = None
                identity.display_name = DELETED_DISPLAY_NAME
                identity.name_color = None
                identity.avatar_key = None
                identity.role = UserRole.USER.value
                identity.updated_at = deleted_at
                identity.last_login_at = deleted_at
                identity.last_active_at = deleted_at
                if identity.id == account.id:
                    identity.state = AccountState.DELETED.value

            session.add(
                AuditEvent(
                    id=generate_uuid(),
                    event_type="account.deleted",
                    actor_user_id=account.id,
                    target_user_id=account.id,
                    target_type=AuditTargetType.USER.value,
                    target_id=str(account.id),
                    details={"identities_anonymized": len(identity_ids)},
                    created_at=deleted_at,
                )
            )
            return AccountDeletionResult(
                user_id=str(account.id),
                identities_anonymized=len(identity_ids),
                sessions_revoked=int(sessions.rowcount or 0),
                friends_notified=tuple(sorted(friends_of)),
            )


def export_status_payload(job: DataExport) -> dict:
    ready = job.status == DataExportStatus.READY.value and job.artifact is not None
    return {
        "id": str(job.id),
        "status": job.status,
        "schemaVersion": job.schema_version,
        "createdAt": _timestamp(job.created_at),
        "startedAt": _timestamp(job.started_at),
        "completedAt": _timestamp(job.completed_at),
        "expiresAt": _timestamp(job.expires_at),
        "downloadUrl": f"/api/auth/data-exports/{job.id}/download" if ready else None,
        "failureCode": job.failure_code,
    }


async def _run_pending(limit: int) -> int:
    try:
        await init_db()
        return await process_pending_data_exports(async_session_factory, limit=limit)
    finally:
        await async_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process a bounded batch of pending or stale account exports."
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_EXPORT_BATCH_SIZE)
    args = parser.parse_args()
    try:
        completed = asyncio.run(_run_pending(args.limit))
    except ValueError as error:
        parser.error(str(error))
    print(f"Completed {completed} account data exports.")


if __name__ == "__main__":
    main()
