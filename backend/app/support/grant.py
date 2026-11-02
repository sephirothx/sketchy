"""Audited command for a comp, or for repairing a provider-side mistake (#1473).

    python -m app.support.grant <username> --months 12 --admin <username> --reason "…"

Writes a `stub` purchase and an `audit_events` row naming the administrator.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import maintenance_engine
from app.db.models import AuditEvent, User, generate_uuid
from app.domain_values import (
    AccountState,
    AuditTargetType,
    SupportProvider,
    SupportPurchaseKind,
    UserRole,
)
from app.services.supporter import months_later, record_support_fact


class SupportGrantError(RuntimeError):
    """Raised when a grant cannot be made."""


async def _registered(session: AsyncSession, username: str) -> User:
    user = await session.scalar(
        select(User).where(
            func.lower(User.username) == username.strip().lower(),
            User.state == AccountState.REGISTERED.value,
        )
    )
    if user is None:
        raise SupportGrantError(f"no registered account called {username!r}")
    return user


async def grant_pass(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    username: str,
    admin: str,
    reason: str,
    months: int | None,
    now: datetime | None = None,
) -> None:
    """`months=None` is a lifetime pass."""
    if not reason.strip():
        raise SupportGrantError("an audit reason is required")
    if months is not None and months < 1:
        raise SupportGrantError("a grant lasts at least one month")
    start = now or datetime.now(timezone.utc)
    order = f"grant_{uuid4().hex}"
    async with session_factory() as session:
        async with session.begin():
            administrator = await _registered(session, admin)
            if administrator.role != UserRole.ADMIN.value:
                raise SupportGrantError(f"{admin!r} is not an administrator")
            user = await _registered(session, username)
            await record_support_fact(
                session,
                provider=SupportProvider.STUB.value,
                provider_event_id=order,
                provider_order_id=order,
                kind=SupportPurchaseKind.PURCHASE,
                user_id=user.id,
                amount_minor=0,
                currency="EUR",
                period_start=start,
                period_end=months_later(start, months) if months else None,
            )
            session.add(
                AuditEvent(
                    id=generate_uuid(),
                    event_type="support.granted",
                    actor_user_id=administrator.id,
                    target_user_id=user.id,
                    target_type=AuditTargetType.USER.value,
                    target_id=str(user.id),
                    details={"reason": reason.strip(), "months": months, "order": order},
                )
            )


async def _run(args: argparse.Namespace) -> None:
    engine, factory = maintenance_engine()
    try:
        await grant_pass(
            factory,
            username=args.username,
            admin=args.admin,
            reason=args.reason,
            months=None if args.lifetime else args.months,
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Grant a supporter pass.")
    parser.add_argument("username")
    length = parser.add_mutually_exclusive_group(required=True)
    length.add_argument("--months", type=int)
    length.add_argument("--lifetime", action="store_true")
    parser.add_argument("--admin", required=True, help="The administrator making the grant")
    parser.add_argument("--reason", required=True, help="Why, for the audit ledger")
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except SupportGrantError as error:
        raise SystemExit(str(error)) from error
    print(f"Granted {args.username} a supporter pass.")


if __name__ == "__main__":
    main()
