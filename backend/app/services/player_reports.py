"""Writing a player report, once its subject and evidence are settled.

Two callers reach this, and they differ in how much they have to prove rather
than in what they write.

`POST /api/reports` is given ids by a client and must check every one of them:
that the target exists, that the game and turn go together, that each selected
message was authored by the reported player and was actually received by the
reporter. That validation stays in the router, because it is the router's
problem.

The socket path is given none of that. It resolves the target from the live
room, takes the game and turn from the room's own state, and selects the
evidence itself - so the questions the router has to ask are answered by
construction. What is left in common is the writing, which is what lives here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditEvent,
    PlayerReport,
    PlayerReportMessageEvidence,
    RoomMessage,
    generate_uuid,
)
from app.domain_values import AuditTargetType


# A report is a complaint about something that just happened, so the evidence
# is the tail of the conversation rather than all of it. Bounded because the
# snapshot is stored for as long as the report is.
MAX_AUTOMATIC_EVIDENCE = 20


def record_player_report(
    session: AsyncSession,
    *,
    reporter_user_id: UUID,
    reported_user_id: UUID,
    game_id: UUID | None,
    turn_id: UUID | None,
    reason: str,
    details: str,
    messages: list[RoomMessage],
    context_snapshot: dict | None = None,
    request_id: str | None = None,
    ip_hash: str | None = None,
) -> PlayerReport:
    """Write the report, its evidence snapshot, and the audit entry.

    The evidence is copied rather than referenced: a message deleted or expired
    later must not take the reason for a moderator's decision with it.

    Returns the unflushed row. Its `created_at` comes from the database, so a
    caller that needs the timestamp has to flush before reading it - returning
    a snapshot from here would hand back a null.
    """
    report = PlayerReport(
        id=generate_uuid(),
        reporter_user_id=reporter_user_id,
        reported_user_id=reported_user_id,
        game_id=game_id,
        turn_id=turn_id,
        reason=reason,
        details=details,
        context_snapshot={
            "schemaVersion": 1,
            "submitted": context_snapshot or {},
        },
    )
    session.add(report)
    session.add_all(
        PlayerReportMessageEvidence(
            report_id=report.id,
            position=position,
            source_message_id=message.id,
            source_message_snapshot_id=message.id,
            game_id_snapshot=message.game_id,
            turn_id_snapshot=message.turn_id,
            sender_user_id=message.sender_user_id,
            sender_display_name_snapshot=message.sender_display_name_snapshot,
            sender_name_color_snapshot=message.sender_name_color_snapshot,
            sender_is_anonymous_snapshot=message.sender_is_anonymous_snapshot,
            message_kind=message.message_kind,
            audience=message.audience,
            near_miss_kind=message.near_miss_kind,
            text_snapshot=message.text,
            message_created_at=message.created_at,
        )
        for position, message in enumerate(messages)
    )
    session.add(
        AuditEvent(
            id=generate_uuid(),
            event_type="report.submitted",
            actor_user_id=reporter_user_id,
            target_user_id=reported_user_id,
            target_type=AuditTargetType.USER.value,
            target_id=str(reported_user_id),
            request_id=request_id,
            ip_hash=ip_hash,
            details={"report_id": str(report.id), "reason": reason},
        )
    )
    return report


async def evidence_from_live_room(
    session: AsyncSession,
    *,
    room_instance_id: UUID,
    reported_user_id: UUID,
    reporter_user_id: UUID,
    limit: int = MAX_AUTOMATIC_EVIDENCE,
    now: datetime | None = None,
) -> list[RoomMessage]:
    """The reported player's recent messages, as this reporter saw them.

    Chosen by the server rather than sent by the client, which answers two of
    the checks the REST path has to make by hand: the evidence is authored by
    the reported player because that is the filter, and the reporter received
    it because `audience_user_ids` is what the filter is against.
    """
    checked_at = now or datetime.now(timezone.utc)
    recent = (
        await session.scalars(
            select(RoomMessage)
            .where(
                RoomMessage.room_instance_id == room_instance_id,
                RoomMessage.sender_user_id == reported_user_id,
                RoomMessage.expires_at > checked_at,
            )
            .order_by(RoomMessage.created_at.desc())
            .limit(limit)
        )
    ).all()
    # Only what this reporter could actually see. A prompt-aware message they
    # were never shown is not theirs to submit.
    visible = [
        message
        for message in recent
        if str(reporter_user_id) in (message.audience_user_ids or [])
    ]
    # Back into the order they were said in, which is the order a moderator
    # needs to read them in.
    return list(reversed(visible))
