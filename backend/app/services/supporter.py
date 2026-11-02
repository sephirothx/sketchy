"""Supporter status, derived from the purchase ledger and never stored (#1472).

A supporter pass leaves one `support_purchases` row per thing the provider told
us: a purchase, a renewal, a refund, a chargeback. Status is a question about
those facts - a purchase whose period contains now and whose order nothing
reversed - so a pass ends by its period simply running out, and a refund wins
whichever order the two webhooks arrived in. There is no flag to fall out of
step with the ledger (R-SUP-01).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql import func

from app.db.models import SupportPurchase
from app.domain_values import SupportPurchaseKind


@dataclass(frozen=True)
class SupporterStatus:
    active: bool = False
    # When the last known period ends. None while inactive, and on a lifetime
    # pass, which has no end to name.
    until: datetime | None = None

    @classmethod
    def from_columns(
        cls, active: bool, lifetime: bool, until: datetime | None
    ) -> "SupporterStatus":
        """Read the values `supporter_status_columns` selected."""
        if not active:
            return cls()
        return cls(active=True, until=None if lifetime else until)

    def payload(self) -> dict:
        return {
            "active": self.active,
            "until": self.until.isoformat() if self.until else None,
        }


def supporter_status_columns(
    user_id: UUID | ColumnElement, now: datetime
) -> tuple[ColumnElement, ColumnElement, ColumnElement]:
    """What status needs, as subqueries to ride another statement (R-PLAT-17).

    `GET /api/auth/me` runs on every page load and may not spend a round trip on
    this. Read the three values with `SupporterStatus.from_columns`.
    """
    reversal = aliased(SupportPurchase)
    kept = (
        SupportPurchase.user_id == user_id,
        SupportPurchase.kind == SupportPurchaseKind.PURCHASE.value,
        # Across every row of the order, whoever it names: a refund that landed
        # after the account was deleted, or before its purchase, still counts.
        ~select(reversal.id)
        .where(
            reversal.provider == SupportPurchase.provider,
            reversal.provider_order_id == SupportPurchase.provider_order_id,
            reversal.kind.in_(
                (
                    SupportPurchaseKind.REFUND.value,
                    SupportPurchaseKind.CHARGEBACK.value,
                )
            ),
        )
        .exists(),
    )
    started = SupportPurchase.period_start <= now
    active = (
        select(SupportPurchase.id)
        .where(
            *kept,
            started,
            or_(SupportPurchase.period_end.is_(None), SupportPurchase.period_end > now),
        )
        .exists()
    )
    lifetime = (
        select(SupportPurchase.id)
        .where(*kept, started, SupportPurchase.period_end.is_(None))
        .exists()
    )
    # Past the period that contains now: time still to come extends the answer.
    until = (
        select(func.max(SupportPurchase.period_end))
        .where(*kept, SupportPurchase.period_end > now)
        .scalar_subquery()
    )
    return active, lifetime, until


async def supporter_status(
    session: AsyncSession, user_id: UUID, *, now: datetime | None = None
) -> SupporterStatus:
    """One account's status, for a caller with no statement to ride."""
    row = (
        await session.execute(
            select(*supporter_status_columns(user_id, now or datetime.now(timezone.utc)))
        )
    ).one()
    return SupporterStatus.from_columns(*row)


async def record_support_fact(
    session: AsyncSession,
    *,
    provider: str,
    provider_event_id: str,
    provider_order_id: str,
    kind: SupportPurchaseKind,
    user_id: UUID | None,
    amount_minor: int,
    currency: str,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> bool:
    """Record one provider event; False if it was already recorded.

    A provider redelivers webhooks whenever it likes, so the second delivery has
    to be a no-op rather than a second period or a failed request.
    """
    insert = (
        postgresql_insert
        if session.get_bind().dialect.name == "postgresql"
        else sqlite_insert
    )
    result = await session.execute(
        insert(SupportPurchase)
        .values(
            provider=provider,
            provider_event_id=provider_event_id,
            provider_order_id=provider_order_id,
            kind=kind.value,
            user_id=user_id,
            amount_minor=amount_minor,
            currency=currency,
            period_start=period_start,
            period_end=period_end,
        )
        .on_conflict_do_nothing(index_elements=["provider", "provider_event_id"])
    )
    return result.rowcount == 1
