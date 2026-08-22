"""Bounded cleanup policy for stale anonymous account rows."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import async_engine, async_session_factory, init_db
from app.db.models import AuditEvent, GameParticipant, User, generate_uuid
from app.domain_values import AccountState


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
