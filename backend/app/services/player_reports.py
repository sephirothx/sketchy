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

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditEvent,
    PlayerReport,
    PlayerReportMessageEvidence,
    RoomMessage,
    UserBlock,
    generate_uuid,
)
from app.domain_values import AuditTargetType


# A report is a complaint about something that just happened, so the evidence
# is the tail of the conversation rather than all of it. Bounded because the
# snapshot is stored for as long as the report is.
MAX_AUTOMATIC_EVIDENCE = 20

# What was said around the cited lines. Ten before and five after is enough
# to see what a line was answering and what it provoked; twelve hours is
# where "around" stops meaning anything - a room or the lobby has turned
# over by then. The bound is per report, so a report never copies more
# third-party text than this.
CONTEXT_LINES_BEFORE = 10
CONTEXT_LINES_AFTER = 5
CONTEXT_WINDOW = timedelta(hours=12)
# Rows are read in bulk and the audience rule applied here, as the evidence
# selector does, so a run of prompt-aware lines the reporter never received
# does not empty the window. Four times the bound is far past what a room
# says between two lines the reporter saw.
_CONTEXT_FETCH_FACTOR = 4


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
    context_messages: list[RoomMessage] | None = None,
    context_snapshot: dict | None = None,
    request_id: str | None = None,
    ip_hash: str | None = None,
) -> PlayerReport:
    """Write the report, its evidence snapshot, and the audit entry.

    The evidence is copied rather than referenced: a message deleted or expired
    later must not take the reason for a moderator's decision with it.

    `messages` are the cited lines and `context_messages` what was said around
    them; both are copied the same way, and the rows are positioned in the
    order the lines were said so every reader gets the conversation back
    rather than two lists to interleave.

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
    copied = sorted(
        [(message, "cited") for message in messages]
        + [(message, "context") for message in (context_messages or [])],
        key=lambda pair: (pair[0].created_at, pair[0].id),
    )
    session.add_all(
        PlayerReportMessageEvidence(
            report_id=report.id,
            position=position,
            role=role,
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
        for position, (message, role) in enumerate(copied)
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


async def context_around(
    session: AsyncSession,
    *,
    cited: list[RoomMessage],
    reporter_user_id: UUID,
    room_instance_id: UUID | None,
    now: datetime | None = None,
) -> list[RoomMessage]:
    """What was said around the cited lines, by anyone, as the reporter saw it.

    A line on its own is often unreadable - it answers something, or provokes
    something - so a report carries the conversation around it: up to
    `CONTEXT_LINES_BEFORE` lines before the latest cited one and
    `CONTEXT_LINES_AFTER` after, within `CONTEXT_WINDOW` of it, from the same
    room instance (or the lobby, when `room_instance_id` is None). With
    nothing cited the anchor is now, so a report about somebody who said
    nothing still shows what was going on.

    Chosen here rather than sent by a client, for the reason the evidence is:
    the reporter received every line copied, which is checked here rather
    than trusted. A room line records its audience, blocks already applied.
    A lobby line records none - it was said to every open lobby, and a list
    of who was around would be a directory (R-LCHAT-05) - so the block is
    re-applied here from the block table: a line by an author the reporter
    has muted was never delivered to them (R-LCHAT-03), and copying it into
    a report they can later export would hand them the very text the block
    withholds. The cited lines themselves are left out so nothing is copied
    twice, and the third-party lines this copies get the same tombstone on
    account deletion the cited ones do.
    """
    checked_at = now or datetime.now(timezone.utc)
    anchor = max((message.created_at for message in cited), default=checked_at)
    cited_ids = {message.id for message in cited}
    scope = (
        RoomMessage.audience == "lobby"
        if room_instance_id is None
        else RoomMessage.room_instance_id == room_instance_id
    )
    base = select(RoomMessage).where(scope, RoomMessage.expires_at > checked_at)
    if cited_ids:
        base = base.where(RoomMessage.id.not_in(cited_ids))
    muted_by_reporter: set[UUID] = set()
    if room_instance_id is None:
        muted_by_reporter = set(
            (
                await session.scalars(
                    select(UserBlock.blocked_user_id).where(
                        UserBlock.blocker_user_id == reporter_user_id
                    )
                )
            ).all()
        )

    def received(message: RoomMessage) -> bool:
        if message.audience == "lobby":
            return message.sender_user_id not in muted_by_reporter
        return str(reporter_user_id) in (message.audience_user_ids or [])

    before_rows = (
        await session.scalars(
            base.where(
                RoomMessage.created_at <= anchor,
                RoomMessage.created_at >= anchor - CONTEXT_WINDOW,
            )
            .order_by(RoomMessage.created_at.desc(), RoomMessage.id.desc())
            .limit(CONTEXT_LINES_BEFORE * _CONTEXT_FETCH_FACTOR)
        )
    ).all()
    after_rows = (
        await session.scalars(
            base.where(
                RoomMessage.created_at > anchor,
                RoomMessage.created_at <= anchor + CONTEXT_WINDOW,
            )
            .order_by(RoomMessage.created_at.asc(), RoomMessage.id.asc())
            .limit(CONTEXT_LINES_AFTER * _CONTEXT_FETCH_FACTOR)
        )
    ).all()
    before = [message for message in before_rows if received(message)][
        :CONTEXT_LINES_BEFORE
    ]
    after = [message for message in after_rows if received(message)][
        :CONTEXT_LINES_AFTER
    ]
    # Back into the order they were said in.
    return list(reversed(before)) + after
