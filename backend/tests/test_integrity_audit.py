"""The integrity audit finds what it exists to find, and repairs nothing (#894)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import UUID

import pytest
from sqlalchemy import select, update

import app.services.integrity_audit as integrity
from app.db.models import AuditEvent, GameParticipant, GameRecord, TurnDrawing, TurnRecord, UserStatsDaily
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from app.services.integrity_audit import CHECKS, AuditBudget, IntegrityAudit
from app.services.readiness import LoopHealth

from tests.dbfixtures import create_test_db
from tests.test_drawing_reactions import record_game, registered

GENEROUS = AuditBudget(pass_seconds=30.0, byte_budget=64 * 1024 * 1024)


@pytest.fixture
async def world():
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    drawer = await registered(users, "Drawer")
    reactor = await registered(users, "Reactor")
    recorded = await record_game(
        history, drawer=drawer.id, reactor=reactor.id, reactions="default", visibility="public"
    )
    try:
        yield factory, recorded
    finally:
        await engine.dispose()


async def _audit_rows(factory) -> list[AuditEvent]:
    async with factory() as session:
        return list(
            (
                await session.scalars(
                    select(AuditEvent).where(AuditEvent.event_type == integrity.MISMATCH_EVENT)
                )
            ).all()
        )


async def test_a_clean_database_passes_every_check_and_completes_each_cycle(world):
    factory, _ = world
    health = LoopHealth("integrity_audit")
    report = await IntegrityAudit(factory, budget=GENEROUS).run_pass(health=health)
    assert {check: row["mismatches_total"] for check, row in report.items()} == dict.fromkeys(CHECKS, 0)
    assert all(not row["failed"] for row in report.values())
    assert report["drawings"]["rows_verified_total"] == 1
    assert all(row["last_completed_at"] is not None for row in report.values())
    assert health.detail["checks"] == report and health.consecutive_failures == 0
    assert await _audit_rows(factory) == []


async def test_a_corrupted_drawing_byte_is_reported_with_its_turn_and_nothing_else(world):
    factory, recorded = world
    async with factory() as session, session.begin():
        drawing = await session.get(TurnDrawing, UUID(recorded.turn_id))
        damaged = bytearray(drawing.payload)
        damaged[-1] ^= 0xFF
        drawing.payload = bytes(damaged)

    report = await IntegrityAudit(factory, budget=GENEROUS).run_pass()

    assert report["drawings"]["mismatches_total"] == 1
    [row] = await _audit_rows(factory)
    assert (row.target_type, row.target_id) == ("drawing", recorded.turn_id)
    assert row.details == {"check": "drawings", "kind": "corrupt", "row": recorded.turn_id}


async def test_a_hand_edited_reaction_count_is_reported(world):
    factory, recorded = world
    async with factory() as session, session.begin():
        await session.execute(
            update(TurnDrawing)
            .where(TurnDrawing.turn_id == UUID(recorded.turn_id))
            .values(reaction_count=TurnDrawing.reaction_count + 5)
        )
    report = await IntegrityAudit(factory, budget=GENEROUS).run_pass()
    assert report["drawing_projections"]["mismatches_total"] == 1
    [row] = await _audit_rows(factory)
    assert row.details["check"] == "drawing_projections" and row.details["kind"] == "reaction_count"


async def test_a_hand_edited_stats_row_is_reported_and_left_as_it_was(world):
    """Report, do not repair: the rebuild it compares against is rolled back."""
    factory, recorded = world
    drawer = UUID(recorded.drawer)
    async with factory() as session, session.begin():
        await session.execute(
            update(UserStatsDaily)
            .where(UserStatsDaily.user_id == drawer)
            .values(games_played=UserStatsDaily.games_played + 3)
        )
        before = (await session.scalars(select(UserStatsDaily.games_played).where(UserStatsDaily.user_id == drawer))).all()

    report = await IntegrityAudit(factory, budget=GENEROUS).run_pass()

    assert report["user_stats"]["mismatches_total"] == 1
    [row] = await _audit_rows(factory)
    assert (row.target_type, row.target_id) == ("user", str(drawer))
    async with factory() as session:
        after = (await session.scalars(select(UserStatsDaily.games_played).where(UserStatsDaily.user_id == drawer))).all()
    assert after == before, "the audit must not repair what it finds"


async def test_a_ledger_that_does_not_sum_and_a_wrong_guesser_count_are_reported(world):
    factory, recorded = world
    async with factory() as session, session.begin():
        # A ledgered game (version 1) with no scoring: every seat's events sum
        # to zero, as its final score does - until the score is edited.
        await session.execute(
            update(GameRecord).where(GameRecord.id == UUID(recorded.game_id)).values(score_ledger_version=1)
        )
        await session.execute(
            update(GameParticipant)
            .where(GameParticipant.game_id == UUID(recorded.game_id), GameParticipant.id == UUID(recorded.drawer_seat))
            .values(final_score=GameParticipant.final_score + 10)
        )
        await session.execute(
            update(TurnRecord).where(TurnRecord.id == UUID(recorded.turn_id)).values(guesser_count=TurnRecord.guesser_count + 1)
        )
    report = await IntegrityAudit(factory, budget=GENEROUS).run_pass()
    assert report["games"]["mismatches_total"] == 2
    kinds = sorted(row.details["kind"] for row in await _audit_rows(factory) if row.details["check"] == "games")
    assert kinds == ["guesser_count", "ledger_sum"]
    # And the edited score no longer matches the projection built from it,
    # which the stats check says on its own account.
    assert report["user_stats"]["mismatches_total"] == 1


async def test_a_pass_stops_at_its_byte_budget_and_a_restart_resumes_where_it_stopped(world, monkeypatch):
    factory, _ = world
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    for index in range(4):
        drawer = await registered(users, f"More{index}")
        reactor = await registered(users, f"Fan{index}")
        await record_game(history, drawer=drawer.id, reactor=reactor.id)
    monkeypatch.setattr(integrity, "DRAWING_SLICE_ROWS", 1)
    # Distinct instants, as PostgreSQL's microsecond clock gives them: SQLite's
    # CURRENT_TIMESTAMP default has one-second resolution and stores a form
    # the bound cursor does not compare equal to, which is a SQLite quirk of
    # the keyset and not what this test is about.
    async with factory() as session, session.begin():
        drawings = (await session.scalars(select(TurnDrawing).order_by(TurnDrawing.turn_id))).all()
        for index, drawing in enumerate(drawings):
            drawing.created_at = datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(minutes=index)

    tight = AuditBudget(pass_seconds=30.0, byte_budget=1)
    first = await IntegrityAudit(factory, budget=tight).run_pass()
    assert first["drawings"]["rows_verified_total"] == 1
    assert first["drawings"]["last_completed_at"] is None

    # A new process: the cursor comes from app_config, not from memory.
    resumed = IntegrityAudit(factory, budget=tight)
    for _ in range(4):
        report = await resumed.run_pass()
    assert report["drawings"]["rows_verified_total"] == 4, "the other four, none twice"
    # The walk learns it has reached the end on the next slice.
    report = await resumed.run_pass()
    assert report["drawings"]["rows_verified_total"] == 4
    assert report["drawings"]["last_completed_at"] is not None


async def test_one_check_failing_does_not_stop_the_others(world, monkeypatch):
    factory, _ = world

    async def broken(session, cursor):
        raise RuntimeError("this check is on fire")

    monkeypatch.setattr(integrity, "_games_slice", broken)
    health = LoopHealth("integrity_audit")
    report = await IntegrityAudit(factory, budget=GENEROUS).run_pass(health=health)
    assert report["games"]["failed"] is True
    assert report["alias_chains"]["failed"] is False and report["alias_chains"]["last_completed_at"] is not None
    assert health.consecutive_failures == 1


# --- a writer committing mid-slice (PostgreSQL's READ COMMITTED) --------------

ON_POSTGRESQL = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")


class _Interleaved:
    """A session that lets a writer commit before its `nth` statement.

    Under READ COMMITTED each statement sees whatever committed before it, so
    a slice that reads a projection and then its facts in two statements can
    compare one moment with the next - the window this opens on purpose.
    """

    def __init__(self, session, nth: int, writer) -> None:
        self._session = session
        self._nth = nth
        self._writer = writer
        self._calls = 0

    async def _before(self) -> None:
        self._calls += 1
        if self._calls == self._nth:
            await self._writer()

    async def execute(self, *args, **kwargs):
        await self._before()
        return await self._session.execute(*args, **kwargs)

    async def scalars(self, *args, **kwargs):
        await self._before()
        return await self._session.scalars(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)

    async def __aenter__(self):
        await self._session.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self._session.__aexit__(*exc)


async def _a_fan_reacts(factory, recorded, name: str) -> None:
    users = SqlAlchemyUserRepository(factory)
    fan = await registered(users, name)
    await SqlAlchemyGameHistoryRepository(factory).set_drawing_reaction(
        None, recorded.turn_id, requesting_user_id=fan.id, emoji="wow", from_gallery=True
    )


@pytest.mark.skipif(not ON_POSTGRESQL, reason="the interleaving is PostgreSQL's READ COMMITTED")
async def test_a_reaction_committing_mid_slice_is_not_drift_in_the_drawing_projection(world):
    """The writer sets the count and the row in one transaction; the check
    must read both from one moment, or it reports its own race as damage."""
    factory, recorded = world

    async def slice_with_a_reaction_between_its_reads():
        async with factory() as session:
            interleaved = _Interleaved(session, 2, lambda: _a_fan_reacts(factory, recorded, "Midslice"))
            return await integrity._drawing_projections_slice(interleaved, None)

    result = await slice_with_a_reaction_between_its_reads()
    assert result.rows == 1 and result.mismatches == []
    # And the reaction did land: the next slice counts it, still consistent.
    async with factory() as session:
        assert (await integrity._drawing_projections_slice(session, None)).mismatches == []


@pytest.mark.skipif(not ON_POSTGRESQL, reason="the interleaving is PostgreSQL's READ COMMITTED")
async def test_a_reaction_committing_between_the_stored_copy_and_the_rebuild_is_not_drift(world):
    """The stored rows and the rebuild's facts must be one moment's: a
    reaction landing between them is not a projection that drifted. A slice
    that cannot hold its snapshot against a writer steps back and is retried,
    rather than reported."""
    factory, recorded = world

    def interleaving_factory():
        # Statements: the batch of accounts, the stored copy, then the
        # rebuild; the writer commits just before the rebuild's first read.
        return _Interleaved(factory(), 3, lambda: _a_fan_reacts(factory, recorded, "Rebuildrace"))

    result = await integrity._user_stats_slice(interleaving_factory, None)
    # The reaction moved the drawer's row after the snapshot, so the rebuild
    # could not replace it: stepped back, nothing reported, cursor unmoved.
    assert (result.contended, result.mismatches, result.cursor) == (True, [], None)
    # Retried with nobody writing, the slice completes and still finds nothing.
    again = await integrity._user_stats_slice(factory, None)
    assert again.rows >= 2 and again.mismatches == []


async def test_a_contended_slice_is_retried_next_pass_not_counted(world, monkeypatch):
    factory, _ = world

    async def contended(session_factory, cursor):
        return integrity.SliceResult(cursor=cursor, contended=True)

    monkeypatch.setattr(integrity, "_user_stats_slice", contended)
    report = await IntegrityAudit(factory, budget=GENEROUS).run_pass()
    assert report["user_stats"]["rows_verified_total"] == 0
    assert report["user_stats"]["failed"] is False
    assert report["user_stats"]["last_completed_at"] is None
    assert report["games"]["last_completed_at"] is not None
