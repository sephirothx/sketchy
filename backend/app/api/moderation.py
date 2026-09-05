"""Player reports and role-gated moderation actions."""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.auth.avatars import avatar_url
from app.services.avatars import remove_avatar
from app.auth.rate_limit import (
    PersistentRateLimiter,
    client_key,
)
from app.auth.audit import audit_coordinates
from app.auth.bans import active_ban_filter, active_ban_for_user
from app.auth.mail import queue_email
from app.services.player_reports import context_around, record_player_report
from app.auth.sessions import revoke_all_sessions
from app.auth.warnings import pending_warning_payload
from app.db.models import (
    AuditEvent,
    GameRecord,
    PlayerReport,
    PromptContentReport,
    PromptList,
    PromptListRevision,
    PromptListRevisionItem,
    PromptVersion,
    RoomMessage,
    TurnRecord,
    User,
    UserBan,
    UserWarning,
    generate_uuid,
)
from app.domain_values import (
    AccountState,
    AuditTargetType,
    EmailTemplate,
    PromptContentModerationState,
    PromptContentReportReason,
    PromptListVisibility,
    ReportReason,
    ReportStatus,
    UserRole,
)


MAX_REPORT_CONTEXT_BYTES = 32_768
MAX_REPORT_DETAILS = 2_000
MAX_RESOLUTION_NOTE = 2_000
MAX_REPORT_MESSAGES = 20
OnUserBanned = Callable[[str], Awaitable[None]]
OnUserWarned = Callable[[str], Awaitable[None]]


class ReportBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    reported_user_id: UUID = Field(alias="reportedUserId")
    game_id: UUID | None = Field(default=None, alias="gameId")
    turn_id: UUID | None = Field(default=None, alias="turnId")
    reason: ReportReason
    details: str = Field(min_length=1, max_length=MAX_REPORT_DETAILS)
    message_ids: list[UUID] = Field(
        default_factory=list, alias="messageIds", max_length=MAX_REPORT_MESSAGES
    )
    context_snapshot: dict = Field(default_factory=dict, alias="contextSnapshot")

    @field_validator("details")
    @classmethod
    def clean_details(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("details cannot be blank")
        return cleaned

    @field_validator("context_snapshot")
    @classmethod
    def bound_context(cls, value: dict) -> dict:
        encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_REPORT_CONTEXT_BYTES:
            raise ValueError("contextSnapshot is too large")
        return value

    @field_validator("message_ids")
    @classmethod
    def unique_message_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("messageIds must be unique")
        return value


class ReportReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["resolved", "dismissed"]
    note: str = Field(min_length=1, max_length=MAX_RESOLUTION_NOTE)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("note cannot be blank")
        return cleaned


class PromptContentReportBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    prompt_list_id: UUID = Field(alias="promptListId")
    prompt_version_id: UUID | None = Field(default=None, alias="promptVersionId")
    share_code: str | None = Field(
        default=None, alias="shareCode", min_length=8, max_length=24
    )
    reason: PromptContentReportReason
    details: str = Field(min_length=1, max_length=MAX_REPORT_DETAILS)

    @field_validator("details")
    @classmethod
    def clean_details(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("details cannot be blank")
        return cleaned


class PromptContentReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: Literal["resolved", "dismissed"]
    note: str = Field(min_length=1, max_length=MAX_RESOLUTION_NOTE)
    moderation_state: Literal["active", "hidden"] | None = Field(
        default=None, alias="moderationState"
    )

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("note cannot be blank")
        return cleaned


class BanBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    user_id: UUID = Field(alias="userId")
    reason: str = Field(min_length=1, max_length=255)
    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    # Optional: a suspension can be issued directly. When it comes from a
    # report, recording which one is what lets the suspended player be shown
    # the messages it was about.
    report_id: UUID | None = Field(default=None, alias="reportId")

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reason cannot be blank")
        return cleaned

    @field_validator("expires_at")
    @classmethod
    def aware_expiry(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("expiresAt must include a timezone")
        return value.astimezone(timezone.utc) if value is not None else None


class BanRevokeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reason cannot be blank")
        return cleaned


def _content_target(prompt_list_id, prompt_version_id) -> tuple[str, str]:
    """Name the reported content itself, not its owner.

    The owner already rides along in `target_user_id`. What the ledger could
    not say before is which list or prompt an action was about, which is the
    only question worth asking of a takedown.
    """
    if prompt_version_id is not None:
        return AuditTargetType.PROMPT_VERSION.value, str(prompt_version_id)
    return AuditTargetType.PROMPT_LIST.value, str(prompt_list_id)


async def _reported_player_context(
    session: AsyncSession, reports: list[PlayerReport]
) -> dict[UUID, dict]:
    """Who each report is about, as a moderator weighs it.

    Standing, not identity: account age, how often this player has come up
    before, and whether a suspension is already in force. Computed for the
    page in three grouped queries rather than per report.
    """
    user_ids = {r.reported_user_id for r in reports if r.reported_user_id}
    if not user_ids:
        return {}
    users = (
        await session.scalars(select(User).where(User.id.in_(user_ids)))
    ).all()
    report_totals = dict(
        (
            await session.execute(
                select(PlayerReport.reported_user_id, func.count())
                .where(PlayerReport.reported_user_id.in_(user_ids))
                .group_by(PlayerReport.reported_user_id)
            )
        ).all()
    )
    warning_totals = dict(
        (
            await session.execute(
                select(UserWarning.user_id, func.count())
                .where(UserWarning.user_id.in_(user_ids))
                .group_by(UserWarning.user_id)
            )
        ).all()
    )
    now = datetime.now(timezone.utc)
    suspended = set(
        (
            await session.scalars(
                select(UserBan.user_id).where(
                    UserBan.user_id.in_(user_ids), *active_ban_filter(now)
                )
            )
        ).all()
    )
    return {
        user.id: {
            "displayName": user.display_name,
            # So a report about a picture can be judged from the queue.
            "avatarUrl": avatar_url(user.avatar_key),
            "registered": user.state == AccountState.REGISTERED.value,
            "createdAt": user.created_at.isoformat(),
            # This report itself is not "prior".
            "priorReports": max(0, report_totals.get(user.id, 0) - 1),
            "priorWarnings": warning_totals.get(user.id, 0),
            "activeSuspension": user.id in suspended,
        }
        for user in users
    }


def _report_payload(
    report: PlayerReport, player_context: dict[UUID, dict] | None = None
) -> dict:
    return {
        "reportedPlayer": (
            (player_context or {}).get(report.reported_user_id)
            if report.reported_user_id
            else None
        ),
        "id": str(report.id),
        "reporterUserId": (
            str(report.reporter_user_id) if report.reporter_user_id else None
        ),
        "reportedUserId": (
            str(report.reported_user_id) if report.reported_user_id else None
        ),
        "gameId": str(report.game_id) if report.game_id else None,
        "turnId": str(report.turn_id) if report.turn_id else None,
        "reason": report.reason,
        "details": report.details,
        "contextSnapshot": report.context_snapshot,
        "messageEvidence": [
            {
                "sourceMessageId": str(evidence.source_message_snapshot_id),
                "sourceAvailable": evidence.source_message_id is not None,
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
                "senderUserId": (
                    str(evidence.sender_user_id)
                    if evidence.sender_user_id
                    else None
                ),
                "senderDisplayName": evidence.sender_display_name_snapshot,
                "senderNameColor": evidence.sender_name_color_snapshot,
                "senderWasAnonymous": evidence.sender_is_anonymous_snapshot,
                "messageKind": evidence.message_kind,
                "audience": evidence.audience,
                "nearMissKind": evidence.near_miss_kind,
                "role": evidence.role,
                "text": evidence.text_snapshot,
                "messageCreatedAt": evidence.message_created_at.isoformat(),
                "copiedAt": evidence.copied_at.isoformat(),
            }
            for evidence in report.message_evidence
        ],
        "status": report.status,
        "reviewedByUserId": (
            str(report.reviewed_by_user_id) if report.reviewed_by_user_id else None
        ),
        "resolutionNote": report.resolution_note,
        "createdAt": report.created_at.isoformat(),
        "updatedAt": report.updated_at.isoformat(),
        "reviewedAt": report.reviewed_at.isoformat() if report.reviewed_at else None,
    }


def _prompt_content_report_payload(report: PromptContentReport) -> dict:
    return {
        "id": str(report.id),
        "reporterUserId": (
            str(report.reporter_user_id) if report.reporter_user_id else None
        ),
        "reportedOwnerUserId": (
            str(report.reported_owner_user_id)
            if report.reported_owner_user_id
            else None
        ),
        "promptListId": str(report.prompt_list_id) if report.prompt_list_id else None,
        "promptVersionId": (
            str(report.prompt_version_id) if report.prompt_version_id else None
        ),
        "targetType": report.target_type,
        "listName": report.list_name_snapshot,
        "prompt": report.prompt_snapshot,
        "reason": report.reason,
        "details": report.details,
        "status": report.status,
        "reviewedByUserId": (
            str(report.reviewed_by_user_id) if report.reviewed_by_user_id else None
        ),
        "resolutionNote": report.resolution_note,
        "moderationState": report.resolution_moderation_state,
        "createdAt": report.created_at.isoformat(),
        "updatedAt": report.updated_at.isoformat(),
        "reviewedAt": report.reviewed_at.isoformat() if report.reviewed_at else None,
    }


class WarningBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    user_id: UUID = Field(alias="userId")
    reason: str = Field(min_length=1, max_length=255)
    # The report this warning decides. Recording it is what lets the warned
    # player be shown the messages the complaint was about.
    report_id: UUID | None = Field(default=None, alias="reportId")

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reason cannot be blank")
        return cleaned


def _ban_payload(ban: UserBan, display_name: str | None = None) -> dict:
    """One suspension, as a moderator needs to read it.

    The display name is passed in rather than followed through the relationship
    so that listing many does not become a query each. It is optional because
    an anonymised account no longer has one to show.
    """
    now = datetime.now(timezone.utc)
    effectively_active = ban.is_active and (
        ban.expires_at is None or ban.expires_at > now
    )
    return {
        "id": str(ban.id),
        "userId": str(ban.user_id) if ban.user_id else None,
        "displayName": display_name,
        "bannedByUserId": (
            str(ban.banned_by_user_id) if ban.banned_by_user_id else None
        ),
        "reason": ban.reason,
        "expiresAt": ban.expires_at.isoformat() if ban.expires_at else None,
        "isActive": effectively_active,
        "createdAt": ban.created_at.isoformat(),
        "revokedAt": ban.revoked_at.isoformat() if ban.revoked_at else None,
        "revokedByUserId": (
            str(ban.revoked_by_user_id) if ban.revoked_by_user_id else None
        ),
        "revokeReason": ban.revoke_reason,
    }


async def _reviewer(session: AsyncSession, request: Request) -> User:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in first.")
    user = await session.get(User, UUID(user_id))
    if user is None or user.role not in {
        UserRole.MODERATOR.value,
        UserRole.ADMIN.value,
    }:
        raise HTTPException(status_code=403, detail="Moderator access required.")
    return user


def create_moderation_router(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    on_user_banned: OnUserBanned | None = None,
    on_user_warned: OnUserWarned | None = None,
    # Called with the account whose picture a moderator took down, so live
    # seats and the lobby's identity cache stop showing it.
    on_avatar_changed: Callable[[str, str | None], Awaitable[None]] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")
    report_limiter = PersistentRateLimiter(
        session_factory, scope="report-submit", limit=10, window_seconds=3600
    )
    content_report_limiter = PersistentRateLimiter(
        session_factory,
        scope="prompt-content-report-submit",
        limit=10,
        window_seconds=3600,
    )

    @router.post("/prompt-content-reports", status_code=201)
    async def submit_prompt_content_report(
        body: PromptContentReportBody, request: Request
    ):
        reporter_id = getattr(request.state, "user_id", None)
        if not reporter_id:
            raise HTTPException(status_code=401, detail="Sign in first.")
        if not await content_report_limiter.check(client_key(request)):
            raise HTTPException(
                status_code=429,
                detail="Too many reports. Please wait before sending another.",
            )
        db_reporter_id = UUID(reporter_id)
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        async with session_factory() as session:
            async with session.begin():
                prompt_list = await session.get(PromptList, body.prompt_list_id)
                if (
                    prompt_list is None
                    or prompt_list.is_bundled
                    or prompt_list.owner_user_id is None
                    or (
                        prompt_list.visibility
                        != PromptListVisibility.PUBLIC.value
                        and not (
                            prompt_list.visibility
                            == PromptListVisibility.UNLISTED.value
                            and body.share_code == prompt_list.share_code
                        )
                    )
                ):
                    raise HTTPException(
                        status_code=404, detail="No reportable prompt list found."
                    )
                if prompt_list.owner_user_id == db_reporter_id:
                    raise HTTPException(
                        status_code=422,
                        detail="You cannot report your own prompt list.",
                    )

                prompt_version = None
                if body.prompt_version_id is not None:
                    prompt_version = await session.scalar(
                        select(PromptVersion)
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
                        .where(
                            PromptVersion.id == body.prompt_version_id,
                            PromptListRevision.prompt_list_id == prompt_list.id,
                        )
                    )
                    if prompt_version is None:
                        raise HTTPException(
                            status_code=422,
                            detail="That prompt does not belong to this list.",
                        )

                # The rate limiter bounds how many reports one client may
                # send; this bounds how many times the same content may be
                # reported by the same person, which is the noise a queue
                # actually drowns in.
                already_open = await session.scalar(
                    select(PromptContentReport.id).where(
                        PromptContentReport.reporter_user_id == db_reporter_id,
                        PromptContentReport.status == ReportStatus.PENDING.value,
                        PromptContentReport.prompt_list_id == prompt_list.id,
                        PromptContentReport.prompt_version_id
                        == (prompt_version.id if prompt_version else None),
                    )
                )
                if already_open is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "You have already reported this, and a moderator "
                            "has not reviewed it yet."
                        ),
                    )

                report = PromptContentReport(
                    id=generate_uuid(),
                    reporter_user_id=db_reporter_id,
                    reported_owner_user_id=prompt_list.owner_user_id,
                    prompt_list_id=prompt_list.id,
                    prompt_version_id=(prompt_version.id if prompt_version else None),
                    target_type="prompt" if prompt_version else "list",
                    list_name_snapshot=prompt_list.name,
                    prompt_snapshot=(
                        prompt_version.canonical_answer if prompt_version else None
                    ),
                    reason=body.reason.value,
                    details=body.details,
                )
                session.add(report)
                content_target_type, content_target_id = _content_target(
                    prompt_list.id, prompt_version.id if prompt_version else None
                )
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="prompt_content_report.submitted",
                        actor_user_id=db_reporter_id,
                        target_user_id=prompt_list.owner_user_id,
                        target_type=content_target_type,
                        target_id=content_target_id,
                        request_id=request_id,
                        ip_hash=ip_hash,
                        details={
                            "report_id": str(report.id),
                            "target_type": report.target_type,
                            "prompt_list_id": str(prompt_list.id),
                            "prompt_version_id": (
                                str(prompt_version.id) if prompt_version else None
                            ),
                            "reason": body.reason.value,
                        },
                    )
                )
                try:
                    await session.flush()
                except IntegrityError as error:
                    # Two submissions in the same instant both passed the
                    # check above; the partial unique index is what really
                    # decides, and the loser is told what a slower
                    # duplicate would have been told.
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "You have already reported this, and a moderator "
                            "has not reviewed it yet."
                        ),
                    ) from error
            return {
                "id": str(report.id),
                "status": report.status,
                "createdAt": report.created_at.isoformat(),
            }

    @router.post("/reports", status_code=201)
    async def submit_report(body: ReportBody, request: Request):
        reporter_id = getattr(request.state, "user_id", None)
        if not reporter_id:
            raise HTTPException(status_code=401, detail="Sign in first.")
        if not await report_limiter.check(client_key(request)):
            raise HTTPException(
                status_code=429,
                detail="Too many reports. Please wait before sending another.",
            )
        db_reporter_id = UUID(reporter_id)
        if db_reporter_id == body.reported_user_id:
            raise HTTPException(status_code=422, detail="You cannot report yourself.")
        request_id, ip_hash = await audit_coordinates(request, session_factory)

        async with session_factory() as session:
            async with session.begin():
                target = await session.get(User, body.reported_user_id)
                if target is None or target.state in {
                    AccountState.MERGED.value,
                    AccountState.DELETED.value,
                }:
                    raise HTTPException(status_code=404, detail="No such player.")

                game = await session.get(GameRecord, body.game_id) if body.game_id else None
                if body.game_id and game is None:
                    raise HTTPException(status_code=422, detail="No such game context.")
                turn = await session.get(TurnRecord, body.turn_id) if body.turn_id else None
                if body.turn_id and turn is None:
                    raise HTTPException(status_code=422, detail="No such turn context.")
                if turn is not None and game is not None and turn.game_id != game.id:
                    raise HTTPException(
                        status_code=422,
                        detail="The turn does not belong to that game.",
                    )
                retained_messages: list[RoomMessage] = []
                if body.message_ids:
                    now = datetime.now(timezone.utc)
                    found = (
                        await session.scalars(
                            select(RoomMessage).where(
                                RoomMessage.id.in_(body.message_ids),
                                RoomMessage.expires_at > now,
                            )
                        )
                    ).all()
                    by_id = {message.id: message for message in found}
                    if set(by_id) != set(body.message_ids):
                        raise HTTPException(
                            status_code=422,
                            detail="One or more selected messages are unavailable.",
                        )
                    retained_messages = [
                        by_id[message_id] for message_id in body.message_ids
                    ]
                    # A lobby line was said to every lobby that was open, so
                    # it has no room to agree on and no recipient list to
                    # check the reporter against. It is public by
                    # construction, which is the answer to both questions -
                    # but it is one conversation, not any room's, so the two
                    # are never cited together.
                    lobby_lines = [
                        message
                        for message in retained_messages
                        if message.audience == "lobby"
                    ]
                    if lobby_lines and len(lobby_lines) != len(retained_messages):
                        raise HTTPException(
                            status_code=422,
                            detail="Lobby and room messages cannot be mixed in one report.",
                        )
                    if not lobby_lines and len(
                        {message.room_instance_id for message in retained_messages}
                    ) != 1:
                        raise HTTPException(
                            status_code=422,
                            detail="Selected messages must come from one room instance.",
                        )
                    for message in retained_messages:
                        if message.sender_user_id != target.id:
                            raise HTTPException(
                                status_code=422,
                                detail="Evidence must be authored by the reported player.",
                            )
                        if (
                            message.audience != "lobby"
                            and reporter_id not in message.audience_user_ids
                        ):
                            raise HTTPException(
                                status_code=403,
                                detail="You cannot select a message you did not receive.",
                            )
                        if game is not None and message.game_id != game.id:
                            raise HTTPException(
                                status_code=422,
                                detail="Selected message does not belong to that game.",
                            )
                        if turn is not None and message.turn_id != turn.id:
                            raise HTTPException(
                                status_code=422,
                                detail="Selected message does not belong to that turn.",
                            )

                    # Attach existing history context when all evidence agrees.
                    # Live or abandoned games remain valid evidence even though
                    # their runtime UUID has no game-history row yet.
                    selected_game_ids = {
                        message.game_id
                        for message in retained_messages
                        if message.game_id
                    }
                    if game is None and len(selected_game_ids) == 1:
                        game = await session.get(
                            GameRecord, next(iter(selected_game_ids))
                        )
                    selected_turn_ids = {
                        message.turn_id
                        for message in retained_messages
                        if message.turn_id
                    }
                    if turn is None and len(selected_turn_ids) == 1:
                        turn = await session.get(
                            TurnRecord, next(iter(selected_turn_ids))
                        )
                # The rate limiter bounds how many reports one client may
                # send; this bounds how many times the same person may be
                # reported by the same reporter, which is the noise a queue
                # actually drowns in. Same rule as content reports.
                already_open = await session.scalar(
                    select(PlayerReport.id).where(
                        PlayerReport.reporter_user_id == db_reporter_id,
                        PlayerReport.reported_user_id == target.id,
                        PlayerReport.status == ReportStatus.PENDING.value,
                    )
                )
                if already_open is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "You have already reported this player, and a "
                            "moderator has not reviewed it yet."
                        ),
                    )

                game_id = game.id if game is not None else (turn.game_id if turn else None)
                # What was said around the cited lines, in the one place they
                # came from. Chosen by the server, like the socket path's
                # evidence, so nothing about it has to be checked. Nothing
                # cited means no place to look.
                context_messages: list[RoomMessage] = []
                if retained_messages:
                    context_messages = await context_around(
                        session,
                        cited=retained_messages,
                        reporter_user_id=db_reporter_id,
                        room_instance_id=(
                            None
                            if retained_messages[0].audience == "lobby"
                            else retained_messages[0].room_instance_id
                        ),
                    )
                # Everything above this line is the router proving what a
                # client told it. The writing is shared with the socket path,
                # which has nothing to prove because it resolved the target and
                # picked the evidence itself.
                report = record_player_report(
                    session,
                    reporter_user_id=db_reporter_id,
                    reported_user_id=target.id,
                    game_id=game_id,
                    turn_id=turn.id if turn else None,
                    reason=body.reason.value,
                    details=body.details,
                    messages=list(retained_messages),
                    context_messages=context_messages,
                    context_snapshot=body.context_snapshot,
                    request_id=request_id,
                    ip_hash=ip_hash,
                )
                try:
                    await session.flush()
                except IntegrityError as error:
                    # Two submissions in the same instant both passed the check
                    # above; the partial unique index is what really decides,
                    # and the loser is told what a slower duplicate is told.
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "You have already reported this player, and a "
                            "moderator has not reviewed it yet."
                        ),
                    ) from error
            return {
                "id": str(report.id),
                "status": report.status,
                "createdAt": report.created_at.isoformat(),
            }

    @router.get("/moderation/reports")
    async def list_reports(
        request: Request,
        status: ReportStatus | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        async with session_factory() as session:
            await _reviewer(session, request)
            statement = select(PlayerReport).options(
                selectinload(PlayerReport.message_evidence)
            )
            if status is not None:
                statement = statement.where(PlayerReport.status == status.value)
            reports = (
                await session.scalars(
                    statement.order_by(PlayerReport.created_at.asc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            player_context = await _reported_player_context(session, list(reports))
            return {
                "reports": [
                    _report_payload(report, player_context) for report in reports
                ]
            }

    @router.post("/moderation/reports/{report_id}/remove-avatar")
    async def remove_reported_avatar(report_id: UUID, request: Request):
        """Take down the picture a report is about, and block re-upload.

        Reached through the report rather than the account (R-MOD-02): the
        moderator acts on the case in front of them and never has to hold an
        account id to do it. The block is what makes the removal stick - a
        re-upload a minute later would otherwise be the same picture back.
        """
        async with session_factory() as session:
            actor = await _reviewer(session, request)
            report = await session.get(PlayerReport, report_id)
        if report is None or report.reported_user_id is None:
            raise HTTPException(status_code=404, detail="No such report.")
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        removed = await remove_avatar(
            session_factory,
            user_id=report.reported_user_id,
            actor_id=actor.id,
            by_moderator=True,
            report_id=report.id,
            request_id=request_id,
            ip_hash=ip_hash,
        )
        if on_avatar_changed is not None:
            await on_avatar_changed(str(report.reported_user_id), None)
        return {"ok": True, "removed": removed}

    @router.get("/moderation/prompt-content-reports")
    async def list_prompt_content_reports(
        request: Request,
        status: ReportStatus | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        async with session_factory() as session:
            await _reviewer(session, request)
            statement = select(PromptContentReport)
            if status is not None:
                statement = statement.where(PromptContentReport.status == status.value)
            reports = (
                await session.scalars(
                    statement.order_by(PromptContentReport.created_at.asc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return {
                "reports": [
                    _prompt_content_report_payload(report) for report in reports
                ]
            }

    @router.patch("/moderation/reports/{report_id}")
    async def review_report(report_id: UUID, body: ReportReviewBody, request: Request):
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            async with session.begin():
                reviewer = await _reviewer(session, request)
                report = await session.scalar(
                    select(PlayerReport)
                    .where(PlayerReport.id == report_id)
                    .options(selectinload(PlayerReport.message_evidence))
                    .with_for_update()
                )
                if report is None:
                    raise HTTPException(status_code=404, detail="No such report.")
                if report.status != ReportStatus.PENDING.value:
                    raise HTTPException(
                        status_code=409, detail="This report was already reviewed."
                    )
                report.status = body.status
                report.reviewed_by_user_id = reviewer.id
                report.resolution_note = body.note
                report.reviewed_at = now
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type=f"report.{body.status}",
                        actor_user_id=reviewer.id,
                        target_user_id=report.reported_user_id,
                        target_type=AuditTargetType.USER.value,
                        target_id=str(report.reported_user_id),
                        request_id=request_id,
                        ip_hash=ip_hash,
                        details={"report_id": str(report.id)},
                    )
                )
                await session.flush()
                await session.refresh(report)
                await session.refresh(report, attribute_names=["message_evidence"])
            return _report_payload(report)

    @router.patch("/moderation/prompt-content-reports/{report_id}")
    async def review_prompt_content_report(
        report_id: UUID,
        body: PromptContentReviewBody,
        request: Request,
    ):
        if body.status == ReportStatus.RESOLVED.value and body.moderation_state is None:
            raise HTTPException(
                status_code=422,
                detail="Resolved content reports require a moderation state.",
            )
        if body.status == ReportStatus.DISMISSED.value and body.moderation_state:
            raise HTTPException(
                status_code=422,
                detail="Dismissed reports cannot change content moderation state.",
            )
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            async with session.begin():
                reviewer = await _reviewer(session, request)
                report = await session.scalar(
                    select(PromptContentReport)
                    .where(PromptContentReport.id == report_id)
                    .with_for_update()
                )
                if report is None:
                    raise HTTPException(status_code=404, detail="No such report.")
                if report.status != ReportStatus.PENDING.value:
                    raise HTTPException(
                        status_code=409, detail="This report was already reviewed."
                    )

                if body.status == ReportStatus.RESOLVED.value:
                    if report.target_type == "prompt":
                        target = (
                            await session.get(PromptVersion, report.prompt_version_id)
                            if report.prompt_version_id
                            else None
                        )
                    else:
                        target = (
                            await session.get(PromptList, report.prompt_list_id)
                            if report.prompt_list_id
                            else None
                        )
                    if target is None:
                        raise HTTPException(
                            status_code=409,
                            detail="The reported content has already been deleted.",
                        )
                    target.moderation_state = body.moderation_state
                    target.moderated_by_user_id = reviewer.id
                    target.moderated_at = now
                    # Telling somebody their content was hidden is the least
                    # the review owes them, and it is the second use the
                    # address was collected for.
                    if body.moderation_state == PromptContentModerationState.HIDDEN.value:
                        owner = (
                            await session.get(User, report.reported_owner_user_id)
                            if report.reported_owner_user_id
                            else None
                        )
                        if owner and owner.email and owner.email_verified_at:
                            queue_email(
                                session,
                                to_address=owner.email,
                                template=EmailTemplate.CONTENT_HIDDEN,
                                payload={
                                    "displayName": owner.display_name,
                                    "what": (
                                        "A prompt you shared"
                                        if report.prompt_version_id
                                        else "A prompt list you shared"
                                    ),
                                },
                                user_id=owner.id,
                                now=now,
                            )

                report.status = body.status
                report.reviewed_by_user_id = reviewer.id
                report.resolution_note = body.note
                report.resolution_moderation_state = (
                    body.moderation_state
                    if body.status == ReportStatus.RESOLVED.value
                    else None
                )
                report.reviewed_at = now
                content_target_type, content_target_id = _content_target(
                    report.prompt_list_id, report.prompt_version_id
                )
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type=f"prompt_content_report.{body.status}",
                        actor_user_id=reviewer.id,
                        target_user_id=report.reported_owner_user_id,
                        target_type=content_target_type,
                        target_id=content_target_id,
                        request_id=request_id,
                        ip_hash=ip_hash,
                        details={
                            "report_id": str(report.id),
                            "target_type": report.target_type,
                            "prompt_list_id": (
                                str(report.prompt_list_id)
                                if report.prompt_list_id
                                else None
                            ),
                            "prompt_version_id": (
                                str(report.prompt_version_id)
                                if report.prompt_version_id
                                else None
                            ),
                            "moderation_state": report.resolution_moderation_state,
                        },
                    )
                )
                await session.flush()
                await session.refresh(report)
            return _prompt_content_report_payload(report)


    async def _attach_and_resolve_report(
        session: AsyncSession,
        *,
        report_id: UUID,
        target_id: UUID,
        reviewer: User,
        note: str,
        now: datetime,
        request_id,
        ip_hash,
    ) -> PlayerReport:
        """Lock the source report and decide it in the caller's transaction.

        A warning or suspension issued from a report is one decision, not
        two requests: if the consequence lands, the report is resolved with
        it, and a report another moderator already decided refuses the whole
        action - which is also what stops a retry from issuing the same
        consequence twice.
        """
        report = await session.scalar(
            select(PlayerReport)
            .where(PlayerReport.id == report_id)
            .with_for_update()
        )
        if report is None or report.reported_user_id != target_id:
            raise HTTPException(
                status_code=422, detail="That report is not about this player."
            )
        if report.status != ReportStatus.PENDING.value:
            raise HTTPException(
                status_code=409, detail="This report was already reviewed."
            )
        report.status = ReportStatus.RESOLVED.value
        report.reviewed_by_user_id = reviewer.id
        report.resolution_note = note
        report.reviewed_at = now
        session.add(
            AuditEvent(
                id=generate_uuid(),
                event_type="report.resolved",
                actor_user_id=reviewer.id,
                target_user_id=report.reported_user_id,
                target_type=AuditTargetType.USER.value,
                target_id=str(report.reported_user_id),
                request_id=request_id,
                ip_hash=ip_hash,
                details={"report_id": str(report.id)},
            )
        )
        return report

    @router.post("/moderation/bans", status_code=201)
    async def create_ban(body: BanBody, request: Request):
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        now = datetime.now(timezone.utc)
        if body.expires_at is not None and body.expires_at <= now:
            raise HTTPException(status_code=422, detail="expiresAt must be in the future.")

        async with session_factory() as session:
            async with session.begin():
                reviewer = await _reviewer(session, request)
                target = await session.scalar(
                    select(User).where(User.id == body.user_id).with_for_update()
                )
                if target is None or target.state in {
                    AccountState.MERGED.value,
                    AccountState.DELETED.value,
                }:
                    raise HTTPException(status_code=404, detail="No such player.")
                if target.id == reviewer.id:
                    raise HTTPException(status_code=422, detail="You cannot ban yourself.")
                if target.role == UserRole.ADMIN.value:
                    raise HTTPException(status_code=403, detail="Administrators cannot be banned.")
                if (
                    reviewer.role == UserRole.MODERATOR.value
                    and target.role != UserRole.USER.value
                ):
                    raise HTTPException(
                        status_code=403,
                        detail="Moderators cannot ban another moderator.",
                    )
                existing = await active_ban_for_user(session, target.id, now=now)
                if existing is not None:
                    raise HTTPException(
                        status_code=409, detail="That account is already suspended."
                    )
                source_report = None
                if body.report_id is not None:
                    source_report = await _attach_and_resolve_report(
                        session,
                        report_id=body.report_id,
                        target_id=target.id,
                        reviewer=reviewer,
                        note=body.reason,
                        now=now,
                        request_id=request_id,
                        ip_hash=ip_hash,
                    )
                ban = UserBan(
                    id=generate_uuid(),
                    user_id=target.id,
                    banned_by_user_id=reviewer.id,
                    reason=body.reason,
                    expires_at=body.expires_at,
                    created_at=now,
                    source_report_id=source_report.id if source_report else None,
                )
                session.add(ban)
                # Written here, in the transaction that creates the ban, so a
                # mail server that is down cannot undo a suspension and a
                # suspension cannot be issued without the notice being owed.
                if target.email and target.email_verified_at is not None:
                    queue_email(
                        session,
                        to_address=target.email,
                        template=EmailTemplate.ACCOUNT_BANNED,
                        payload={
                            "displayName": target.display_name,
                            "reason": body.reason,
                        },
                        user_id=target.id,
                        now=now,
                    )
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="ban.created",
                        actor_user_id=reviewer.id,
                        target_user_id=target.id,
                        target_type=AuditTargetType.USER.value,
                        target_id=str(target.id),
                        request_id=request_id,
                        ip_hash=ip_hash,
                        details={
                            "ban_id": str(ban.id),
                            "reason": body.reason,
                            "expires_at": (
                                body.expires_at.isoformat()
                                if body.expires_at is not None
                                else None
                            ),
                        },
                    )
                )
                await session.flush()
            payload = _ban_payload(ban, target.display_name)

        await revoke_all_sessions(session_factory, user_id=str(body.user_id), now=now)
        if on_user_banned is not None:
            await on_user_banned(str(body.user_id))
        return payload

    @router.get("/moderation/bans")
    async def list_bans(
        request: Request,
        active: bool | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            await _reviewer(session, request)
            statement = select(UserBan)
            if active is True:
                statement = statement.where(*active_ban_filter(now))
            elif active is False:
                statement = statement.where(
                    or_(
                        UserBan.is_active.is_(False),
                        UserBan.expires_at <= now,
                    )
                )
            bans = (
                await session.scalars(
                    statement.order_by(UserBan.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            user_ids = {ban.user_id for ban in bans if ban.user_id}
            names = (
                {
                    row.id: row.display_name
                    for row in (
                        await session.scalars(
                            select(User).where(User.id.in_(user_ids))
                        )
                    ).all()
                }
                if user_ids
                else {}
            )
            return {
                "bans": [
                    _ban_payload(ban, names.get(ban.user_id)) for ban in bans
                ]
            }

    @router.post("/moderation/bans/{ban_id}/revoke")
    async def revoke_ban(ban_id: UUID, body: BanRevokeBody, request: Request):
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            async with session.begin():
                reviewer = await _reviewer(session, request)
                ban = await session.scalar(
                    select(UserBan).where(UserBan.id == ban_id).with_for_update()
                )
                if ban is None:
                    raise HTTPException(status_code=404, detail="No such suspension.")
                if not ban.is_active:
                    raise HTTPException(
                        status_code=409, detail="This suspension was already revoked."
                    )
                ban.is_active = False
                ban.revoked_at = now
                ban.revoked_by_user_id = reviewer.id
                ban.revoke_reason = body.reason
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="ban.revoked",
                        actor_user_id=reviewer.id,
                        target_user_id=ban.user_id,
                        target_type=AuditTargetType.USER.value,
                        target_id=str(ban.user_id) if ban.user_id else None,
                        request_id=request_id,
                        ip_hash=ip_hash,
                        details={"ban_id": str(ban.id), "reason": body.reason},
                    )
                )
                await session.flush()
                subject = (
                    await session.get(User, ban.user_id) if ban.user_id else None
                )
            return _ban_payload(ban, subject.display_name if subject else None)

    @router.post("/moderation/warnings", status_code=201)
    async def create_warning(body: WarningBody, request: Request):
        """The step between dismissing a report and suspending the account.

        Nothing is restricted: the player is shown, once, what was reported
        and that a moderator looked. Same role boundaries as a suspension,
        because it is the same kind of judgement about a person.
        """
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        async with session_factory() as session:
            async with session.begin():
                reviewer = await _reviewer(session, request)
                target = await session.scalar(
                    select(User).where(User.id == body.user_id)
                )
                if target is None or target.state in {
                    AccountState.MERGED.value,
                    AccountState.DELETED.value,
                }:
                    raise HTTPException(status_code=404, detail="No such player.")
                if target.id == reviewer.id:
                    raise HTTPException(
                        status_code=422, detail="You cannot warn yourself."
                    )
                if target.role == UserRole.ADMIN.value:
                    raise HTTPException(
                        status_code=403, detail="Administrators cannot be warned."
                    )
                if (
                    reviewer.role == UserRole.MODERATOR.value
                    and target.role != UserRole.USER.value
                ):
                    raise HTTPException(
                        status_code=403,
                        detail="Moderators cannot warn another moderator.",
                    )
                source_report = None
                if body.report_id is not None:
                    source_report = await _attach_and_resolve_report(
                        session,
                        report_id=body.report_id,
                        target_id=target.id,
                        reviewer=reviewer,
                        note=body.reason,
                        now=datetime.now(timezone.utc),
                        request_id=request_id,
                        ip_hash=ip_hash,
                    )
                warning = UserWarning(
                    id=generate_uuid(),
                    user_id=target.id,
                    issued_by_user_id=reviewer.id,
                    reason=body.reason,
                    source_report_id=source_report.id if source_report else None,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(warning)
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="warning.issued",
                        actor_user_id=reviewer.id,
                        target_user_id=target.id,
                        target_type=AuditTargetType.USER.value,
                        target_id=str(target.id),
                        request_id=request_id,
                        ip_hash=ip_hash,
                        details={
                            "warning_id": str(warning.id),
                            "reason": body.reason,
                        },
                    )
                )
                await session.flush()
                payload = {
                    "id": str(warning.id),
                    "userId": str(target.id),
                    "reason": warning.reason,
                    "createdAt": warning.created_at.isoformat(),
                }
        # After the commit, so a socket can never announce a warning a
        # rolled-back transaction never created.
        if on_user_warned is not None:
            await on_user_warned(str(body.user_id))
        return payload

    @router.get("/warnings/pending")
    async def pending_warning(request: Request):
        """The caller's own oldest unacknowledged warning - the catch-up
        route for a player who was offline when it was issued. The payload is
        shared with the live socket push (`app/auth/warnings.py`)."""
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(status_code=401, detail="Sign in first.")
        return await pending_warning_payload(session_factory, user_id)

    @router.post("/warnings/{warning_id}/acknowledge")
    async def acknowledge_warning(warning_id: UUID, request: Request):
        """Recorded so a moderator can see the message actually landed."""
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(status_code=401, detail="Sign in first.")
        async with session_factory() as session:
            async with session.begin():
                warning = await session.scalar(
                    select(UserWarning)
                    .where(UserWarning.id == warning_id)
                    .with_for_update()
                )
                # Someone else's warning is not this caller's to see, or to
                # acknowledge away; answering 404 keeps its existence private.
                if warning is None or warning.user_id != UUID(user_id):
                    raise HTTPException(status_code=404, detail="No such warning.")
                if warning.acknowledged_at is None:
                    warning.acknowledged_at = datetime.now(timezone.utc)
            return {"ok": True}

    return router
