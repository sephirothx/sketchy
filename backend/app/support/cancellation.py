"""Stopping a subscription's renewal, and saying so (#1473).

The periods already paid stand: a cancellation only leaves a fact, so the page
can say "ends" instead of "renews", and owes a confirmation by mail (§312k).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.mail import queue_email
from app.db.models import EmailOutboxEntry, User, UserSettings
from app.domain_values import EmailTemplate
from app.services.supporter import apply_provider_event, renewals_nothing_pays_for
from app.support.config import support_config
from app.support.providers import Provider, cancellation_event, provider_for

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
    budget=None,
):
    """Try again what could not be stopped when it should have been: an outage during
    an account's deletion, or a webhook whose retries ran out. Nothing else comes back
    to these. A retention-loop sweep, so it runs hourly and reports like one, and
    removes nothing. What still fails is logged and comes up again next time.
    """
    from app.services.sweeps import SweepReport

    started = time.monotonic()
    config = support_config()
    subscriptions: tuple[str, ...] = ()
    if config is not None:
        async with session_factory() as session:
            subscriptions = await renewals_nothing_pays_for(session, limit=STOP_BATCH)
    stopped = 0
    if config is not None:
        provider = provider_for(config)
        for subscription_id in subscriptions:
            if await cancel_quietly(session_factory, provider, (subscription_id,)):
                stopped += 1
    return SweepReport(
        stopped,
        name="unpaid_for_renewals",
        batches=1,
        seconds=time.monotonic() - started,
        exhausted=len(subscriptions) >= STOP_BATCH,
        oldest_overdue_seconds=0.0,
    )

