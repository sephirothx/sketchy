"""Player-filed bug reports and the administrator queue that triages them.

Deliberately separate from `api/moderation.py`. A bug report is about the
software rather than about a person: it carries build and diagnostic data, its
audience is whoever operates the server, and mixing it into the safety queue
would put two different confidentiality regimes in front of the same reader.

The shape of everything else - bounded values, a rate limiter, an audit event
per action, one-way review with a required note - follows the prompt-content
report path exactly, because those decisions were right there and are right
here.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.audit import audit_coordinates
from app.auth.rate_limit import PersistentRateLimiter, client_key
from app.db.models import AuditEvent, BugReport, User, generate_uuid
from app.domain_values import (
    AuditTargetType,
    BugReportArea,
    BugReportScreenshotStatus,
    BugReportSeverity,
    ReportStatus,
    UserRole,
)
from app.rooms import RoomManager


MAX_SUMMARY = 200
MAX_DETAILS = 4_000
MAX_RESOLUTION_NOTE = 2_000
MAX_CLIENT_CONTEXT_BYTES = 32_768
MAX_SCREENSHOT_BYTES = 2_097_152
# What 2 MiB looks like once base64 has grown it by four thirds, plus padding.
# The body limit in `app/request_limits.py` is the memory guard; this is the
# correctness one, so an oversized image is refused before it is decoded rather
# than after.
MAX_SCREENSHOT_BASE64 = ((MAX_SCREENSHOT_BYTES + 2) // 3) * 4 + 8
# Long enough to see what led to the failure, short enough that a page looping
# an error cannot turn one report into a log shipment.
MAX_CLIENT_ERRORS = 20
MAX_CLIENT_ERROR_CHARS = 500

# What a screenshot is allowed to be, keyed by the bytes a real file starts
# with. The declared content type is a claim; this is the check.
_IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"RIFF", "image/webp"),
)


def _sniff_image(payload: bytes) -> str | None:
    """The real content type of `payload`, or None if it is not one we take.

    WebP needs both halves of its header checked: `RIFF` alone is a container
    that could be an audio file just as easily.
    """
    for magic, content_type in _IMAGE_MAGIC:
        if not payload.startswith(magic):
            continue
        if content_type == "image/webp":
            return "image/webp" if payload[8:12] == b"WEBP" else None
        return content_type
    return None


class BugReportBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    area: BugReportArea
    severity: BugReportSeverity
    summary: str = Field(min_length=1, max_length=MAX_SUMMARY)
    details: str = Field(min_length=1, max_length=MAX_DETAILS)
    # Everything the reporter's browser said about itself. Stored as supplied
    # evidence, never promoted to fact by having been written down.
    client_context: dict | None = Field(default=None, alias="clientContext")
    # Which room they believe they are in. Checked against the live room rather
    # than believed: the server records the seat it can actually see.
    room_code: str | None = Field(default=None, alias="roomCode", max_length=16)
    screenshot: str | None = Field(default=None, max_length=MAX_SCREENSHOT_BASE64)

    @field_validator("summary", "details")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("cannot be blank")
        return cleaned


class BugReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: Literal["resolved", "dismissed"]
    note: str = Field(min_length=1, max_length=MAX_RESOLUTION_NOTE)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("note cannot be blank")
        return cleaned


def _safe_route(value: object) -> str | None:
    """The path a report may keep, with everything after it removed.

    The client already sends `location.pathname` alone, but that is the client's
    promise rather than a fact. A query string is where invite codes and
    identifiers live, and a fragment is no better; the rule that a report never
    carries one has to hold against a client that is buggy or lying, so the cut
    is made here rather than trusted from over there.
    """
    if not isinstance(value, str):
        return None
    path = value.split("?", 1)[0].split("#", 1)[0].strip()
    return path[:255] or None


def _trim_client_context(context: dict | None) -> dict:
    """Bound the parts of the reporter's context that a loop could inflate.

    The error tail is trimmed rather than refused: a page erroring in a loop is
    itself worth knowing about, and rejecting the report would lose the one
    account of it anybody was going to file.
    """
    if not context:
        return {}
    trimmed = dict(context)
    # Stripped in the blob too, not only in the column lifted out of it: a
    # query string left in the JSON is just as much a leak as one in a column.
    if "route" in trimmed:
        trimmed["route"] = _safe_route(trimmed.get("route"))
    errors = trimmed.get("recentErrors")
    if isinstance(errors, list):
        trimmed["recentErrors"] = [
            {
                key: (
                    value[:MAX_CLIENT_ERROR_CHARS]
                    if isinstance(value, str)
                    else value
                )
                for key, value in entry.items()
            }
            if isinstance(entry, dict)
            else str(entry)[:MAX_CLIENT_ERROR_CHARS]
            for entry in errors[-MAX_CLIENT_ERRORS:]
        ]
    events = trimmed.get("recentSocketEvents")
    if isinstance(events, list):
        trimmed["recentSocketEvents"] = events[-MAX_CLIENT_ERRORS:]
    return trimmed


def _live_room_context(
    room_manager: RoomManager, user_id: str, room_code: str | None
) -> tuple[dict, str | None, UUID | None, UUID | None]:
    """What this server knows about the reporter's seat, right now.

    Found by walking the live rooms for this account rather than by trusting
    the code the client sent: a bug report is not a way to learn what is going
    on in a room you are not sitting in. The claimed code only decides which
    room to prefer when somebody is somehow in more than one.

    Returns the context blob plus the three columns lifted out of it, so a
    queue can be grouped by room and game without parsing JSON.
    """
    seated: list[tuple[object, object]] = []
    for room in list(room_manager.rooms.values()):
        player = room_manager.get_player_by_user_id(room, user_id)
        if player is not None:
            seated.append((room, player))
    if not seated:
        return {}, None, None, None

    room, player = next(
        ((r, p) for r, p in seated if r.code == room_code),
        seated[0],
    )

    context: dict = {
        "room": {
            "code": room.code,
            "state": room.state,
            "isPublic": room.is_public,
            "playerCount": len(room.players),
            "maxPlayers": room.max_players,
            "ageSeconds": round(time.time() - room.created_at),
            "persistent": room.persistent_room_id is not None,
        },
        "roomSettings": {
            "rounds": room.rounds,
            "drawingSeconds": room.drawing_seconds,
            "hintMode": room.hint_mode,
            "scoringMode": room.scoring_mode,
            "colorMode": room.color_mode,
            "promptLanguage": room.prompt_language,
            "customPromptsOnly": room.custom_prompts_only,
            "customPromptCount": len(room.custom_prompts),
            "allowedTools": list(room.allowed_tools),
            "spectatorsSeePrompt": room.spectators_see_prompt,
            "hideMaskedPrompt": room.hide_masked_prompt,
        },
        "seat": {
            "isHost": player.is_host,
            "isSpectator": player.is_spectator,
            "isAfk": player.is_afk,
            "connected": player.connected,
            "score": player.score,
        },
    }

    game = room.game
    game_id: UUID | None = None
    turn_id: UUID | None = None
    if game is not None:
        game_id = UUID(game.id)
        turn_id = UUID(game.current_turn_id) if game.current_turn_id else None
        # Never the prompt, in any form. A guesser filing a bug is still a
        # guesser, and a report they can read back is not a hint channel.
        context["game"] = {
            "id": game.id,
            "turnId": game.current_turn_id,
            "phase": game.phase.value,
            "roundNumber": game.round_number,
            "roundsTotal": game.rounds_total,
            "turnIndex": game.turn_index,
            "scoringMode": game.scoring_mode,
            "scoringVersion": game.scoring_version,
            "isDrawer": game.current_drawer == player.id,
            "hasGuessed": player.id in game.correct_guessers,
            "correctGuessers": len(game.correct_guessers),
            "playersInTurnOrder": len(game.turn_order),
        }
    return context, room.code, game_id, turn_id


def _report_payload(report: BugReport, *, reporter: User | None = None) -> dict:
    return {
        "id": str(report.id),
        "reporterUserId": (
            str(report.reporter_user_id) if report.reporter_user_id else None
        ),
        "reporter": (
            {
                "displayName": reporter.display_name,
                "registered": not reporter.is_anonymous,
                "createdAt": reporter.created_at.isoformat(),
            }
            if reporter is not None
            else None
        ),
        "area": report.area,
        "severity": report.severity,
        "summary": report.summary,
        "details": report.details,
        "buildSha": report.build_sha,
        "route": report.route,
        "roomCode": report.room_code,
        "gameId": str(report.game_id) if report.game_id else None,
        "turnId": str(report.turn_id) if report.turn_id else None,
        "clientContext": report.client_context,
        "serverContext": report.server_context,
        "screenshot": {
            "status": report.screenshot_status,
            "contentType": report.screenshot_content_type,
            "byteSize": report.screenshot_byte_size,
            "width": report.screenshot_width,
            "height": report.screenshot_height,
            "checksum": report.screenshot_checksum_sha256,
        },
        "status": report.status,
        "reviewedByUserId": (
            str(report.reviewed_by_user_id) if report.reviewed_by_user_id else None
        ),
        "resolutionNote": report.resolution_note,
        "createdAt": report.created_at.isoformat(),
        "updatedAt": report.updated_at.isoformat(),
        "reviewedAt": report.reviewed_at.isoformat() if report.reviewed_at else None,
    }


def create_bug_report_router(
    session_factory: async_sessionmaker[AsyncSession],
    room_manager: RoomManager,
) -> APIRouter:
    router = APIRouter()
    limiter = PersistentRateLimiter(
        session_factory, scope="bug-report-submit", limit=5, window_seconds=3600
    )

    async def require_admin(request: Request) -> User:
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(status_code=401, detail="Sign in first.")
        async with session_factory() as session:
            user = await session.get(User, UUID(user_id))
        if user is None or user.role != UserRole.ADMIN.value:
            # 404 rather than 403, the same answer `api/operations.py` gives:
            # whether this deployment triages bugs in-app is not something an
            # ordinary player needs to learn.
            raise HTTPException(status_code=404, detail="Not found.")
        return user

    def _decode_screenshot(encoded: str | None) -> tuple[bytes, str, str] | None:
        """Validated bytes, content type and digest for an attached screenshot.

        Every property is re-derived here. The client says how big its picture
        is and what format it is in; none of that decides anything, because a
        client that is wrong about it is exactly the client filing bug reports.
        """
        if not encoded:
            return None
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise HTTPException(
                status_code=422, detail="The screenshot could not be read."
            ) from error
        if not payload:
            return None
        if len(payload) > MAX_SCREENSHOT_BYTES:
            raise HTTPException(
                status_code=422,
                detail="That screenshot is too large. The limit is 2 MB.",
            )
        content_type = _sniff_image(payload)
        if content_type is None:
            raise HTTPException(
                status_code=422, detail="A screenshot must be a PNG or WebP image."
            )
        return payload, content_type, hashlib.sha256(payload).hexdigest()

    @router.post("/api/bug-reports", status_code=201)
    async def submit_bug_report(body: BugReportBody, request: Request):
        reporter_id = getattr(request.state, "user_id", None)
        if not reporter_id:
            # Guests hold an account too, so this only refuses somebody with no
            # identity at all - and a bug nobody can be asked about helps least.
            raise HTTPException(status_code=401, detail="Sign in first.")
        if not await limiter.check(client_key(request)):
            raise HTTPException(
                status_code=429,
                detail="Too many bug reports. Please wait before sending another.",
            )

        client_context = _trim_client_context(body.client_context)
        if len(json.dumps(client_context).encode()) > MAX_CLIENT_CONTEXT_BYTES:
            raise HTTPException(
                status_code=422, detail="That report carries too much context."
            )

        screenshot = _decode_screenshot(body.screenshot)
        server_context, room_code, game_id, turn_id = _live_room_context(
            room_manager, reporter_id, body.room_code
        )
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        db_reporter_id = UUID(reporter_id)

        # The client's clock against this server's, because "it happened at
        # 09:41" is worth nothing if the two disagree by an hour.
        reported_at = client_context.get("clientTime")
        if isinstance(reported_at, str):
            try:
                skew = (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(reported_at.replace("Z", "+00:00"))
                ).total_seconds()
                server_context["clockSkewSeconds"] = round(skew, 1)
            except ValueError:
                server_context["clockSkewSeconds"] = None

        async with session_factory() as session:
            async with session.begin():
                reporter = await session.get(User, db_reporter_id)
                if reporter is not None:
                    server_context["account"] = {
                        "registered": not reporter.is_anonymous,
                        "role": reporter.role,
                        "createdAt": reporter.created_at.isoformat(),
                    }
                report = BugReport(
                    id=generate_uuid(),
                    reporter_user_id=db_reporter_id,
                    area=body.area.value,
                    severity=body.severity.value,
                    summary=body.summary,
                    details=body.details,
                    build_sha=(
                        str(client_context.get("buildSha"))[:64]
                        if client_context.get("buildSha")
                        else None
                    ),
                    route=_safe_route(client_context.get("route")),
                    room_code=room_code,
                    game_id=game_id,
                    turn_id=turn_id,
                    client_context=client_context,
                    server_context=server_context,
                )
                if screenshot is not None:
                    payload, content_type, checksum = screenshot
                    report.screenshot_status = BugReportScreenshotStatus.READY.value
                    report.screenshot_payload = payload
                    report.screenshot_content_type = content_type
                    report.screenshot_byte_size = len(payload)
                    report.screenshot_checksum_sha256 = checksum
                    width = client_context.get("screenshotWidth")
                    height = client_context.get("screenshotHeight")
                    report.screenshot_width = width if isinstance(width, int) else None
                    report.screenshot_height = (
                        height if isinstance(height, int) else None
                    )
                session.add(report)
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="bug_report.submitted",
                        actor_user_id=db_reporter_id,
                        target_type=AuditTargetType.BUG_REPORT.value,
                        target_id=str(report.id),
                        request_id=request_id,
                        ip_hash=ip_hash,
                        # Ids and bounded values only. The ledger is append-only
                        # and readable by administrators; the report's own text
                        # and context stay in the report.
                        details={
                            "report_id": str(report.id),
                            "area": report.area,
                            "severity": report.severity,
                            "has_screenshot": screenshot is not None,
                            "build_sha": report.build_sha,
                        },
                    )
                )
                await session.flush()
                return {
                    "id": str(report.id),
                    "status": report.status,
                    "createdAt": report.created_at.isoformat(),
                }

    @router.get("/api/admin/bug-reports")
    async def list_bug_reports(
        request: Request,
        status: str | None = Query(default=None),
    ):
        await require_admin(request)
        if status is not None and status not in {s.value for s in ReportStatus}:
            raise HTTPException(status_code=422, detail="Unknown status.")
        async with session_factory() as session:
            query = select(BugReport).order_by(BugReport.created_at.desc())
            if status is not None:
                query = query.where(BugReport.status == status)
            reports = list((await session.scalars(query.limit(200))).all())
            # Names resolved on read rather than stored, so a deleted account
            # reads as gone instead of leaving a copy of itself behind here.
            reporter_ids = {r.reporter_user_id for r in reports if r.reporter_user_id}
            reporters: dict[UUID, User] = {}
            if reporter_ids:
                reporters = {
                    user.id: user
                    for user in (
                        await session.scalars(
                            select(User).where(User.id.in_(reporter_ids))
                        )
                    ).all()
                }
            return {
                "reports": [
                    _report_payload(
                        report,
                        reporter=reporters.get(report.reporter_user_id)
                        if report.reporter_user_id
                        else None,
                    )
                    for report in reports
                ]
            }

    @router.get("/api/admin/bug-reports/{report_id}/screenshot")
    async def bug_report_screenshot(report_id: UUID, request: Request):
        await require_admin(request)
        async with session_factory() as session:
            report = await session.get(BugReport, report_id)
        if (
            report is None
            or report.screenshot_status != BugReportScreenshotStatus.READY.value
            or report.screenshot_payload is None
        ):
            raise HTTPException(status_code=404, detail="No screenshot.")
        return Response(
            content=report.screenshot_payload,
            media_type=report.screenshot_content_type or "application/octet-stream",
            # Somebody's screen, held only as long as the report is open. It has
            # no business in a shared cache or on disk.
            headers={"Cache-Control": "private, no-store"},
        )

    @router.patch("/api/admin/bug-reports/{report_id}")
    async def review_bug_report(
        report_id: UUID, body: BugReviewBody, request: Request
    ):
        reviewer = await require_admin(request)
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        async with session_factory() as session:
            async with session.begin():
                report = await session.get(BugReport, report_id)
                if report is None:
                    raise HTTPException(status_code=404, detail="Not found.")
                if report.status != ReportStatus.PENDING.value:
                    # One decision per report. A record that can be quietly
                    # rewritten is not a record.
                    raise HTTPException(
                        status_code=409, detail="That report has already been decided."
                    )
                report.status = body.status
                report.resolution_note = body.note
                report.reviewed_by_user_id = reviewer.id
                report.reviewed_at = datetime.now(timezone.utc)
                # Deciding drops the picture in the same transaction that
                # records the decision, so the two can never disagree.
                if report.screenshot_status == BugReportScreenshotStatus.READY.value:
                    report.screenshot_payload = None
                    report.screenshot_status = BugReportScreenshotStatus.ERASED.value
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type=f"bug_report.{body.status}",
                        actor_user_id=reviewer.id,
                        target_type=AuditTargetType.BUG_REPORT.value,
                        target_id=str(report.id),
                        request_id=request_id,
                        ip_hash=ip_hash,
                        details={"report_id": str(report.id), "status": body.status},
                    )
                )
                await session.flush()
                await session.refresh(report)
            return _report_payload(report)

    return router
