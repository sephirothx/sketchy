"""Bounded cleanup policy for stale anonymous account rows."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
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
) -> int:
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
    removed = 0
    while True:
        async with session_factory() as session:
            async with session.begin():
                # A set, not a scalar: the selectable says so, and the
                # is_not(None) matters as much - a single NULL on the right of
                # NOT IN makes the whole predicate never true, which would
                # silently purge nothing at all.
                protected = select(UserBan.user_id).where(
                    UserBan.user_id.is_not(None),
                    UserBan.is_active.is_(True),
                    or_(
                        UserBan.expires_at.is_(None),
                        UserBan.expires_at > checked_at,
                    ),
                )
                doomed = (
                    await session.scalars(
                        select(AuthSession.id)
                        .where(
                            AuthSession.expires_at <= cutoff,
                            AuthSession.user_id.not_in(protected),
                        )
                        .limit(batch_size)
                    )
                ).all()
                if doomed:
                    await session.execute(
                        delete(AuthSession).where(AuthSession.id.in_(doomed))
                    )
        removed += len(doomed)
        if len(doomed) < batch_size:
            return removed


async def purge_expired_data_exports(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Remove exports past the window their own row declares.

    Until now an expired export only went when its owner asked for another one
    or a worker happened to pick the job up again, so a document generated once
    and never collected outlived its seven days indefinitely - carrying the
    largest single non-blob value in the schema with it.
    """
    if batch_size < 1:
        raise ValueError("batch size must be positive")
    checked_at = now or datetime.now(timezone.utc)
    removed = 0
    while True:
        async with session_factory() as session:
            async with session.begin():
                doomed = (
                    await session.scalars(
                        select(DataExport.id)
                        .where(DataExport.expires_at <= checked_at)
                        .limit(batch_size)
                    )
                ).all()
                if doomed:
                    await session.execute(
                        delete(DataExport).where(DataExport.id.in_(doomed))
                    )
        removed += len(doomed)
        if len(doomed) < batch_size:
            return removed


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
            unused_ids = await _select_candidates(
                session, unused_cutoff, with_history=False, limit=batch_size, lock=apply
            )
            player_ids = await _select_candidates(
                session,
                player_cutoff,
                with_history=True,
                limit=batch_size - len(unused_ids),
                lock=apply,
            )
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


async def run_retention_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    interval_seconds: float | None = None,
    health: LoopHealth | None = None,
) -> None:
    """Purge stale guest rows for ever, surviving every failure but cancellation.

    Scheduled by the application rather than left to a command somebody has to
    remember: an unrun retention policy is not a policy, and the rows that
    accumulate without it are exactly the ones guest provisioning creates.
    """
    interval = interval_seconds or sweep_interval_seconds()
    while True:
        try:
            result = await purge_stale_anonymous_accounts(session_factory, apply=True)
            sessions = await purge_expired_auth_sessions(session_factory)
            exports = await purge_expired_data_exports(session_factory)
            # Retired prompt lists whose grace has passed: the revisions no
            # finished game pins, then the tombstone, then orphan content.
            await reclaim_retired_prompt_lists(session_factory)
            if health is not None:
                health.record_success()
            if sessions or exports:
                logger.info(
                    "retention sweep: removed %d expired sessions and %d "
                    "expired exports",
                    sessions,
                    exports,
                )
            if result.total:
                logger.info(
                    "retention sweep: removed %d anonymous accounts "
                    "(%d unused, %d with history)",
                    result.total,
                    result.unused_accounts,
                    result.player_accounts,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            # A sweep that raises must not take the loop down with it: the
            # next one is an hour away and the rows are still there. Counted
            # rather than only logged, so a sweep that has failed every time
            # since startup is visible without reading the log.
            if health is not None:
                health.record_failure()
            logger.exception("retention sweep failed")
        await asyncio.sleep(interval)


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
