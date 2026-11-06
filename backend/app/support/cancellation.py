"""Stopping a subscription's renewal, and saying so (#1473).

The periods already paid stand: a cancellation only leaves a fact, so the page
can say "ends" instead of "renews", and owes a confirmation by mail (§312k).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.mail import queue_email
from app.db.models import EmailOutboxEntry, User, UserSettings
from app.domain_values import EmailTemplate
from app.services.supporter import (
    apply_provider_event,
    renewals_nothing_pays_for,
    supporter_status,
)
from app.services.sweeps import SweepBudget, SweepReport
from app.support.config import support_config
from app.support.providers import Provider, ProviderRefused, cancellation_event, provider_for

logger = logging.getLogger(__name__)

# Each is a call to the provider, so an outage should not make one sweep take long.
STOP_BATCH = 20


async def cancel_subscription(
    session_factory: async_sessionmaker[AsyncSession],
    provider: Provider,
    subscription_id: str,
    *,
    user_id: UUID | None = None,
    notify: bool = True,
) -> None:
    """Tell the provider first: a fact without the provider's yes would be a lie."""
    cancelled = await provider.cancel_at_period_end(subscription_id)
    async with session_factory() as session:
        async with session.begin():
            await apply_provider_event(
                session, provider.name, cancellation_event(subscription_id)
            )
            if not notify:
                return
            user = await session.get(User, user_id) if user_id else None
            address = cancelled.email or (user.email if user else None)
            if address is None:
                return
            # One mail a subscription, and the fact cannot say who sends it: two
            # requests can both reach the provider, and its webhook can record the
            # cancellation while the answer to this call is still on its way.
            told = await session.scalars(
                select(EmailOutboxEntry.payload).where(
                    EmailOutboxEntry.to_address == address,
                    EmailOutboxEntry.template == EmailTemplate.SUPPORT_CANCELLED.value,
                )
            )
            if any(payload.get("subscription") == subscription_id for payload in told):
                return
            settings = await session.get(UserSettings, user_id) if user_id else None
            queue_email(
                session,
                to_address=address,
                template=EmailTemplate.SUPPORT_CANCELLED,
                payload={
                    "subscription": subscription_id,
                    **({"displayName": user.display_name} if user else {}),
                },
                user_id=user_id,
                locale=settings.locale if settings else None,
            )


async def cancel_quietly(
    session_factory: async_sessionmaker[AsyncSession],
    provider: Provider,
    subscription_ids: tuple[str, ...],
) -> bool:
    """For a caller that must not fail on this: nobody is there to be told. Whether
    every one stopped.

    A deleted account, a refunded year, or a year a lifetime pass just replaced.
    A failure here is a charge that should not happen, so it is logged at error
    level for the operator to cancel by hand. Nothing escapes: the caller's own
    work is already committed. A webhook answers 500 on False, so the provider's
    retry tries again; nothing else will.
    """
    stopped = True
    for subscription_id in subscription_ids:
        try:
            await cancel_subscription(
                session_factory, provider, subscription_id, notify=False
            )
        except Exception:
            stopped = False
            logger.error(
                "support_subscription_not_cancelled %s", subscription_id, exc_info=True
            )
    return stopped


async def stop_renewals_nothing_pays_for(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    budget: SweepBudget | None = None,
):
    """Try again what could not be stopped when it should have been: an outage during
    an account's deletion, or a webhook whose retries ran out. Nothing else comes back
    to these. A retention-loop sweep, so it runs hourly and reports like one, and removes
    nothing. What still fails is logged, counted as a failed attempt so the loop's health
    says so, and comes up again next time, its lateness measured from when it came due.
    """
    started = time.monotonic()
    moment = now or datetime.now(timezone.utc)
    config = support_config()
    if config is None:
        return SweepReport(0, name="unpaid_for_renewals", oldest_overdue_seconds=0.0, backlog=0)
    async with session_factory() as session:
        due = await renewals_nothing_pays_for(session)
    provider = provider_for(config)
    allowance = min(STOP_BATCH, budget.rows) if budget is not None else STOP_BATCH
    attempted = stopped = 0
    for subscription_id, _ in due[:allowance]:
        # Before each, since one call can take the provider's whole timeout, and the
        # sweeps after this one are waiting.
        if (
            budget is not None
            and attempted
            and time.monotonic() - started >= budget.seconds
        ):
            break
        attempted += 1
        if await cancel_quietly(session_factory, provider, (subscription_id,)):
            stopped += 1
    async with session_factory() as session:
        left = await renewals_nothing_pays_for(session)
    return SweepReport(
        stopped,
        name="unpaid_for_renewals",
        batches=1 if attempted else 0,
        seconds=time.monotonic() - started,
        exhausted=attempted < len(due),
        oldest_overdue_seconds=(
            max(0.0, (moment - left[0][1]).total_seconds()) if left else 0.0
        ),
        backlog=len(left),
        detail={"failed_attempts": attempted - stopped},
    )



async def postpone_renewals(
    session_factory: async_sessionmaker[AsyncSession],
    provider: Provider,
    subscription_ids: tuple[str, ...],
    user_id: UUID,
    *,
    lock: asyncio.Lock,
) -> bool:
    """A gift's months are paid for, so a renewal waits for them to end. Where the
    provider will not move it, it stops: a pass that ends can be bought again, and a
    charge for months already given cannot be taken back here. Whether each one was
    dealt with; False asks for the webhook to be delivered again.

    One at a time, and to the account's last end as read under the lock: two gifts
    landing together would otherwise finish in either order, and the earlier date
    could win. One worker, so a lock in the process is the whole of that.
    """
    async with lock:
        try:
            async with session_factory() as session:
                until = (await supporter_status(session, user_id)).until
        except Exception:
            logger.error("support_renewal_not_moved %s", subscription_ids, exc_info=True)
            return False
        if until is None:
            return True
        dealt_with = True
        for subscription_id in subscription_ids:
            try:
                await provider.move_renewal(subscription_id, until)
            except ProviderRefused:
                logger.warning("support_renewal_not_moved %s", subscription_id, exc_info=True)
                if not await cancel_quietly(session_factory, provider, (subscription_id,)):
                    dealt_with = False
            except Exception:
                # Not a no: it may even have worked. Stopping a healthy renewal for a
                # timeout could not be undone, and the retry costs nothing.
                logger.warning("support_renewal_not_moved %s", subscription_id, exc_info=True)
                dealt_with = False
        return dealt_with
