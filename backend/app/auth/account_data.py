"""Versioned account exports and history-safe account anonymization."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import async_engine, async_session_factory, init_db
from app.db.models import (
    AuditEvent,
    AuthSession,
    DataExport,
    ExternalIdentity,
    GameParticipant,
    GameRecord,
    IdentityAlias,
    TurnGuess,
    TurnRecord,
    UploadedAvatarAsset,
    User,
    generate_uuid,
)
from app.domain_values import AccountState, DataExportStatus, UserRole


EXPORT_SCHEMA_VERSION = 1
EXPORT_TTL = timedelta(days=7)
STALE_PROCESSING_AFTER = timedelta(minutes=15)
DELETED_DISPLAY_NAME = "Deleted player"
DEFAULT_EXPORT_BATCH_SIZE = 25

logger = logging.getLogger(__name__)


class AccountDataError(RuntimeError):
    """Raised when an export or deletion cannot apply to an account."""


@dataclass(frozen=True)
class AccountDeletionResult:
    user_id: str
    identities_anonymized: int
    sessions_revoked: int


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
                .order_by(IdentityAlias.created_at, IdentityAlias.id)
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
                    details={
                        "export_id": str(job.id),
                        "schema_version": EXPORT_SCHEMA_VERSION,
                    },
                )
            )
        return job


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
                .order_by(TurnRecord.game_id, TurnRecord.round_number, TurnRecord.turn_number)
            )
        ).all()
    )
    guesses = list(
        (
            await session.execute(
                select(TurnGuess, TurnRecord)
                .join(TurnRecord, TurnRecord.id == TurnGuess.turn_id)
                .where(TurnGuess.user_id.in_(identity_ids))
                .order_by(TurnRecord.game_id, TurnRecord.round_number, TurnRecord.turn_number)
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
    export_jobs = list(
        (
            await session.scalars(
                select(DataExport)
                .where(DataExport.user_id == account.id)
                .order_by(DataExport.created_at, DataExport.id)
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
                "roundNumber": turn.round_number,
                "turnNumber": turn.turn_number,
                "prompt": turn.prompt,
                "durationSeconds": turn.duration_seconds,
                "guesserCount": turn.guesser_count,
                "promptAutoPicked": turn.prompt_auto_picked,
                "strokeCount": turn.stroke_count,
                "endReason": turn.end_reason,
                "wrongGuessCount": turn.wrong_guess_count,
                "nearMissCount": turn.near_miss_count,
            }
            for turn in drawings
        ],
        "correctGuesses": [
            {
                "guessId": str(guess.id),
                "turnId": str(turn.id),
                "gameId": str(turn.game_id),
                "identityId": str(guess.user_id) if guess.user_id else None,
                "roundNumber": turn.round_number,
                "turnNumber": turn.turn_number,
                "prompt": turn.prompt,
                "pointsAwarded": guess.points_awarded,
                "guessTimeSeconds": guess.guess_time_seconds,
                "hintsUsed": guess.hints_used,
                "pointsSpentOnHints": guess.points_spent_on_hints,
                "wrongGuessesBefore": guess.wrong_guesses_before,
            }
            for guess, turn in guesses
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
                job.artifact = artifact
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
            await session.execute(
                update(TurnGuess)
                .where(TurnGuess.user_id.in_(identity_ids))
                .values(
                    display_name_snapshot=DELETED_DISPLAY_NAME,
                    name_color_snapshot=None,
                    is_anonymous_snapshot=True,
                )
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
                    details={"identities_anonymized": len(identity_ids)},
                    created_at=deleted_at,
                )
            )
            return AccountDeletionResult(
                user_id=str(account.id),
                identities_anonymized=len(identity_ids),
                sessions_revoked=int(sessions.rowcount or 0),
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
