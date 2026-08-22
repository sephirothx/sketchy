"""Player reports and role-gated moderation actions."""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.rate_limit import (
    PersistentRateLimiter,
    client_key,
    keyed_client_hash,
)
from app.auth.bans import active_ban_filter, active_ban_for_user
from app.auth.sessions import revoke_all_sessions
from app.db.models import (
    AuditEvent,
    GameRecord,
    PlayerReport,
    TurnRecord,
    User,
    UserBan,
    generate_uuid,
)
from app.domain_values import AccountState, ReportReason, ReportStatus, UserRole


MAX_REPORT_CONTEXT_BYTES = 32_768
MAX_REPORT_DETAILS = 2_000
MAX_RESOLUTION_NOTE = 2_000
OnUserBanned = Callable[[str], Awaitable[None]]


class ReportBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    reported_user_id: UUID = Field(alias="reportedUserId")
    game_id: UUID | None = Field(default=None, alias="gameId")
    turn_id: UUID | None = Field(default=None, alias="turnId")
    reason: ReportReason
    details: str = Field(min_length=1, max_length=MAX_REPORT_DETAILS)
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


class BanBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    user_id: UUID = Field(alias="userId")
    reason: str = Field(min_length=1, max_length=255)
    expires_at: datetime | None = Field(default=None, alias="expiresAt")

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


def _report_payload(report: PlayerReport) -> dict:
    return {
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
        "status": report.status,
        "reviewedByUserId": (
            str(report.reviewed_by_user_id) if report.reviewed_by_user_id else None
        ),
        "resolutionNote": report.resolution_note,
        "createdAt": report.created_at.isoformat(),
        "updatedAt": report.updated_at.isoformat(),
        "reviewedAt": report.reviewed_at.isoformat() if report.reviewed_at else None,
    }


def _ban_payload(ban: UserBan) -> dict:
    now = datetime.now(timezone.utc)
    effectively_active = ban.is_active and (
        ban.expires_at is None or ban.expires_at > now
    )
    return {
        "id": str(ban.id),
        "userId": str(ban.user_id) if ban.user_id else None,
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


def _request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "").strip()
    if supplied:
        try:
            return str(UUID(supplied))
        except ValueError:
            pass
    return str(generate_uuid())


async def _audit_coordinates(
    request: Request, session_factory: async_sessionmaker[AsyncSession]
) -> tuple[str, str]:
    return _request_id(request), await keyed_client_hash(
        session_factory, client_key(request)
    )


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
) -> APIRouter:
    router = APIRouter(prefix="/api")
    report_limiter = PersistentRateLimiter(
        session_factory, scope="report-submit", limit=10, window_seconds=3600
    )

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
        request_id, ip_hash = await _audit_coordinates(request, session_factory)

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
                game_id = game.id if game is not None else (turn.game_id if turn else None)
                report = PlayerReport(
                    id=generate_uuid(),
                    reporter_user_id=db_reporter_id,
                    reported_user_id=target.id,
                    game_id=game_id,
                    turn_id=turn.id if turn else None,
                    reason=body.reason.value,
                    details=body.details,
                    context_snapshot={
                        "schemaVersion": 1,
                        "submitted": body.context_snapshot,
                    },
                )
                session.add(report)
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="report.submitted",
                        actor_user_id=db_reporter_id,
                        target_user_id=target.id,
                        request_id=request_id,
                        ip_hash=ip_hash,
                        details={
                            "report_id": str(report.id),
                            "reason": body.reason.value,
                        },
                    )
                )
                await session.flush()
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
            statement = select(PlayerReport)
            if status is not None:
                statement = statement.where(PlayerReport.status == status.value)
            reports = (
                await session.scalars(
                    statement.order_by(PlayerReport.created_at.asc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return {"reports": [_report_payload(report) for report in reports]}

    @router.patch("/moderation/reports/{report_id}")
    async def review_report(report_id: UUID, body: ReportReviewBody, request: Request):
        request_id, ip_hash = await _audit_coordinates(request, session_factory)
        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            async with session.begin():
                reviewer = await _reviewer(session, request)
                report = await session.scalar(
                    select(PlayerReport)
                    .where(PlayerReport.id == report_id)
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
                        request_id=request_id,
                        ip_hash=ip_hash,
                        details={"report_id": str(report.id)},
                    )
                )
                await session.flush()
                await session.refresh(report)
            return _report_payload(report)

    @router.post("/moderation/bans", status_code=201)
    async def create_ban(body: BanBody, request: Request):
        request_id, ip_hash = await _audit_coordinates(request, session_factory)
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
                ban = UserBan(
                    id=generate_uuid(),
                    user_id=target.id,
                    banned_by_user_id=reviewer.id,
                    reason=body.reason,
                    expires_at=body.expires_at,
                    created_at=now,
                )
                session.add(ban)
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="ban.created",
                        actor_user_id=reviewer.id,
                        target_user_id=target.id,
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
            payload = _ban_payload(ban)

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
            return {"bans": [_ban_payload(ban) for ban in bans]}

    @router.post("/moderation/bans/{ban_id}/revoke")
    async def revoke_ban(ban_id: UUID, body: BanRevokeBody, request: Request):
        request_id, ip_hash = await _audit_coordinates(request, session_factory)
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
                        request_id=request_id,
                        ip_hash=ip_hash,
                        details={"ban_id": str(ban.id), "reason": body.reason},
                    )
                )
                await session.flush()
            return _ban_payload(ban)

    return router
