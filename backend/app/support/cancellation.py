"""Stopping a subscription's renewal, and saying so (#1473).

The periods already paid stand: a cancellation only leaves a fact, so the page
can say "ends" instead of "renews", and owes a confirmation by mail (§312k).
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.mail import queue_email
from app.db.models import User, UserSettings
from app.domain_values import EmailTemplate
from app.services.supporter import apply_provider_event
from app.support.providers import Provider, cancellation_event

logger = logging.getLogger(__name__)


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
            settings = await session.get(UserSettings, user_id) if user_id else None
            queue_email(
                session,
                to_address=address,
                template=EmailTemplate.SUPPORT_CANCELLED,
                payload={"displayName": user.display_name} if user else {},
                user_id=user_id,
                locale=settings.locale if settings else None,
            )


async def cancel_quietly(
    session_factory: async_sessionmaker[AsyncSession],
    provider: Provider,
    subscription_ids: tuple[str, ...],
) -> None:
    """For a caller that must not fail on this: nobody is there to be told.

    A deleted account, a refunded year, or a year a lifetime pass just replaced.
    A failure here is a charge that should not happen, so it is logged at error
    level for the operator to cancel by hand. Nothing escapes: the caller's own
    work is already committed, and a provider's retry would find it a duplicate.
    """
    for subscription_id in subscription_ids:
        try:
            await cancel_subscription(
                session_factory, provider, subscription_id, notify=False
            )
        except Exception:
            logger.error(
                "support_subscription_not_cancelled %s", subscription_id, exc_info=True
            )
