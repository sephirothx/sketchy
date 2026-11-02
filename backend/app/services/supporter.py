"""Supporter status, derived from the purchase ledger and never stored (#1472).

A supporter pass leaves one `support_purchases` row per thing the provider told
us: a purchase, a renewal, a refund, a chargeback. Status is a question about
those facts - a purchase whose period contains now and whose order nothing
reversed - so a pass ends by its period simply running out, and a refund wins
whichever order the two webhooks arrived in. There is no flag to fall out of
step with the ledger (R-SUP-01).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql import func

from app.db.models import SupportPurchase, User
from app.domain_values import AccountState, SupportPurchaseKind
from app.support.providers import ProviderEvent


@dataclass(frozen=True)
class SupporterStatus:
    active: bool = False
    # When the last known period ends. None while inactive, and on a lifetime
    # pass, which has no end to name.
    until: datetime | None = None
    # A subscription will charge again at `until`. False once told not to.
    renews: bool = False

    @classmethod
    def from_columns(
        cls, active: bool, lifetime: bool, until: datetime | None, renews: bool
    ) -> "SupporterStatus":
        """Read the values `supporter_status_columns` selected."""
        if not active:
            return cls()
        if lifetime:
            return cls(active=True)
        return cls(active=True, until=until, renews=renews)

    def payload(self) -> dict:
        return {
            "active": self.active,
            "until": self.until.isoformat() if self.until else None,
            "renews": self.renews,
        }


def supporter_status_columns(
    user_id: UUID | ColumnElement, now: datetime
) -> tuple[ColumnElement, ColumnElement, ColumnElement, ColumnElement]:
    """What status needs, as subqueries to ride another statement (R-PLAT-17).

    `GET /api/auth/me` runs on every page load and may not spend a round trip on
    this. Read the four values with `SupporterStatus.from_columns`.
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
    renews = (
        select(SupportPurchase.id)
        .where(
            *kept,
            SupportPurchase.period_end > now,
            SupportPurchase.provider_subscription_id.is_not(None),
            ~_stopped(SupportPurchase.provider_subscription_id),
        )
        .exists()
    )
    return active, lifetime, until, renews


def _stopped(subscription_id: ColumnElement) -> ColumnElement:
    """Whether a cancellation names this subscription."""
    stop = aliased(SupportPurchase)
    return (
        select(stop.id)
        .where(
            stop.kind == SupportPurchaseKind.CANCELLATION.value,
            stop.provider_subscription_id == subscription_id,
        )
        .exists()
    )


async def renewing_subscriptions(
    session: AsyncSession, user_ids: Iterable[UUID]
) -> tuple[str, ...]:
    """The subscriptions that would still charge these accounts."""
    rows = await session.scalars(
        select(SupportPurchase.provider_subscription_id)
        .where(
            SupportPurchase.user_id.in_(list(user_ids)),
            SupportPurchase.provider_subscription_id.is_not(None),
            SupportPurchase.kind == SupportPurchaseKind.PURCHASE.value,
            ~_stopped(SupportPurchase.provider_subscription_id),
        )
        .distinct()
    )
    return tuple(rows.all())


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
    provider_subscription_id: str | None = None,
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
            provider_subscription_id=provider_subscription_id,
        )
        .on_conflict_do_nothing(index_elements=["provider", "provider_event_id"])
    )
    return result.rowcount == 1


async def _attributed_account(session: AsyncSession, event: ProviderEvent) -> UUID | None:
    """Whose fact this is: what we told the provider, else what its order says.

    A renewal may come back without our custom data, and a refund never carries
    it. A deleted account is nobody: its row names no one (R-SUP-03).
    """
    candidate: UUID | None = None
    if event.account_id:
        try:
            candidate = UUID(event.account_id)
        except ValueError:
            candidate = None
    if candidate is None:
        related = or_(
            SupportPurchase.provider_order_id == event.order_id,
            SupportPurchase.provider_subscription_id == event.subscription_id,
        )
        candidate = await session.scalar(
            select(SupportPurchase.user_id)
            .where(related, SupportPurchase.user_id.is_not(None))
            .limit(1)
        )
    if candidate is None:
        return None
    # Shared, so a deletion in flight finishes first and this sees its tombstone:
    # otherwise a renewal landing beside it would name the deleted account.
    account = await session.get(User, candidate, with_for_update={"read": True})
    if account is None or account.state != AccountState.REGISTERED.value:
        return None
    return candidate


async def apply_provider_event(
    session: AsyncSession, provider: str, event: ProviderEvent
) -> tuple[bool, UUID | None]:
    """Record one webhook's fact. Returns whether it was new, and whose it is."""
    user_id = await _attributed_account(session, event)
    recorded = await record_support_fact(
        session,
        provider=provider,
        provider_event_id=event.event_id,
        provider_order_id=event.order_id,
        provider_subscription_id=event.subscription_id,
        kind=event.kind,
        user_id=user_id,
        amount_minor=event.amount_minor,
        currency=event.currency,
        period_start=event.period_start,
        period_end=event.period_end,
    )
    return recorded, user_id


async def active_supporters(session: AsyncSession, *, now: datetime | None = None) -> int:
    """How many accounts hold a pass right now, for the operator."""
    moment = now or datetime.now(timezone.utc)
    reversal = aliased(SupportPurchase)
    return int(
        await session.scalar(
            select(func.count(SupportPurchase.user_id.distinct())).where(
                SupportPurchase.kind == SupportPurchaseKind.PURCHASE.value,
                SupportPurchase.period_start <= moment,
                or_(SupportPurchase.period_end.is_(None), SupportPurchase.period_end > moment),
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
        )
        or 0
    )
