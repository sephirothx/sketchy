"""A ceiling on how long an undecided bug report keeps its screenshot.

Every other retention window in the schema is over a whole row. This one is
over a single column, and it exists because the row must survive it: a bug
report is a record of a defect, and a defect does not stop being real because
nobody triaged it. What cannot stay is the picture. A screenshot is somebody's
screen at a moment they were playing - up to 2 MiB of it - and the policy that
governed it was "erased when the report is decided", which is a ceiling only
if somebody decides. A report nobody ever looks at held its pixels for ever
(#478, R-BUG-13).

So the picture expires on its own after `SCREENSHOT_MAX_AGE_DAYS`, and the
row says so. `expired` rather than `erased` because a reviewer opening a
still-pending report deserves the true reason: `erased` means a decision was
made and took the picture with it, `expired` means the clock ran out first.
Both are structural - a CHECK constraint forbids a payload on either - so no
later code path can put pixels back behind one of these statuses.

The metadata stays: content type, byte size, dimensions and the server's own
SHA-256. A reviewer is still told a picture existed and what shape it was,
which is what makes the ledger honest rather than merely empty.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AuditEvent, BugReport, generate_uuid
from app.domain_values import BugReportScreenshotStatus, ReportStatus
from app.services.sweeps import (
    SweepBudget,
    SweepReport,
    erase_in_batches,
    overdue_probe,
    sweep_budget_from_env,
)


logger = logging.getLogger(__name__)

# Ninety days. Long enough that a real triage backlog - a quiet month, a
# holiday, a queue nobody got to - never costs a reviewer the evidence, and
# short enough to be a ceiling rather than a gesture. It is the same window
# the shutdown abandonments keep, for the same reason: diagnostic value
# decays, personal exposure does not.
SCREENSHOT_MAX_AGE_DAYS = 90


def _eligible(cutoff: datetime):
    """An undecided report still holding pixels, past the ceiling.

    A decided report is not a candidate however old: deciding already erased
    its screenshot, and a row that reaches `erased` or `expired` holds nothing
    for this sweep to take. The predicate is shared by the candidate select
    and the overdue probe, so nothing exempt is ever counted as lateness.
    """
    return (
        BugReport.status == ReportStatus.PENDING.value,
        BugReport.screenshot_status == BugReportScreenshotStatus.READY.value,
        BugReport.created_at <= cutoff,
    )


async def expire_stale_bug_report_screenshots(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    max_age_days: int = SCREENSHOT_MAX_AGE_DAYS,
    budget: SweepBudget | None = None,
) -> SweepReport:
    """Drop the pixels of every report that has waited too long to be decided.

    An UPDATE rather than a DELETE, batched and budgeted like every other
    sweep. The payload column is set to NULL and the status to `expired` in
    the same statement, so the two can never disagree - and the CHECK would
    refuse the row if a later change tried to make them.

    One aggregate audit event per run, never one per report: what the ledger
    records is that personal content was erased and how much of it, not whose
    screen it was. R-BUG-10 keeps the per-report events for the two things a
    person did - filing and deciding - and this is neither.
    """
    if max_age_days < 1:
        raise ValueError("the screenshot ceiling must be at least a day")
    checked_at = now or datetime.now(timezone.utc)
    cutoff = checked_at - timedelta(days=max_age_days)
    report = await erase_in_batches(
        session_factory,
        name="bug_report_screenshots",
        candidates=select(BugReport.id)
        .where(*_eligible(cutoff))
        .order_by(BugReport.created_at, BugReport.id),
        erase_for=lambda ids: update(BugReport)
        .where(
            BugReport.id.in_(ids),
            # Repeated on the write itself: a report decided between the
            # select and this statement has already erased its own picture,
            # and must not be relabelled as one nobody looked at (#608).
            *_eligible(cutoff),
        )
        .values(
            screenshot_payload=None,
            screenshot_status=BugReportScreenshotStatus.EXPIRED.value,
        ),
        budget=budget or sweep_budget_from_env(),
        probe=overdue_probe(BugReport.created_at, *_eligible(cutoff)),
        # Measured past eligibility, not past filing: a report is late by how
        # long it has been over the ceiling, not by how old it is.
        now=cutoff,
    )
    if report.rows:
        logger.info(
            "retention: expired %d bug-report screenshots past %d days",
            report.rows,
            max_age_days,
        )
        async with session_factory() as session:
            async with session.begin():
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="retention.bug_report_screenshots_expired",
                        details={
                            "reports": report.rows,
                            "max_age_days": max_age_days,
                        },
                    )
                )
    return report
