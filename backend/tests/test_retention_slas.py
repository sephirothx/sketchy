"""Retention that runs is not retention that complies (#478).

Every sweep was already bounded, scheduled and fault-isolated (#550), and all
of that is true of a sweep that removes five thousand rows an hour from a
table growing by six thousand. What these tests hold is the other half:
that each table states how long a row may remain past eligibility, that the
lateness it reports is measured over its own eligibility predicate so nothing
exempt is counted as a breach, and that a screenshot nobody ever decided
about has an end of its own.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

# `app.services.shutdown` and `app.handlers` import each other, so whichever
# is reached first has to be the package: importing the module directly, as
# `retention_sweeps()` does, fails from a test that imported neither.
import app.handlers  # noqa: F401
import app.auth.retention as retention
from app.api.operations import _retention_json, _retention_lines, retention_sweeps_from
from app.auth.retention import (
    Sweep,
    _describe,
    purge_expired_auth_sessions,
    run_retention_sweeps,
)
from app.db.models import (
    AuditEvent,
    AuthSession,
    BugReport,
    GamePromptSource,
    GameRecord,
    PromptList,
    PromptListRevision,
    RoomCodeReservation,
    User,
    UserBan,
    generate_uuid,
)
from app.domain_values import BugReportScreenshotStatus, ReportStatus
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.bug_report_retention import (
    SCREENSHOT_MAX_AGE_DAYS,
    expire_stale_bug_report_screenshots,
)
from app.services.prompt_reclaim import reclaim_retired_prompt_lists
from app.services.readiness import LoopHealth
from app.services.room_codes import purge_retired_room_codes
from app.services.sweeps import SweepBudget

from tests.dbfixtures import create_test_db

pytestmark = pytest.mark.asyncio

# A real PNG header, so the row is the shape the submit path would leave.
PNG = b"\x89PNG\r\n\x1a\n" + b"pixels" * 32


async def _report(factory, *, filed_at: datetime, status: str = "pending", picture: bool = True):
    report_id = generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(
                BugReport(
                    id=report_id,
                    area="drawing_and_canvas",
                    severity="minor",
                    summary="The brush skips",
                    details="Only on the second stroke.",
                    status=status,
                    reviewed_at=None if status == ReportStatus.PENDING.value else filed_at,
                    created_at=filed_at,
                    updated_at=filed_at,
                    screenshot_status=(
                        BugReportScreenshotStatus.READY.value
                        if picture
                        else BugReportScreenshotStatus.NONE.value
                    ),
                    screenshot_payload=PNG if picture else None,
                    screenshot_content_type="image/png" if picture else None,
                    screenshot_byte_size=len(PNG) if picture else None,
                    screenshot_width=800 if picture else None,
                    screenshot_height=600 if picture else None,
                    screenshot_checksum_sha256="a" * 64 if picture else None,
                )
            )
    return report_id


async def _load(factory, report_id) -> BugReport:
    async with factory() as session:
        report = await session.get(BugReport, report_id)
        assert report is not None
        return report


# --- the screenshot ceiling ------------------------------------------------


async def test_a_screenshot_nobody_decided_about_expires_and_leaves_its_report():
    """The one retained thing with no maximum age gets one (R-BUG-13)."""
    factory, engine = await create_test_db()
    try:
        now = datetime(2026, 9, 9, tzinfo=timezone.utc)
        stale = await _report(factory, filed_at=now - timedelta(days=91))
        fresh = await _report(factory, filed_at=now - timedelta(days=89))

        report = await expire_stale_bug_report_screenshots(factory, now=now)
        assert report == 1

        gone = await _load(factory, stale)
        assert gone.screenshot_payload is None
        assert gone.screenshot_status == BugReportScreenshotStatus.EXPIRED.value
        # The report is the record of a defect and survives its picture; so
        # does everything that says what the picture was.
        assert gone.status == ReportStatus.PENDING.value
        assert gone.summary == "The brush skips"
        assert gone.screenshot_byte_size == len(PNG)
        assert gone.screenshot_content_type == "image/png"
        assert (gone.screenshot_width, gone.screenshot_height) == (800, 600)
        assert gone.screenshot_checksum_sha256 == "a" * 64

        kept = await _load(factory, fresh)
        assert kept.screenshot_payload == PNG
        assert kept.screenshot_status == BugReportScreenshotStatus.READY.value
    finally:
        await engine.dispose()


async def test_expiring_says_expired_rather_than_claiming_a_decision():
    """`erased` on a pending report would put a decision nobody made on the
    record, and leave a reviewer no way to tell the two apart."""
    factory, engine = await create_test_db()
    try:
        now = datetime(2026, 9, 9, tzinfo=timezone.utc)
        await _report(factory, filed_at=now - timedelta(days=200))
        await expire_stale_bug_report_screenshots(factory, now=now)
        async with factory() as session:
            statuses = set(
                (await session.scalars(select(BugReport.screenshot_status))).all()
            )
        assert statuses == {BugReportScreenshotStatus.EXPIRED.value}
    finally:
        await engine.dispose()


async def test_a_decided_report_is_not_a_candidate_however_old():
    """Deciding already erased the picture; the sweep must not relabel that
    row as one nobody looked at."""
    factory, engine = await create_test_db()
    try:
        now = datetime(2026, 9, 9, tzinfo=timezone.utc)
        decided = await _report(
            factory,
            filed_at=now - timedelta(days=400),
            status=ReportStatus.RESOLVED.value,
            picture=False,
        )
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(BugReport)
                    .where(BugReport.id == decided)
                    .values(screenshot_status=BugReportScreenshotStatus.ERASED.value)
                )

        assert await expire_stale_bug_report_screenshots(factory, now=now) == 0
        row = await _load(factory, decided)
        assert row.screenshot_status == BugReportScreenshotStatus.ERASED.value
    finally:
        await engine.dispose()


async def test_the_database_refuses_pixels_behind_an_expired_status():
    """Structural, like R-BUG-08's erasure: no later code path can put the
    picture back and leave the row claiming it expired."""
    factory, engine = await create_test_db()
    try:
        now = datetime(2026, 9, 9, tzinfo=timezone.utc)
        report_id = await _report(factory, filed_at=now - timedelta(days=100))
        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    await session.execute(
                        update(BugReport)
                        .where(BugReport.id == report_id)
                        .values(
                            screenshot_status=BugReportScreenshotStatus.EXPIRED.value
                        )
                    )
    finally:
        await engine.dispose()


async def test_expiry_records_how_many_pictures_went_and_never_whose():
    """One aggregate row per run, not one per report: what the ledger owes is
    that personal content was erased, not who was on the screen."""
    factory, engine = await create_test_db()
    try:
        now = datetime(2026, 9, 9, tzinfo=timezone.utc)
        for _ in range(3):
            await _report(factory, filed_at=now - timedelta(days=120))

        assert await expire_stale_bug_report_screenshots(factory, now=now) == 3
        async with factory() as session:
            events = list(
                (
                    await session.scalars(
                        select(AuditEvent).where(
                            AuditEvent.event_type
                            == "retention.bug_report_screenshots_expired"
                        )
                    )
                ).all()
            )
        assert len(events) == 1
        assert events[0].details == {"reports": 3, "max_age_days": SCREENSHOT_MAX_AGE_DAYS}
        assert events[0].actor_user_id is None
        assert events[0].target_id is None

        # A run with nothing to do writes nothing at all.
        assert await expire_stale_bug_report_screenshots(factory, now=now) == 0
        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.event_type
                        == "retention.bug_report_screenshots_expired"
                    )
                )
                == 1
            )
    finally:
        await engine.dispose()


async def test_a_starved_screenshot_sweep_says_how_far_behind_it_is():
    """The budget is spent and the table is still overdue - which is the
    condition the SLA exists to name."""
    factory, engine = await create_test_db()
    try:
        now = datetime(2026, 9, 9, tzinfo=timezone.utc)
        for index in range(5):
            await _report(factory, filed_at=now - timedelta(days=120 + index))

        report = await expire_stale_bug_report_screenshots(
            factory, now=now, budget=SweepBudget(rows=2, batch=2, seconds=30)
        )
        assert report == 2 and report.exhausted
        assert report.backlog == 3
        # Oldest survivor filed 122 days ago, eligible at 90: 32 days late.
        assert report.oldest_overdue_seconds == pytest.approx(
            timedelta(days=32).total_seconds(), abs=1
        )
    finally:
        await engine.dispose()


# --- exemptions are not lateness -------------------------------------------


async def test_a_suspended_accounts_sessions_are_exempt_not_overdue():
    """R-BAN-04 keeps that row as the account's only route to export and
    deletion. Counting it as a missed deletion would make a long suspension
    read as retention failing, for ever."""
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        banned = await users.create_anonymous("Suspended")
        now = datetime(2026, 9, 9, tzinfo=timezone.utc)
        async with factory() as session:
            async with session.begin():
                session.add(
                    AuthSession(
                        id=generate_uuid(),
                        user_id=UUID(banned.id),
                        token_hash="h" * 64,
                        device_label="test",
                        created_at=now - timedelta(days=400),
                        expires_at=now - timedelta(days=365),
                        idle_expires_at=now - timedelta(days=365),
                    )
                )
                session.add(
                    UserBan(
                        id=generate_uuid(),
                        user_id=UUID(banned.id),
                        reason="spam",
                        expires_at=None,
                    )
                )

        report = await purge_expired_auth_sessions(factory, now=now)
        assert report == 0
        assert report.backlog == 0
        assert report.oldest_overdue_seconds == 0.0
        async with factory() as session:
            assert await session.scalar(select(func.count(AuthSession.id))) == 1
    finally:
        await engine.dispose()


async def test_a_permanent_room_code_is_exempt_not_overdue():
    """Codes of the removed persistent-room feature never re-enter the pool.
    A deployment full of them must not read as a sweep falling behind, even
    while the ephemeral side of the same table is starved."""
    factory, engine = await create_test_db()
    try:
        now = datetime(2026, 9, 9, tzinfo=timezone.utc)
        async with factory() as session:
            async with session.begin():
                session.add(RoomCodeReservation(code="KEEPME", kind="persistent"))
                session.add_all(
                    RoomCodeReservation(
                        code=f"OLD{index:03d}",
                        kind="ephemeral",
                        retired_until=now - timedelta(days=30 + index),
                    )
                    for index in range(3)
                )

        report = await purge_retired_room_codes(
            factory, now=now, budget=SweepBudget(rows=1, batch=1, seconds=30)
        )
        # One overdue ephemeral code went; the two left are the backlog, and
        # the permanent code is in neither number.
        assert report == 1 and report.backlog == 2
        async with factory() as session:
            kinds = list(
                (await session.scalars(select(RoomCodeReservation.kind))).all()
            )
        assert kinds.count("persistent") == 1

        rest = await purge_retired_room_codes(factory, now=now)
        assert rest == 2
        assert rest.backlog == 0 and rest.oldest_overdue_seconds == 0.0
    finally:
        await engine.dispose()


async def test_a_clean_table_reports_a_zero_rather_than_nothing():
    """An absent series is not less than its allowance - it is silence, and a
    rule written on `>` never fires on it."""
    factory, engine = await create_test_db()
    try:
        now = datetime(2026, 9, 9, tzinfo=timezone.utc)
        report = await purge_expired_auth_sessions(factory, now=now)
        assert report.oldest_overdue_seconds == 0.0
        assert report.backlog == 0
    finally:
        await engine.dispose()


# --- what the loop reports -------------------------------------------------


async def test_every_sweep_states_the_sla_it_is_held_to_and_what_it_exempts():
    named = {sweep.name: sweep for sweep in retention.retention_sweeps()}
    assert all(sweep.sla_seconds > 0 for sweep in named.values())
    # The two whose per-run ceiling is deliberately small work a backlog off
    # over several passes by design, so they are held to a day.
    assert named["anonymous_accounts"].sla_seconds == retention.HEAVY_SLA_SECONDS
    assert named["retired_prompt_lists"].sla_seconds == retention.HEAVY_SLA_SECONDS
    assert named["room_messages"].sla_seconds == retention.STANDARD_SLA_SECONDS
    # An SLA with unstated exceptions is unauditable, so the tables that keep
    # something for ever say what.
    for name in ("auth_sessions", "room_code_reservations", "retired_prompt_lists"):
        assert named[name].exempt


async def test_each_table_reports_its_own_run_its_own_sla_and_its_own_totals():
    factory, engine = await create_test_db()
    try:
        health = LoopHealth("retention_sweep")
        totals: dict[str, retention.SweepTotals] = {}
        reports = await run_retention_sweeps(
            factory, budget=SweepBudget(rows=50, batch=10), health=health, totals=totals
        )
        for name, sweep in {s.name: s for s in retention.retention_sweeps()}.items():
            assert reports[name]["sla_seconds"] == sweep.sla_seconds
            assert reports[name]["failed"] is False
            assert reports[name]["removed_total"] == 0
            assert reports[name]["failures_total"] == 0
        # Every table says how far behind it is - all of them, including the
        # reclaim, whose own shape is different but whose backlog is real.
        # The compliance question is answerable per table rather than only
        # for the loop as a whole.
        measured = [
            name
            for name, report in reports.items()
            if report.get("oldest_overdue_seconds") is not None
        ]
        assert set(measured) == set(reports)
        assert health.consecutive_failures == 0
    finally:
        await engine.dispose()


async def test_a_failing_table_is_named_recovers_and_keeps_its_running_total():
    """Fault isolation means nothing else will name it: the loop goes on
    looking intermittent while one table fails every hour."""
    factory, engine = await create_test_db()
    try:
        attempts = {"count": 0}

        async def flaky(session_factory, *, budget):
            attempts["count"] += 1
            if attempts["count"] <= 2:
                raise RuntimeError("this table is on fire")
            return await purge_expired_auth_sessions(session_factory, budget=budget)

        sweeps = (Sweep("auth_sessions", flaky),)
        totals: dict[str, retention.SweepTotals] = {}
        health = LoopHealth("retention_sweep")

        first = await run_retention_sweeps(
            factory, sweeps=sweeps, health=health, totals=totals
        )
        assert first["auth_sessions"]["failed"] is True
        assert first["auth_sessions"]["failures_total"] == 1
        row = _retention_json(first)[0]
        assert row["failed"] is True and row["breached"] is False

        second = await run_retention_sweeps(
            factory, sweeps=sweeps, health=health, totals=totals
        )
        assert second["auth_sessions"]["failures_total"] == 2
        assert health.consecutive_failures == 2 and health.last_success is None

        third = await run_retention_sweeps(
            factory, sweeps=sweeps, health=health, totals=totals
        )
        # Recovered: the run reports success, and the failures it survived are
        # still on the record, which is what separates "hiccupped once" from
        # "has been failing all night".
        assert third["auth_sessions"]["failed"] is False
        assert third["auth_sessions"]["failures_total"] == 2
        assert health.consecutive_failures == 0 and health.last_success is not None
    finally:
        await engine.dispose()


async def test_a_table_past_its_sla_is_logged_and_flagged_for_both_surfaces(caplog):
    factory, engine = await create_test_db()
    try:
        now = datetime(2026, 9, 9, tzinfo=timezone.utc)
        # Filed a year ago, eligible at ninety days: months past a six-hour
        # allowance, and starved by a budget of one row.
        for index in range(3):
            await _report(factory, filed_at=now - timedelta(days=365 + index))

        async def screenshots(session_factory, *, budget):
            return await expire_stale_bug_report_screenshots(
                session_factory, now=now, budget=SweepBudget(rows=1, batch=1, seconds=30)
            )

        with caplog.at_level("WARNING", logger="app.auth.retention"):
            reports = await run_retention_sweeps(
                factory, sweeps=(Sweep("bug_report_screenshots", screenshots),)
            )

        entry = reports["bug_report_screenshots"]
        assert entry["exhausted"] is True and entry["backlog"] == 2
        assert entry["oldest_overdue_seconds"] > entry["sla_seconds"]
        assert "past its SLA" in caplog.text

        row = _retention_json(reports)[0]
        assert row["breached"] is True and row["table"] == "bug_report_screenshots"

        lines = _retention_lines(reports)
        assert 'sketchy_retention_sweep_exhausted{table="bug_report_screenshots"} 1' in lines
        assert any(line.startswith("sketchy_retention_overdue_seconds{") for line in lines)
        assert any(line.startswith("sketchy_retention_sla_seconds{") for line in lines)
    finally:
        await engine.dispose()


async def test_the_scrape_reads_the_sweeps_off_whichever_loop_reported_them():
    health = LoopHealth("retention_sweep")
    health.detail = {
        "sweeps": {
            "room_messages": {
                "rows": 0,
                "oldest_overdue_seconds": 0.0,
                "backlog": 0,
                "sla_seconds": 21600.0,
                "failed": False,
                "exhausted": False,
                "seconds": 0.01,
                "removed_total": 7,
                "failures_total": 0,
            }
        }
    }
    loops = {"retention_sweep": {"running": True, **health.snapshot()}}
    assert set(retention_sweeps_from(loops)) == {"room_messages"}
    lines = _retention_lines(retention_sweeps_from(loops))
    assert 'sketchy_retention_overdue_seconds{table="room_messages"} 0.0' in lines
    assert 'sketchy_retention_rows_removed_total{table="room_messages"} 7' in lines
    # A loop with no sweeps on its record contributes nothing rather than
    # inventing an empty table.
    assert retention_sweeps_from({"mail_delivery": {"running": True}}) == {}


# --- the reclaim's own starvation -----------------------------------------


async def _retired_list(factory, *, retired_at: datetime, pinned: bool, name: str):
    """A retired list with one revision, optionally pinned by a finished game."""
    list_id, revision_id = generate_uuid(), generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(
                PromptList(
                    id=list_id,
                    slug=f"slug-{name}",
                    name=name,
                    language="en",
                    visibility="private",
                    deleted_at=retired_at,
                )
            )
            await session.flush()
            session.add(
                PromptListRevision(
                    id=revision_id,
                    prompt_list_id=list_id,
                    version=1,
                    language="en",
                    content_hash=f"hash-{name}",
                )
            )
            if pinned:
                game_id = generate_uuid()
                session.add(
                    GameRecord(
                        id=game_id,
                        room_name="Played it",
                        scoring_mode="default",
                        hint_mode="none",
                        drawing_seconds=60,
                        total_rounds=1,
                        player_count=1,
                        started_at=retired_at,
                        finished_at=retired_at,
                    )
                )
                await session.flush()
                session.add(
                    GamePromptSource(
                        game_id=game_id, prompt_list_revision_id=revision_id
                    )
                )
    return list_id


async def test_pinned_tombstones_cannot_monopolise_the_reclaim_batch():
    """A pin is a finished game's provenance, so it never lapses: the
    tombstone holding it is permanent. Selecting the oldest retired lists
    without excluding them means that once there are `limit` of them they are
    the oldest `limit` for ever, and no list retired afterwards is ever
    reached - the reclaim runs every hour, reports success, and collects
    nothing again."""
    factory, engine = await create_test_db()
    try:
        now = datetime(2026, 9, 9, tzinfo=timezone.utc)
        limit = 3
        for index in range(limit):
            await _retired_list(
                factory,
                retired_at=now - timedelta(days=100 + index),
                pinned=True,
                name=f"pinned-{index}",
            )
        newer = await _retired_list(
            factory, retired_at=now - timedelta(days=10), pinned=False, name="collectable"
        )

        result = await reclaim_retired_prompt_lists(factory, now=now, limit=limit)

        assert result.lists_deleted == 1, "the reclaimable list behind them is reached"
        async with factory() as session:
            assert await session.get(PromptList, newer) is None
            # The pinned tombstones are untouched: exempt, not collected.
            assert (
                await session.scalar(select(func.count(PromptList.id)))
                == limit
            )
    finally:
        await engine.dispose()


async def test_the_reclaim_measures_the_lists_it_could_still_collect():
    """Its backlog is over reclaimable lists only. Counting permanent
    tombstones would climb for ever with nothing wrong, and counting nothing
    at all leaves the one sweep whose starvation is unbounded unwatched."""
    factory, engine = await create_test_db()
    try:
        now = datetime(2026, 9, 9, tzinfo=timezone.utc)
        await _retired_list(
            factory, retired_at=now - timedelta(days=400), pinned=True, name="forever"
        )
        await _retired_list(
            factory, retired_at=now - timedelta(days=9), pinned=False, name="waiting"
        )

        result = await reclaim_retired_prompt_lists(
            factory, now=now, budget=SweepBudget(rows=1, batch=1, seconds=30)
        )
        described = _describe(result)
        assert described["backlog"] == 0, "what it collected is no longer a backlog"
        assert described["oldest_overdue_seconds"] == 0.0

        # With the reclaimable one still waiting, the age is measured past the
        # grace it is already over - and the permanent tombstone is in neither
        # number.
        await _retired_list(
            factory, retired_at=now - timedelta(days=9), pinned=False, name="waiting-2"
        )
        await _retired_list(
            factory, retired_at=now - timedelta(days=3), pinned=False, name="waiting-3"
        )
        starved = await reclaim_retired_prompt_lists(
            factory, now=now, limit=1, budget=SweepBudget(rows=1, batch=1, seconds=30)
        )
        described = _describe(starved)
        assert described["backlog"] == 1
        # Retired three days ago, collectable after a day's grace: two late.
        assert described["oldest_overdue_seconds"] == pytest.approx(
            timedelta(days=2).total_seconds(), abs=1
        )
    finally:
        await engine.dispose()


async def test_each_guest_tier_reports_its_own_lateness():
    """One number for both tiers would hide the starvation the halved batch
    exists to prevent: the never-played flood keeps the table's oldest row
    young while the tier with history quietly ages."""
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        now = datetime(2026, 9, 9, tzinfo=timezone.utc)
        from sqlalchemy import update as sql_update

        from app.db.models import GameParticipant, GameRecord

        played = await users.create_anonymous("Veteran")
        async with factory() as session:
            async with session.begin():
                game_id = generate_uuid()
                session.add(
                    GameRecord(
                        id=game_id,
                        room_name="Old",
                        scoring_mode="default",
                        hint_mode="none",
                        drawing_seconds=60,
                        total_rounds=1,
                        player_count=1,
                        started_at=now - timedelta(days=800),
                        finished_at=now - timedelta(days=800),
                    )
                )
                await session.flush()
                session.add(
                    GameParticipant(
                        id=generate_uuid(),
                        game_id=game_id,
                        user_id=UUID(played.id),
                        final_score=0,
                        final_rank=1,
                    )
                )
                await session.execute(
                    sql_update(User)
                    .where(User.id == UUID(played.id))
                    .values(last_active_at=now - timedelta(days=375))
                )

        measured = await retention._guest_lateness(
            factory,
            unused_cutoff=now - timedelta(days=retention.DEFAULT_UNUSED_RETENTION_DAYS),
            player_cutoff=now - timedelta(days=retention.DEFAULT_PLAYER_RETENTION_DAYS),
        )
        assert measured["unused_overdue_seconds"] == 0.0
        assert measured["player_overdue_seconds"] == pytest.approx(
            timedelta(days=10).total_seconds(), abs=1
        )
        assert measured["oldest_overdue_seconds"] == measured["player_overdue_seconds"]
        assert measured["backlog"] == 1
    finally:
        await engine.dispose()
