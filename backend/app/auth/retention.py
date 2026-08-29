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
                protected = (
                    select(UserBan.user_id)
                    .where(
                        UserBan.user_id.is_not(None),
                        UserBan.is_active.is_(True),
                        or_(
                            UserBan.expires_at.is_(None),
                            UserBan.expires_at > checked_at,
                        ),
                    )
                    .scalar_subquery()
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


async def purge_stale_anonymous_accounts(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    unused_retention_days: int = DEFAULT_UNUSED_RETENTION_DAYS,
    player_retention_days: int = DEFAULT_PLAYER_RETENTION_DAYS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    apply: bool = False,
) -> AnonymousRetentionResult:
    """Find or remove one bounded batch according to explicit guest tiers."""
    if unused_retention_days < 1 or player_retention_days < 1:
        raise ValueError("retention windows must be positive")
    if batch_size < 1:
        raise ValueError("batch size must be positive")
    checked_at = now or datetime.now(timezone.utc)
    unused_cutoff = checked_at - timedelta(days=unused_retention_days)
    player_cutoff = checked_at - timedelta(days=player_retention_days)
    has_game = exists(
        select(GameParticipant.id).where(GameParticipant.user_id == User.id)
    )

    async with session_factory() as session:
        async with session.begin():
            unused_ids = list(
                (
                    await session.scalars(
                        select(User.id)
                        .where(
                            User.state == AccountState.ANONYMOUS.value,
                            User.last_active_at < unused_cutoff,
                            ~has_game,
                        )
                        .order_by(User.last_active_at)
                        .limit(batch_size)
                    )
                ).all()
            )
            remaining = max(0, batch_size - len(unused_ids))
            player_ids = (
                list(
                    (
                        await session.scalars(
                            select(User.id)
                            .where(
                                User.state == AccountState.ANONYMOUS.value,
                                User.last_active_at < player_cutoff,
                                has_game,
                            )
                            .order_by(User.last_active_at)
                            .limit(remaining)
                        )
                    ).all()
                )
                if remaining
                else []
            )

            result = AnonymousRetentionResult(
                unused_accounts=len(unused_ids),
                player_accounts=len(player_ids),
                applied=apply,
            )
            if apply and result.total:
                await session.execute(
                    delete(User).where(User.id.in_((*unused_ids, *player_ids)))
                )
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
