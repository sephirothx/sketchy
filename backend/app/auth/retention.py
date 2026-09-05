"""Bounded cleanup policy for stale anonymous account rows."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import async_engine, async_session_factory, init_db
from app.db.models import (
    AuditEvent,
    AuthSession,
    DataExport,
    GameParticipant,
    User,
    UserBan,
    generate_uuid,
)
from app.domain_values import AccountState
from app.services.prompt_reclaim import reclaim_retired_prompt_lists
from app.services.readiness import LoopHealth
from app.services.sweeps import (
    SweepBudget,
    SweepReport,
    delete_in_batches,
    sweep_budget_from_env,
)


logger = logging.getLogger(__name__)

# Hourly. The purge is batched, so a sweep is cheap when there is nothing to
# do and keeps up when there is; daily would let a bad afternoon sit until
# tomorrow.
DEFAULT_SWEEP_SECONDS = 3600.0

# How long a session row is kept after the moment every code path stops
# honouring it. Nothing reads an expired session - resolution rejects one
# outright - so this window exists only to keep a just-expired row available
# for diagnosis, and could defensibly be zero.
SESSION_GRACE_DAYS = 30

DEFAULT_UNUSED_RETENTION_DAYS = 30
DEFAULT_PLAYER_RETENTION_DAYS = 365
DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True)
class AnonymousRetentionResult:
    unused_accounts: int
    player_accounts: int
    applied: bool

    @property
    def total(self) -> int:
        return self.unused_accounts + self.player_accounts


async def purge_expired_auth_sessions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    grace_days: int = SESSION_GRACE_DAYS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    budget: SweepBudget | None = None,
) -> SweepReport:
    """Remove sessions that every code path has already stopped honouring.

    The condition is **expiry, not revocation**. A revoked but unexpired row
    still has work to do: a token revoked when a ban landed stays recognisable
    so its next request is not mistaken for a new cookieless guest, and
    rotation leaves a revoked predecessor behind on purpose.

    Sessions belonging to an account under an active suspension are kept
    whatever their age. A banned account cannot log in to make a new one, so
    that row is its only route to the export and deletion that R-BAN-04 keeps
    available - moderation must not erase privacy rights, and neither must
    retention. Once the suspension lapses the account can sign in again, and
    its dead rows become ordinary.
    """
    if grace_days < 0:
        raise ValueError("grace window cannot be negative")
    if batch_size < 1:
        raise ValueError("batch size must be positive")
    checked_at = now or datetime.now(timezone.utc)
    cutoff = checked_at - timedelta(days=grace_days)
    # A set, not a scalar: the selectable says so, and the is_not(None)
    # matters as much - a single NULL on the right of NOT IN makes the whole
    # predicate never true, which would silently purge nothing at all.
    protected = select(UserBan.user_id).where(
        UserBan.user_id.is_not(None),
        UserBan.is_active.is_(True),
        or_(
            UserBan.expires_at.is_(None),
            UserBan.expires_at > checked_at,
        ),
    )
    resolved = budget or sweep_budget_from_env()
    return await delete_in_batches(
        session_factory,
        name="auth_sessions",
        candidates=select(AuthSession.id)
        .where(
            AuthSession.expires_at <= cutoff,
            AuthSession.user_id.not_in(protected),
        )
        .order_by(AuthSession.expires_at, AuthSession.id),
        delete_for=lambda ids: delete(AuthSession).where(AuthSession.id.in_(ids)),
        budget=SweepBudget(
            rows=resolved.rows, batch=min(batch_size, resolved.batch), seconds=resolved.seconds
        ),
    )


async def purge_expired_data_exports(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    budget: SweepBudget | None = None,
) -> SweepReport:
    """Remove exports past the window their own row declares.

    Until now an expired export only went when its owner asked for another one
    or a worker happened to pick the job up again, so a document generated once
    and never collected outlived its seven days indefinitely - carrying the
    largest single non-blob value in the schema with it.
    """
    if batch_size < 1:
        raise ValueError("batch size must be positive")
    checked_at = now or datetime.now(timezone.utc)
    resolved = budget or sweep_budget_from_env()
    return await delete_in_batches(
        session_factory,
        name="data_exports",
        candidates=select(DataExport.id)
        .where(DataExport.expires_at <= checked_at)
        .order_by(DataExport.expires_at, DataExport.id),
        delete_for=lambda ids: delete(DataExport).where(DataExport.id.in_(ids)),
        budget=SweepBudget(
            rows=resolved.rows, batch=min(batch_size, resolved.batch), seconds=resolved.seconds
        ),
    )


def _tier_predicates(cutoff: datetime, *, with_history: bool):
    """What makes a guest a candidate for one tier, as the database evaluates it."""
    has_game = exists(
        select(GameParticipant.id).where(GameParticipant.user_id == User.id)
    )
    return (
        User.state == AccountState.ANONYMOUS.value,
        User.last_active_at < cutoff,
        has_game if with_history else ~has_game,
    )


async def _select_candidates(
    session: AsyncSession, cutoff: datetime, *, with_history: bool, limit: int, lock: bool
) -> list:
    """The oldest `limit` guests still eligible for a tier, oldest first.

    When `lock` is set the rows come back locked `FOR UPDATE SKIP LOCKED`:
    a guest a claim, a merge, a seat or a finished-game write is holding at
    this moment is left for a later sweep rather than waited for, and the
    ones returned cannot change under the delete that follows. A preview
    takes no lock: it has no delete to protect and must not stall gameplay.
    """
    if limit < 1:
        return []
    statement = (
        select(User.id)
        .where(*_tier_predicates(cutoff, with_history=with_history))
        .order_by(User.last_active_at, User.id)
        .limit(limit)
    )
    if lock:
        statement = statement.with_for_update(skip_locked=True)
    return list((await session.scalars(statement)).all())


async def _delete_candidates(
    session: AsyncSession, candidate_ids: list, cutoff: datetime, *, with_history: bool
) -> set:
    """Delete the candidates that still qualify, and say which ones went.

    The eligibility predicates are repeated on the delete itself, so even a
    row that was not locked (SQLite renders no lock) is only removed if it is
    still an unclaimed, unmerged, inactive guest of this tier at that moment.
    """
    if not candidate_ids:
        return set()
    result = await session.execute(
        delete(User)
        .where(User.id.in_(candidate_ids), *_tier_predicates(cutoff, with_history=with_history))
        .returning(User.id)
    )
    return set(result.scalars().all())


async def purge_stale_anonymous_accounts(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    unused_retention_days: int = DEFAULT_UNUSED_RETENTION_DAYS,
    player_retention_days: int = DEFAULT_PLAYER_RETENTION_DAYS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    apply: bool = False,
) -> AnonymousRetentionResult:
    """Find or remove one bounded batch according to explicit guest tiers.

    Selecting by id and then deleting by id alone is a race at READ
    COMMITTED (#608): a guest that registered, was merged, took a seat or
    had a game written between the two statements would be removed by a
    sweep that is only meant for guests nobody has touched. So a removal
    selects under `FOR UPDATE SKIP LOCKED` in ascending activity order -
    identities anything else is writing are skipped, not waited for - and
    the delete repeats every eligibility predicate and returns the ids it
    removed, which are what the counts and the audit row report. A preview
    only reads.
    """
    if unused_retention_days < 1 or player_retention_days < 1:
        raise ValueError("retention windows must be positive")
    if batch_size < 1:
        raise ValueError("batch size must be positive")
    checked_at = now or datetime.now(timezone.utc)
    unused_cutoff = checked_at - timedelta(days=unused_retention_days)
    player_cutoff = checked_at - timedelta(days=player_retention_days)

    async with session_factory() as session:
        async with session.begin():
            # Each tier is offered half the batch and whatever the other
            # cannot use, so a flood of never-played guests cannot starve
            # the guests-with-history tier of its sweep for ever (#550).
            share = batch_size // 2
            unused_ids = await _select_candidates(
                session, unused_cutoff, with_history=False, limit=batch_size, lock=apply
            )
            player_ids = await _select_candidates(
                session, player_cutoff, with_history=True, limit=batch_size, lock=apply
            )
            player_take = min(len(player_ids), max(share, batch_size - len(unused_ids)))
            unused_take = min(len(unused_ids), batch_size - player_take)
            unused_ids = unused_ids[:unused_take]
            player_ids = player_ids[:player_take]
            if not apply:
                return AnonymousRetentionResult(
                    unused_accounts=len(unused_ids),
                    player_accounts=len(player_ids),
                    applied=False,
                )

            unused_removed = await _delete_candidates(
                session, unused_ids, unused_cutoff, with_history=False
            )
            player_removed = await _delete_candidates(
                session, player_ids, player_cutoff, with_history=True
            )
            result = AnonymousRetentionResult(
                unused_accounts=len(unused_removed),
                player_accounts=len(player_removed),
                applied=True,
            )
            skipped = len(unused_ids) + len(player_ids) - result.total
            if skipped:
                logger.info(
                    "retention sweep: %d selected guests were no longer eligible "
                    "by the time of the delete and were kept",
                    skipped,
                )
            if result.total:
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="retention.anonymous_purge",
                        details={
                            "unused_accounts": result.unused_accounts,
                            "player_accounts": result.player_accounts,
                            "unused_retention_days": unused_retention_days,
                            "player_retention_days": player_retention_days,
                        },
                    )
                )
            return result


async def _run(args) -> AnonymousRetentionResult:
    try:
        await init_db()
        return await purge_stale_anonymous_accounts(
            async_session_factory,
            unused_retention_days=args.unused_days,
            player_retention_days=args.player_days,
            batch_size=args.batch_size,
            apply=args.apply,
        )
    finally:
        await async_engine.dispose()


def sweep_interval_seconds(environ: dict[str, str] | None = None) -> float:
    values = os.environ if environ is None else environ
    raw = values.get("RETENTION_SWEEP_SECONDS", "").strip()
    if not raw:
        return DEFAULT_SWEEP_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        return DEFAULT_SWEEP_SECONDS
    return seconds if seconds > 0 else DEFAULT_SWEEP_SECONDS


# When a sweep ran out of budget with work left, the loop comes back this
# soon instead of waiting a whole interval: a backlog is worked off in
# bounded steps rather than in one unbounded pass, and rather than never.
CATCH_UP_SECONDS = 5.0


@dataclass(frozen=True)
class Sweep:
    """One retention mechanism the loop runs: a name and a coroutine factory."""

    name: str
    run: Callable[..., Awaitable[object]]


def retention_sweeps() -> tuple[Sweep, ...]:
    """Every scheduled purge, in the order the loop runs them.

    Fault-isolated: one failing table skips nothing after it. Guests come
    last because their cascades are the heaviest; messages first because
    they are the fastest-growing table.
    """
    from app.auth.mail import purge_expired_outbox_entries
    from app.auth.rate_limit import cleanup_expired_rate_limit_buckets
    from app.auth.tokens import purge_expired_tokens
    from app.services.message_retention import purge_expired_room_messages
    from app.services.room_codes import purge_retired_room_codes
    from app.services.shutdown import purge_expired_shutdown_abandonments

    return (
        Sweep("room_messages", purge_expired_room_messages),
        Sweep("email_outbox", purge_expired_outbox_entries),
        Sweep("auth_tokens", purge_expired_tokens),
        Sweep("auth_sessions", purge_expired_auth_sessions),
        Sweep("data_exports", purge_expired_data_exports),
        Sweep("shutdown_abandonments", purge_expired_shutdown_abandonments),
        Sweep("auth_rate_limit_buckets", cleanup_expired_rate_limit_buckets),
        Sweep("room_code_reservations", purge_retired_room_codes),
        Sweep("retired_prompt_lists", reclaim_retired_prompt_lists),
        Sweep("anonymous_accounts", _purge_guests),
    )


async def _purge_guests(session_factory, *, budget: SweepBudget) -> AnonymousRetentionResult:
    return await purge_stale_anonymous_accounts(
        session_factory, batch_size=min(DEFAULT_BATCH_SIZE, budget.rows), apply=True
    )


def _describe(report: object) -> dict[str, object]:
    if isinstance(report, SweepReport):
        return report.as_dict()
    if isinstance(report, AnonymousRetentionResult):
        return {
            "rows": report.total,
            "unused_accounts": report.unused_accounts,
            "player_accounts": report.player_accounts,
            "exhausted": report.total >= DEFAULT_BATCH_SIZE,
        }
    if hasattr(report, "lists_examined"):
        return {"rows": report.lists_deleted, "revisions": report.revisions_deleted}
    return {"rows": int(report) if isinstance(report, int) else None}


async def run_retention_sweeps(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    sweeps: tuple[Sweep, ...] | None = None,
    budget: SweepBudget | None = None,
    health: LoopHealth | None = None,
) -> dict[str, dict[str, object]]:
    """Run every sweep once, each within the budget, none able to stop the rest.

    Returns each sweep's account of itself, which the loop keeps on its
    health record for the operations page. A sweep that raised is recorded
    as failed there and counted on the health, and the iteration as a whole
    is a failure; the sweeps after it still run.
    """
    resolved = budget or sweep_budget_from_env()
    reports: dict[str, dict[str, object]] = {}
    failed = False
    for sweep in sweeps or retention_sweeps():
        try:
            report = await sweep.run(session_factory, budget=resolved)
        except asyncio.CancelledError:
            raise
        except Exception:
            failed = True
            logger.exception("retention sweep %s failed", sweep.name)
            reports[sweep.name] = {"failed": True}
            continue
        described = _describe(report)
        reports[sweep.name] = described
        if described.get("rows"):
            logger.info(
                "retention sweep %s: %s",
                sweep.name,
                ", ".join(f"{key}={value}" for key, value in described.items()),
            )
    if health is not None:
        health.detail = {"sweeps": reports}
        if failed:
            health.record_failure()
        else:
            health.record_success()
    return reports


async def run_retention_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    interval_seconds: float | None = None,
    health: LoopHealth | None = None,
    catch_up_seconds: float = CATCH_UP_SECONDS,
) -> None:
    """Run every retention sweep for ever, surviving every failure but cancellation.

    Scheduled by the application rather than left to a command somebody has to
    remember: an unrun retention policy is not a policy, and the rows that
    accumulate without it are exactly the ones guest provisioning creates.
    The first pass runs as soon as the loop starts, so startup carries no
    unbounded purge of its own; a pass that spent a sweep's budget with work
    left comes back after `catch_up_seconds` rather than a whole interval.
    """
    interval = interval_seconds or sweep_interval_seconds()
    while True:
        try:
            reports = await run_retention_sweeps(session_factory, health=health)
            behind = any(report.get("exhausted") for report in reports.values())
        except asyncio.CancelledError:
            raise
        except Exception:
            # Only the machinery around the sweeps can raise here; each sweep
            # is already isolated and counted inside run_retention_sweeps.
            behind = False
            if health is not None:
                health.record_failure()
            logger.exception("retention sweep failed")
        await asyncio.sleep(min(interval, catch_up_seconds) if behind else interval)


def start_retention_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    health: LoopHealth | None = None,
) -> asyncio.Task[None]:
    return asyncio.create_task(run_retention_loop(session_factory, health=health))


async def stop_retention_loop(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview or apply one bounded anonymous-account retention batch."
    )
    parser.add_argument(
        "--unused-days", type=int, default=DEFAULT_UNUSED_RETENTION_DAYS
    )
    parser.add_argument(
        "--player-days", type=int, default=DEFAULT_PLAYER_RETENTION_DAYS
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--apply", action="store_true", help="Delete candidates; default is preview only."
    )
    args = parser.parse_args()
    result = asyncio.run(_run(args))
    action = "Removed" if result.applied else "Would remove"
    print(
        f"{action} {result.total} anonymous accounts "
        f"({result.unused_accounts} unused, {result.player_accounts} with history)."
    )


if __name__ == "__main__":
    main()
