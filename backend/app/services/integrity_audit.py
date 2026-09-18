"""The integrity checks, run on a schedule and reported rather than remembered (#894).

The database holds three kinds of value that nothing re-checked unless an
operator thought to: the stored drawings, the projections derived from facts,
and the invariants only the writers prove. Each is checked here a bounded
slice at a time, by a supervised loop off the request path, so silent
corruption or drift lasts at most one audit cycle - and a cycle is kept
shorter than backup retention, so the restore that repairs a damaged drawing
still exists when it is found.

Every check walks its table by keyset and keeps its place in `app_config`
(`integrity_audit.<check>`), so a restart resumes rather than starts over and
a cycle is a real pass over every row, not a sample that may never reach the
bad one:

- `drawings` - the stored-drawing walk of #610 (checksum, declared size and
  format, decodability), held to a byte and a time budget per pass;
- `drawing_projections` - `turn_drawings.reaction_count` and `hot_score`
  against the reaction rows;
- `user_stats` - each account's `user_stats_daily` rows against a rebuild from
  the facts, computed inside a transaction that is rolled back, so the check
  uses the rebuild's own logic and never repairs anything;
- `games` - every participant's ledger sum against `final_score`, and every
  turn's `guesser_count` against its eligible outcome rows;
- `alias_chains` - no merged identity points at another merged identity.

A check reports and does not repair: a mismatch is counted, logged, and
written as one `audit_events` row naming the check and the row id - never its
content - for an operator to read and act on with the rebuild commands.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
import contextlib
from dataclasses import dataclass, field
import json
import logging
import math
import os
import time
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.db.models import (
    AppConfig,
    AuditEvent,
    GameParticipant,
    GameRecord,
    IdentityAlias,
    ScoreEvent,
    TurnDrawing,
    TurnDrawingReaction,
    TurnParticipantOutcome,
    TurnRecord,
    User,
    UserStatsDaily,
    generate_uuid,
)
from app.domain_values import AccountState, AuditTargetType
from app.services.drawing_storage import DrawingCursor, verify_stored_drawings
from app.services.gallery_ranking import hot_score
from app.services.readiness import LoopHealth
from app.services.user_stats_projection import _rebuild_accounts

logger = logging.getLogger(__name__)

CHECKS = ("drawings", "drawing_projections", "user_stats", "games", "alias_chains")
# Which mismatches page: a drawing that no longer reads back is data lost
# until a restore; a projection that drifted is a rebuild away.
PAGING_CHECKS = frozenset({"drawings"})
CONFIG_PREFIX = "integrity_audit."
MISMATCH_EVENT = "integrity.mismatch"

DEFAULT_INTERVAL_SECONDS = 300.0
# What one pass may spend. The drawing walk reads payloads, so it has a byte
# budget as well; at 16 MiB every five minutes a day covers 4.5 GiB of
# drawings, about 150,000 at the sizes measured so far (#471), with each pass
# a few seconds of work.
DEFAULT_PASS_SECONDS = 10.0
DEFAULT_BYTE_BUDGET_MIB = 16
# How long a full cycle of each check is expected to take. A cycle that has
# run for twice this without completing is itself alerted on: an audit that
# never finishes bounds nothing.
DEFAULT_CYCLE_TARGET_SECONDS = 86_400.0
# Rows per slice, by check.
DRAWING_SLICE_ROWS = 100
PROJECTION_SLICE_ROWS = 500
ACCOUNT_SLICE_ROWS = 25
GAME_SLICE_ROWS = 100
HOT_SCORE_TOLERANCE = 1e-6


def _float_setting(environ: dict[str, str], name: str, default: float) -> float:
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class AuditBudget:
    """How much one pass may do, and how often passes run."""

    interval_seconds: float = DEFAULT_INTERVAL_SECONDS
    pass_seconds: float = DEFAULT_PASS_SECONDS
    byte_budget: int = DEFAULT_BYTE_BUDGET_MIB * 1024 * 1024
    cycle_target_seconds: float = DEFAULT_CYCLE_TARGET_SECONDS

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> AuditBudget:
        values = os.environ if environ is None else environ
        return cls(
            interval_seconds=_float_setting(values, "INTEGRITY_AUDIT_SECONDS", DEFAULT_INTERVAL_SECONDS),
            pass_seconds=_float_setting(values, "INTEGRITY_AUDIT_PASS_SECONDS", DEFAULT_PASS_SECONDS),
            byte_budget=int(
                _float_setting(values, "INTEGRITY_AUDIT_BYTE_BUDGET_MIB", DEFAULT_BYTE_BUDGET_MIB)
                * 1024
                * 1024
            ),
            cycle_target_seconds=_float_setting(
                values, "INTEGRITY_AUDIT_CYCLE_TARGET_SECONDS", DEFAULT_CYCLE_TARGET_SECONDS
            ),
        )


@dataclass
class CheckState:
    """Where one check is, persisted between passes and across restarts."""

    cursor: str | None = None
    cycle_started_at: float | None = None
    last_completed_at: float | None = None
    last_cycle_seconds: float | None = None

    def encode(self) -> str:
        return json.dumps(self.__dict__, sort_keys=True)

    @classmethod
    def decode(cls, value: str | None) -> CheckState:
        if not value:
            return cls()
        try:
            data = json.loads(value)
        except ValueError:
            return cls()
        return cls(**{key: data.get(key) for key in cls.__dataclass_fields__})


@dataclass
class Mismatch:
    check: str
    row_id: str
    kind: str
    target_type: str | None = None


@dataclass
class SliceResult:
    """What one slice of a check did."""

    rows: int = 0
    mismatches: list[Mismatch] = field(default_factory=list)
    cursor: str | None = None
    complete: bool = False
    bytes: int = 0


@dataclass
class CheckTotals:
    rows_verified: int = 0
    mismatches: int = 0


# --- the checks ---------------------------------------------------------------


async def _drawings_slice(
    session_factory: async_sessionmaker[AsyncSession], cursor: str | None, *, byte_budget: int
) -> SliceResult:
    verification = await verify_stored_drawings(
        session_factory,
        batch_size=DRAWING_SLICE_ROWS,
        byte_budget=max(1, byte_budget),
        cursor=DrawingCursor.parse(cursor) if cursor else None,
        max_rows=DRAWING_SLICE_ROWS,
    )
    result = SliceResult(
        rows=verification.checked,
        bytes=verification.bytes_checked,
        cursor=None if verification.cursor is None else str(verification.cursor),
        complete=verification.complete,
    )
    for kind in ("corrupt", "unreadable", "malformed", "mismatched"):
        for turn_id in getattr(verification, kind):
            result.mismatches.append(
                Mismatch("drawings", turn_id, kind, AuditTargetType.DRAWING.value)
            )
    return result


async def _drawing_projections_slice(session: AsyncSession, cursor: str | None) -> SliceResult:
    statement = (
        select(
            TurnDrawing.turn_id,
            TurnDrawing.reaction_count,
            TurnDrawing.hot_score,
            GameRecord.finished_at,
        )
        .join(GameRecord, GameRecord.id == TurnDrawing.game_id)
        .order_by(TurnDrawing.turn_id)
        .limit(PROJECTION_SLICE_ROWS)
    )
    if cursor:
        statement = statement.where(TurnDrawing.turn_id > UUID(cursor))
    rows = (await session.execute(statement)).all()
    if not rows:
        return SliceResult(complete=True)
    turn_ids = [row.turn_id for row in rows]
    counts = dict(
        (
            await session.execute(
                select(TurnDrawingReaction.turn_id, func.count())
                .where(TurnDrawingReaction.turn_id.in_(turn_ids))
                .group_by(TurnDrawingReaction.turn_id)
            )
        ).all()
    )
    result = SliceResult(rows=len(rows), cursor=str(turn_ids[-1]))
    for row in rows:
        actual = int(counts.get(row.turn_id, 0))
        if row.reaction_count != actual:
            result.mismatches.append(
                Mismatch("drawing_projections", str(row.turn_id), "reaction_count", AuditTargetType.DRAWING.value)
            )
        elif not math.isclose(
            row.hot_score, hot_score(actual, row.finished_at), abs_tol=HOT_SCORE_TOLERANCE
        ):
            result.mismatches.append(
                Mismatch("drawing_projections", str(row.turn_id), "hot_score", AuditTargetType.DRAWING.value)
            )
    result.complete = len(rows) < PROJECTION_SLICE_ROWS
    return result


def _daily_rows(rows) -> dict[tuple[UUID, object], tuple]:
    return {
        (row.user_id, row.stat_date): (
            row.games_played,
            row.games_won,
            row.total_score,
            row.turns_played,
            row.prompts_guessed,
            row.drawings_made,
            row.reactions_received,
        )
        for row in rows
    }


async def _user_stats_slice(
    session_factory: async_sessionmaker[AsyncSession], cursor: str | None
) -> SliceResult:
    """Each account's rows against a rebuild from facts, rolled back.

    The rebuild is the projection's own logic, so the check cannot disagree
    with the repair it would recommend; the transaction is rolled back
    whatever it finds, so the check repairs nothing. It locks the batch's
    `users` rows for the rebuild's duration, as the rebuild command does.
    """
    async with session_factory() as session:
        statement = (
            select(User.id)
            .where(User.state != AccountState.MERGED.value)
            .order_by(User.id)
            .limit(ACCOUNT_SLICE_ROWS)
        )
        if cursor:
            statement = statement.where(User.id > UUID(cursor))
        accounts = list((await session.scalars(statement)).all())
        if not accounts:
            return SliceResult(complete=True)
        try:
            stored = _daily_rows(
                (await session.scalars(select(UserStatsDaily).where(UserStatsDaily.user_id.in_(accounts)))).all()
            )
            await _rebuild_accounts(session, accounts)
            rebuilt = _daily_rows(
                (await session.scalars(select(UserStatsDaily).where(UserStatsDaily.user_id.in_(accounts)))).all()
            )
        finally:
            # Whatever it found: the rebuild is the yardstick, never a repair.
            await session.rollback()
    drifted = sorted(
        {key[0] for key in set(stored) | set(rebuilt) if stored.get(key) != rebuilt.get(key)}
    )
    return SliceResult(
        rows=len(accounts),
        cursor=str(accounts[-1]),
        complete=len(accounts) < ACCOUNT_SLICE_ROWS,
        mismatches=[
            Mismatch("user_stats", str(user_id), "user_stats_daily", AuditTargetType.USER.value)
            for user_id in drifted
        ],
    )


async def _games_slice(session: AsyncSession, cursor: str | None) -> SliceResult:
    statement = select(GameRecord.id, GameRecord.score_ledger_version).order_by(GameRecord.id).limit(GAME_SLICE_ROWS)
    if cursor:
        statement = statement.where(GameRecord.id > UUID(cursor))
    games = (await session.execute(statement)).all()
    if not games:
        return SliceResult(complete=True)
    game_ids = [game.id for game in games]
    result = SliceResult(rows=len(games), cursor=str(game_ids[-1]), complete=len(games) < GAME_SLICE_ROWS)

    # The ledger: every participant's events sum to their final score. Games
    # recorded before the ledger existed (version 0) carry no events to sum.
    ledgered = [game.id for game in games if game.score_ledger_version >= 1]
    if ledgered:
        sums = dict(
            (
                await session.execute(
                    select(ScoreEvent.participant_id, func.sum(ScoreEvent.points_delta))
                    .where(ScoreEvent.game_id.in_(ledgered))
                    .group_by(ScoreEvent.participant_id)
                )
            ).all()
        )
        for seat_id, game_id, final_score in (
            await session.execute(
                select(GameParticipant.id, GameParticipant.game_id, GameParticipant.final_score).where(
                    GameParticipant.game_id.in_(ledgered)
                )
            )
        ).all():
            if int(sums.get(seat_id) or 0) != final_score:
                result.mismatches.append(Mismatch("games", str(game_id), "ledger_sum"))

    # Guesser counts: a turn's count equals its eligible outcome rows,
    # wherever it has outcome rows at all (the writer's own rule).
    outcome_counts: dict[UUID, list[int]] = defaultdict(lambda: [0, 0])
    for turn_id, is_eligible in (
        await session.execute(
            select(TurnParticipantOutcome.turn_id, TurnParticipantOutcome.eligible)
            .join(TurnRecord, TurnRecord.id == TurnParticipantOutcome.turn_id)
            .where(TurnRecord.game_id.in_(game_ids))
        )
    ).all():
        counts = outcome_counts[turn_id]
        counts[0] += 1
        counts[1] += 1 if is_eligible else 0
    for turn_id, game_id, guesser_count in (
        await session.execute(
            select(TurnRecord.id, TurnRecord.game_id, TurnRecord.guesser_count).where(
                TurnRecord.game_id.in_(game_ids)
            )
        )
    ).all():
        counts = outcome_counts.get(turn_id)
        if counts is not None and counts[0] and counts[1] != guesser_count:
            result.mismatches.append(Mismatch("games", str(game_id), "guesser_count"))
    return result


async def _alias_chains_slice(session: AsyncSession, cursor: str | None) -> SliceResult:
    """No alias targets an identity that is itself merged away. Whole table
    each pass: it holds one row per guest ever merged, and the join is on
    its primary key."""
    target = aliased(IdentityAlias)
    chained = (
        await session.scalars(
            select(IdentityAlias.source_user_id).join(
                target, target.source_user_id == IdentityAlias.target_user_id
            )
        )
    ).all()
    rows = int(await session.scalar(select(func.count()).select_from(IdentityAlias)) or 0)
    return SliceResult(
        rows=rows,
        complete=True,
        mismatches=[
            Mismatch("alias_chains", str(source), "chained_alias", AuditTargetType.USER.value)
            for source in chained
        ],
    )


# --- the pass -----------------------------------------------------------------


class IntegrityAudit:
    """One process's audit: its per-check totals, and the pass that advances them."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        budget: AuditBudget | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._session_factory = session_factory
        self.budget = budget or AuditBudget.from_env()
        self._clock = clock
        self.totals: dict[str, CheckTotals] = {check: CheckTotals() for check in CHECKS}
        self.states: dict[str, CheckState] = {}
        self.failed: dict[str, bool] = {check: False for check in CHECKS}

    async def _load(self, check: str) -> CheckState:
        async with self._session_factory() as session:
            row = await session.get(AppConfig, CONFIG_PREFIX + check)
        return CheckState.decode(row.value if row is not None else None)

    async def _save(self, check: str, state: CheckState, mismatches: list[Mismatch]) -> None:
        """Progress and what it found, in one transaction: a restart never
        re-reports a slice it already recorded, nor skips one it did not."""
        async with self._session_factory() as session, session.begin():
            row = await session.get(AppConfig, CONFIG_PREFIX + check)
            if row is None:
                session.add(AppConfig(key=CONFIG_PREFIX + check, value=state.encode()))
            else:
                row.value = state.encode()
            for mismatch in mismatches:
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type=MISMATCH_EVENT,
                        actor_user_id=None,
                        target_type=mismatch.target_type,
                        target_id=mismatch.row_id if mismatch.target_type else None,
                        # Which check and which row; never the row's content.
                        details={"check": mismatch.check, "kind": mismatch.kind, "row": mismatch.row_id},
                    )
                )

    def _slice(self, check: str) -> Callable[[str | None, int], Awaitable[SliceResult]]:
        factory = self._session_factory

        async def with_session(run, cursor):
            async with factory() as session:
                return await run(session, cursor)

        return {
            "drawings": lambda cursor, budget: _drawings_slice(factory, cursor, byte_budget=budget),
            "drawing_projections": lambda cursor, _budget: with_session(_drawing_projections_slice, cursor),
            "user_stats": lambda cursor, _budget: _user_stats_slice(factory, cursor),
            "games": lambda cursor, _budget: with_session(_games_slice, cursor),
            "alias_chains": lambda cursor, _budget: with_session(_alias_chains_slice, cursor),
        }[check]

    async def run_check(self, check: str, *, deadline: float) -> None:
        """Advance one check by slices until its share of the pass is spent,
        or its cycle completes - a completed cycle waits for the next pass."""
        state = await self._load(check)
        now = self._clock()
        if state.cycle_started_at is None:
            state.cycle_started_at = now
        run = self._slice(check)
        bytes_left = self.budget.byte_budget
        while True:
            result = await run(state.cursor, bytes_left)
            bytes_left -= result.bytes
            totals = self.totals[check]
            totals.rows_verified += result.rows
            totals.mismatches += len(result.mismatches)
            for mismatch in result.mismatches:
                log = logger.error if check in PAGING_CHECKS else logger.warning
                log("integrity check %s: %s on %s", check, mismatch.kind, mismatch.row_id)
            state.cursor = result.cursor
            if result.complete:
                finished = self._clock()
                state.last_completed_at = finished
                state.last_cycle_seconds = round(finished - state.cycle_started_at, 3)
                state.cycle_started_at = None
                state.cursor = None
            await self._save(check, state, result.mismatches)
            self.states[check] = state
            if result.complete or time.monotonic() >= deadline or bytes_left <= 0:
                return

    async def run_pass(self, *, health: LoopHealth | None = None) -> dict[str, dict[str, object]]:
        """Every check, fault-isolated, each with an equal share of the pass."""
        share = self.budget.pass_seconds / len(CHECKS)
        for check in CHECKS:
            try:
                await self.run_check(check, deadline=time.monotonic() + share)
                self.failed[check] = False
            except asyncio.CancelledError:
                raise
            except Exception:
                self.failed[check] = True
                logger.exception("integrity check %s failed", check)
        report = self.report()
        if health is not None:
            health.detail["checks"] = report
            if any(self.failed.values()):
                health.record_failure()
            else:
                health.record_success()
        return report

    def report(self) -> dict[str, dict[str, object]]:
        now = self._clock()
        report: dict[str, dict[str, object]] = {}
        for check in CHECKS:
            state = self.states.get(check, CheckState())
            totals = self.totals[check]
            started = state.cycle_started_at
            report[check] = {
                "rows_verified_total": totals.rows_verified,
                "mismatches_total": totals.mismatches,
                "failed": self.failed[check],
                "cycle_age_seconds": 0.0 if started is None else round(max(0.0, now - started), 3),
                "cycle_target_seconds": self.budget.cycle_target_seconds,
                "last_completed_at": state.last_completed_at,
                "last_cycle_seconds": state.last_cycle_seconds,
                "pages": check in PAGING_CHECKS,
            }
        return report


async def run_integrity_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    health: LoopHealth | None = None,
    audit: IntegrityAudit | None = None,
) -> None:
    """Audit for ever, a pass per interval, surviving everything but cancellation."""
    audit = audit or IntegrityAudit(session_factory)
    while True:
        try:
            await audit.run_pass(health=health)
        except asyncio.CancelledError:
            raise
        except Exception:
            if health is not None:
                health.record_failure()
            logger.exception("integrity audit pass failed")
        await asyncio.sleep(audit.budget.interval_seconds)


def start_integrity_loop(
    session_factory: async_sessionmaker[AsyncSession], *, health: LoopHealth | None = None
) -> asyncio.Task[None]:
    return asyncio.create_task(run_integrity_loop(session_factory, health=health))


async def stop_integrity_loop(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _run_cli(passes: int) -> None:
    from app.db import init_db, maintenance_engine

    engine, factory = maintenance_engine()
    try:
        await init_db(engine)
        audit = IntegrityAudit(factory, budget=AuditBudget.from_env())
        for _ in range(passes):
            report = await audit.run_pass()
        for check, row in report.items():
            print(
                f"{check}: {row['rows_verified_total']} rows verified, "
                f"{row['mismatches_total']} mismatches"
                + (" (check failed; see the log)" if row["failed"] else "")
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run integrity-audit passes now, as the server's loop would, and print what they found."
    )
    parser.add_argument("--passes", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(_run_cli(max(1, args.passes)))


if __name__ == "__main__":
    main()
