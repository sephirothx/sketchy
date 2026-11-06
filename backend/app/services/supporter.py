"""Supporter status, derived from the purchase ledger and never stored (#1472).

A supporter pass leaves one `support_purchases` row per thing the provider told
us: a purchase, a renewal, a refund, a chargeback. Status is a question about
those facts - a purchase whose period contains now and whose order nothing
reversed - so a pass ends by its period simply running out, and a refund wins
whichever order the two webhooks arrived in. There is no flag to fall out of
step with the ledger (R-SUP-01).
"""
from __future__ import annotations

import calendar
import time
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import ColumnElement, and_, false, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased
from sqlalchemy.sql import func

from app.auth.avatar_doodles import SUPPORTER_DOODLES, doodle_name, random_doodle_key
from app.auth.bans import active_ban_filter
from app.db.models import InboxEntry, SupportPurchase, User, UserBan, UserSettings
from app.domain_values import AccountState, SupportPurchaseKind
from app.support.config import support_config
from app.support.providers import PRODUCT_GIFT, ProviderEvent


@dataclass(frozen=True)
class SupporterStatus:
    active: bool = False
    # When the last known period ends. None while inactive, and on a lifetime
    # pass, which has no end to name.
    until: datetime | None = None
    # A subscription we have not stopped can still charge: while the pass runs, at
    # `until`; a period past and unpaid may still be collected, so it can be cancelled
    # whether or not a pass is active. False once told not to.
    renews: bool = False

    @classmethod
    def from_columns(
        cls, active: bool, lifetime: bool, until: datetime | None, renews: bool
    ) -> "SupporterStatus":
        """Read the values `supporter_status_columns` selected."""
        if not active:
            return cls(renews=renews)
        if lifetime:
            return cls(active=True, renews=renews)
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
    # Whatever period it is up to: a renewal a gift moved has no period of its own
    # while the gift runs, and Paddle will still bill it (R-SUP-16).
    renews = (
        select(SupportPurchase.id)
        .where(
            *kept,
            SupportPurchase.provider_subscription_id.is_not(None),
            ~_stopped(SupportPurchase.provider_subscription_id),
        )
        .exists()
    )
    return active, lifetime, until, renews


def _not_reversed(purchase: type[SupportPurchase] = SupportPurchase) -> ColumnElement:
    """This purchase's order has no refund or chargeback, under any account."""
    reversal = aliased(SupportPurchase)
    return ~(
        select(reversal.id)
        .where(
            reversal.provider == purchase.provider,
            reversal.provider_order_id == purchase.provider_order_id,
            reversal.kind.in_(
                (SupportPurchaseKind.REFUND.value, SupportPurchaseKind.CHARGEBACK.value)
            ),
        )
        .exists()
    )


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


async def subscriptions_of_order(session: AsyncSession, order_id: str) -> tuple[str, ...]:
    """What still renews this order: a refunded year must not charge again."""
    rows = await session.scalars(
        select(SupportPurchase.provider_subscription_id)
        .where(
            SupportPurchase.provider_order_id == order_id,
            SupportPurchase.kind == SupportPurchaseKind.PURCHASE.value,
            SupportPurchase.provider_subscription_id.is_not(None),
            ~_stopped(SupportPurchase.provider_subscription_id),
        )
        .distinct()
    )
    return tuple(rows.all())


async def unstopped_owners(
    session: AsyncSession, subscription_ids: Iterable[str]
) -> dict[str, UUID | None]:
    """Which of these subscriptions we sold and have not stopped, and for whom."""
    rows = await session.execute(
        select(SupportPurchase.provider_subscription_id, SupportPurchase.user_id)
        .where(
            SupportPurchase.provider_subscription_id.in_(list(subscription_ids)),
            SupportPurchase.kind == SupportPurchaseKind.PURCHASE.value,
            ~_stopped(SupportPurchase.provider_subscription_id),
        )
        .distinct()
    )
    owners: dict[str, UUID | None] = {}
    for subscription_id, user_id in rows.all():
        owners[subscription_id] = owners.get(subscription_id) or user_id
    return owners


def _order_reversed(purchase) -> ColumnElement:
    reversal = aliased(SupportPurchase)
    return (
        select(reversal.id)
        .where(
            reversal.provider == purchase.provider,
            reversal.provider_order_id == purchase.provider_order_id,
            reversal.kind.in_(
                (SupportPurchaseKind.REFUND.value, SupportPurchaseKind.CHARGEBACK.value)
            ),
        )
        .exists()
    )


async def renewals_nothing_pays_for(session: AsyncSession) -> list[tuple[str, datetime]]:
    """Subscriptions that can still charge and must not (R-SUP-09), each with when it
    came due, oldest first: the account is gone, the order was refunded, or a lifetime
    pass replaced them. Read from the facts, so a stop that failed needs nothing written
    down to be tried again, and a sweep behind on them can say by how much.
    """
    named = aliased(SupportPurchase)
    reversal = aliased(SupportPurchase)
    lifetime = aliased(SupportPurchase)
    ownerless = and_(
        SupportPurchase.user_id.is_(None),
        ~select(named.id)
        .where(
            named.provider_subscription_id == SupportPurchase.provider_subscription_id,
            named.user_id.is_not(None),
        )
        .exists(),
    )
    reversed_at = (
        select(func.min(reversal.created_at))
        .where(
            reversal.provider == SupportPurchase.provider,
            reversal.provider_order_id == SupportPurchase.provider_order_id,
            reversal.kind.in_(
                (SupportPurchaseKind.REFUND.value, SupportPurchaseKind.CHARGEBACK.value)
            ),
        )
        .scalar_subquery()
    )
    replaced_at = (
        select(func.min(lifetime.created_at))
        .where(
            lifetime.user_id == SupportPurchase.user_id,
            lifetime.kind == SupportPurchaseKind.PURCHASE.value,
            lifetime.period_end.is_(None),
            ~_order_reversed(lifetime),
        )
        .scalar_subquery()
    )
    rows = await session.execute(
        select(
            SupportPurchase.provider_subscription_id,
            ownerless,
            func.coalesce(SupportPurchase.owner_deleted_at, SupportPurchase.created_at),
            reversed_at,
            replaced_at,
        ).where(
            SupportPurchase.kind == SupportPurchaseKind.PURCHASE.value,
            SupportPurchase.provider_subscription_id.is_not(None),
            ~_stopped(SupportPurchase.provider_subscription_id),
            or_(ownerless, _order_reversed(SupportPurchase), replaced_at.is_not(None)),
        )
    )
    due: dict[str, datetime] = {}
    for subscription_id, gone, gone_at, reversed_on, replaced_on in rows.all():
        for moment in (gone_at if gone else None, reversed_on, replaced_on):
            if moment is None:
                continue
            moment = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
            if subscription_id not in due or moment < due[subscription_id]:
                due[subscription_id] = moment
    return sorted(due.items(), key=lambda item: item[1])


async def order_was_reversed(session: AsyncSession, order_id: str) -> bool:
    return (
        await session.scalar(
            select(SupportPurchase.id)
            .where(
                SupportPurchase.provider_order_id == order_id,
                SupportPurchase.kind.in_(
                    (
                        SupportPurchaseKind.REFUND.value,
                        SupportPurchaseKind.CHARGEBACK.value,
                    )
                ),
            )
            .limit(1)
        )
        is not None
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


def supporter_mark_column(user_id: UUID | ColumnElement, now: datetime) -> ColumnElement:
    """Whether other players see this account's mark (#1474).

    Combined here, on the server, so no client ever receives a mark its owner
    hid: a supporter who hid it is the same on the wire as anybody else. Hidden
    while suspended too, because a suspended account is not there to be thanked.
    With no provider there is no tier, and this asks the database nothing.
    """
    if support_config() is None:
        return false()
    active = supporter_status_columns(user_id, now)[0]
    # Aliased, because the seat read has `user_settings` in its own FROM and a
    # subquery on the same name would correlate to it and lose its own.
    settings = aliased(UserSettings)
    hidden = (
        select(settings.user_id)
        .where(settings.user_id == user_id, settings.show_supporter_mark.is_(False))
        .exists()
    )
    suspended = (
        select(UserBan.id).where(UserBan.user_id == user_id, *active_ban_filter(now)).exists()
    )
    return and_(active, ~hidden, ~suspended)


async def supporter_marks(
    session: AsyncSession, user_ids: Iterable[UUID | str], *, now: datetime | None = None
) -> set[str]:
    """Which of these accounts show a mark, for a list that has already read them."""
    ids = {UUID(str(user_id)) for user_id in user_ids}
    if not ids or support_config() is None:
        return set()
    rows = await session.scalars(
        select(User.id).where(
            User.id.in_(ids),
            supporter_mark_column(User.id, now or datetime.now(timezone.utc)),
        )
    )
    return {str(user_id) for user_id in rows.all()}


async def name_styles_of(session: AsyncSession, user_ids: Iterable[UUID | str]) -> dict[str, str]:
    """The styles these accounts wear, for a list read from frozen seats."""
    ids = {UUID(str(user_id)) for user_id in user_ids}
    if not ids:
        return {}
    rows = await session.execute(
        select(User.id, User.name_style).where(User.id.in_(ids), User.name_style.is_not(None))
    )
    return {str(user_id): style for user_id, style in rows.all()}


async def revert_supporter_choices(session: AsyncSession, user_id: UUID) -> None:
    """A refund or chargeback takes back what the pass let them choose, in the same
    transaction as the fact, or buy-choose-charge-back keeps the goods (R-SUP-17).
    Only with no other purchase left standing: a lapse keeps them, and so does a
    refund of one order while another still pays.
    """
    now = datetime.now(timezone.utc)
    still_paid = await session.scalar(
        select(SupportPurchase.id)
        .where(
            SupportPurchase.user_id == user_id,
            SupportPurchase.kind == SupportPurchaseKind.PURCHASE.value,
            # Time that has run out pays for nothing: a lapsed year must not let a
            # later purchase's chargeback keep what it chose.
            or_(SupportPurchase.period_end.is_(None), SupportPurchase.period_end > now),
            _not_reversed(),
        )
        .limit(1)
    )
    if still_paid is not None:
        return
    user = await session.get(User, user_id)
    if user is None:
        return
    user.name_style = None
    if doodle_name(user.avatar_key) in SUPPORTER_DOODLES:
        user.avatar_key = random_doodle_key()


async def active_supporter_ids(
    session: AsyncSession, user_ids: Iterable[UUID], *, now: datetime | None = None
) -> set[UUID]:
    """Who holds a pass, shown or hidden: the moderator's view, and nobody else's."""
    ids = set(user_ids)
    if not ids or support_config() is None:
        return set()
    moment = now or datetime.now(timezone.utc)
    rows = await session.scalars(
        select(User.id).where(User.id.in_(ids), supporter_status_columns(User.id, moment)[0])
    )
    return set(rows.all())


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
    gifted_by_user_id: UUID | None = None,
    gift_anonymous: bool = False,
    is_gift: bool = False,
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
            gifted_by_user_id=gifted_by_user_id,
            gift_anonymous=gift_anonymous,
            is_gift=is_gift,
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
        # Only the identifiers this event has: comparing to None would be
        # `IS NULL`, which every lifetime row matches, and name a stranger.
        related = [SupportPurchase.provider_order_id == event.order_id]
        if event.subscription_id:
            related.append(SupportPurchase.provider_subscription_id == event.subscription_id)
        candidate = await session.scalar(
            select(SupportPurchase.user_id)
            .where(or_(*related), SupportPurchase.user_id.is_not(None))
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
    """Record one webhook's fact. Returns whether it was new, and whose it is.

    A purchase with none of our custom data and no row we recognise is not ours:
    a Paddle account can sell other things, and those are none of this ledger's
    business, nor this code's to cancel.
    """
    if event.kind == SupportPurchaseKind.PURCHASE and not event.account_id:
        # A purchase, and nothing less: a refund or a cancellation of something else
        # the account sells is recorded too, and must not make its purchase ours.
        known = await session.scalar(
            select(SupportPurchase.id)
            .where(
                SupportPurchase.kind == SupportPurchaseKind.PURCHASE.value,
                or_(
                    SupportPurchase.provider_order_id == event.order_id,
                    SupportPurchase.provider_subscription_id == event.subscription_id,
                )
                if event.subscription_id
                else SupportPurchase.provider_order_id == event.order_id
            )
            .limit(1)
        )
        if known is None:
            return False, None
    if event.product == PRODUCT_GIFT and event.account_id:
        # Written first, because the read below only shares it: two gifts landing
        # together must not both read the same last period and overlap.
        try:
            await session.execute(
                select(User.id).where(User.id == UUID(event.account_id)).with_for_update()
            )
        except ValueError:
            pass
    user_id = await _attributed_account(session, event)
    if event.product == PRODUCT_GIFT and event.kind == SupportPurchaseKind.PURCHASE:
        event = await _with_gift_period(session, event, user_id)
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
        gifted_by_user_id=await _gift_giver(session, event),
        gift_anonymous=event.gift_anonymous,
        is_gift=event.product == PRODUCT_GIFT and event.kind == SupportPurchaseKind.PURCHASE,
    )
    return recorded, user_id


GIFT_MONTHS = 12


def months_later(moment: datetime, months: int) -> datetime:
    index = moment.month - 1 + months
    year = moment.year + index // 12
    month = index % 12 + 1
    return moment.replace(
        year=year, month=month, day=min(moment.day, calendar.monthrange(year, month)[1])
    )


async def _with_gift_period(
    session: AsyncSession, event: ProviderEvent, user_id: UUID | None
) -> ProviderEvent:
    """A gift starts when the recipient's time ends, so nothing is wasted (#1540)."""
    start = event.period_start or datetime.now(timezone.utc)
    if user_id is not None:
        _, _, until, _ = supporter_status_columns(user_id, start)
        latest = await session.scalar(select(until))
        if latest is not None and latest > start:
            start = latest
    return replace(event, period_start=start, period_end=months_later(start, GIFT_MONTHS))


async def _gift_giver(session: AsyncSession, event: ProviderEvent) -> UUID | None:
    """The giver, if they still have an account to name."""
    if not event.giver_id:
        return None
    try:
        giver = UUID(event.giver_id)
    except ValueError:
        return None
    account = await session.get(User, giver, with_for_update={"read": True})
    if account is None or account.state != AccountState.REGISTERED.value:
        return None
    return giver


ENDING_NOTICE = timedelta(days=14)
ENDING_BATCH = 500


async def tell_ending_supporters(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    budget=None,
):
    """Tell each supporter, once, fourteen days before their last period ends.

    A retention-loop sweep, so it runs hourly and reports like one. Removes
    nothing. The subject is the purchase row, so the inbox's unique index makes
    a second pass over the same period a no-op. A period something later
    extends is not an ending, and a reversed order was never going to end.
    """
    from app.services.inbox import add_entry
    from app.services.sweeps import SweepReport

    moment = now or datetime.now(timezone.utc)
    started = time.monotonic()
    reversal = aliased(SupportPurchase)
    later = aliased(SupportPurchase)
    told_entry = aliased(InboxEntry)
    told = 0
    async with session_factory() as session:
        async with session.begin():
            rows = await session.execute(
                select(SupportPurchase.id, SupportPurchase.user_id)
                .where(
                    SupportPurchase.kind == SupportPurchaseKind.PURCHASE.value,
                    SupportPurchase.user_id.is_not(None),
                    SupportPurchase.period_end > moment,
                    SupportPurchase.period_end <= moment + ENDING_NOTICE,
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
                    ~select(later.id)
                    .where(
                        later.user_id == SupportPurchase.user_id,
                        later.kind == SupportPurchaseKind.PURCHASE.value,
                        or_(
                            later.period_end.is_(None),
                            later.period_end > SupportPurchase.period_end,
                        ),
                        # Refunded time extends nothing.
                        _not_reversed(later),
                    )
                    .exists(),
                    ~select(told_entry.id)
                    .where(
                        told_entry.kind == "supporter_ending",
                        told_entry.subject_id == SupportPurchase.id,
                    )
                    .exists(),
                )
                .limit(ENDING_BATCH)
            )
            for purchase_id, user_id in rows.all():
                if await add_entry(
                    session,
                    user_id=user_id,
                    kind="supporter_ending",
                    subject_id=purchase_id,
                ):
                    told += 1
    return SweepReport(
        told,
        name="supporter_ending_notices",
        batches=1,
        seconds=time.monotonic() - started,
        exhausted=told >= ENDING_BATCH,
        # Everything due was told in this run, unless the batch ran out.
        oldest_overdue_seconds=0.0,
    )


async def last_gift_end_of(session: AsyncSession, user_id: UUID) -> str | None:
    """When the last gift still standing ends, as `pass_facts` writes it."""
    end = await session.scalar(
        select(func.max(SupportPurchase.period_end)).where(
            SupportPurchase.user_id == user_id, SupportPurchase.is_gift, _not_reversed()
        )
    )
    return end.isoformat() if end else None


async def pass_facts(
    session: AsyncSession, purchase_ids: Iterable[UUID]
) -> dict[UUID, tuple[str | None, bool]]:
    """What the inbox should say about these purchases now: `(until, renews)`.

    A purchase whose order was reversed is left out, and its entry with it.
    """
    ids = set(purchase_ids)
    if not ids:
        return {}
    # A gift has no subscription, but its owner's may be waiting for it to end.
    owned = aliased(SupportPurchase)
    owner_renews = (
        select(owned.id)
        .where(
            owned.user_id == SupportPurchase.user_id,
            owned.kind == SupportPurchaseKind.PURCHASE.value,
            owned.provider_subscription_id.is_not(None),
            ~_stopped(owned.provider_subscription_id),
            _not_reversed(owned),
        )
        .exists()
    )
    rows = await session.execute(
        select(
            SupportPurchase.id,
            SupportPurchase.period_end,
            SupportPurchase.provider_subscription_id,
            _stopped(SupportPurchase.provider_subscription_id),
            owner_renews,
        ).where(SupportPurchase.id.in_(ids), _not_reversed())
    )
    return {
        purchase_id: (
            period_end.isoformat() if period_end else None,
            not stopped if subscription_id else bool(waiting),
        )
        for purchase_id, period_end, subscription_id, stopped, waiting in rows.all()
    }


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
