"""The supporter pass's REST surface: checkout, webhook, cancel (#1473).

Only mounted when `SUPPORT_PROVIDER` is set. The webhook needs no exemption from
`origin_policy.py`: a provider's request carries no `Origin` and no `Referer`,
which #465 admits by design. Its proof is the signature.
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import parse_qs
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import Refusal
from app.api.friends import ACCOUNT_REQUIRED_HEADER
from app.auth.rate_limit import RateLimiter
from app.db.models import AuditEvent, SupportPurchase, User, generate_uuid
from app.deployment import public_base_url
from app.domain_values import AccountState, AuditTargetType, SupportPurchaseKind
from app.refusals import ErrorCode
from app.request_text import ControlFreeModel
from app.services.supporter import (
    apply_provider_event,
    order_was_reversed,
    renewing_subscriptions,
    subscriptions_of_order,
    supporter_status,
    unstopped_owners,
)
from app.support.cancellation import cancel_quietly, cancel_subscription
from app.support.config import MAX_EXTRA_MINOR, SupportConfig
from app.support.providers import (
    PRODUCT_LIFETIME,
    SIGNATURE_HEADER,
    BadSignature,
    Provider,
    ProviderEvent,
    ProviderUnavailable,
    StubProvider,
    provider_for,
    signature_header,
)
from app.support.signals import (
    BAD_SIGNATURE,
    DUPLICATE,
    ERROR,
    IGNORED,
    RECORDED,
    support_signals,
)

logger = logging.getLogger(__name__)

checkout_limiter = RateLimiter(limit=10, window_seconds=60)
checkout_address_limiter = RateLimiter(limit=30, window_seconds=60)
cancel_limiter = RateLimiter(limit=5, window_seconds=60)

STUB_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Stub checkout</title></head>
<body><h1>Stub checkout</h1><p>Nothing here charges anybody: {product}.</p>
<form method="post" action="/api/support/stub/pay">
<input type="hidden" name="token" value="{token}"><button type="submit">Pay</button>
</form></body></html>
"""


class CheckoutBody(ControlFreeModel):
    model_config = ConfigDict(populate_by_name=True)

    product: Literal["year", "lifetime"]
    extra_minor: int = Field(default=0, ge=0, le=MAX_EXTRA_MINOR, alias="extraMinor")


class CancelRequestBody(ControlFreeModel):
    # A username or the e-mail the provider has: §312k asks for no login.
    identifier: str = Field(min_length=1, max_length=254)


async def _subscriptions_to_stop(
    session: AsyncSession, event: ProviderEvent, user_id: UUID | None
) -> tuple[str, ...]:
    """What this fact means must no longer charge (R-SUP-09)."""
    if event.kind in (SupportPurchaseKind.REFUND, SupportPurchaseKind.CHARGEBACK):
        # A refund does not stop a subscription by itself: left alone, next
        # year's renewal would charge again and quietly reopen the pass.
        return await subscriptions_of_order(session, event.order_id)
    if event.kind != SupportPurchaseKind.PURCHASE:
        return ()
    if event.subscription_id and (
        # Paid after the account was deleted: nobody can use what this renews.
        user_id is None
        # A refund can land first, and then nothing else would stop this year.
        or await order_was_reversed(session, event.order_id)
    ):
        return (event.subscription_id,)
    if event.subscription_id:
        # A year's webhook can arrive after the lifetime pass bought on top of it,
        # with nothing left to stop it. And a renewal has nothing to add to one.
        status = await supporter_status(session, user_id)
        if status.active and status.until is None:
            return (event.subscription_id,)
    if event.product == PRODUCT_LIFETIME:
        # The lifetime pass replaces the year it was bought on top of.
        return await renewing_subscriptions(session, [user_id])
    return ()


async def _fact_exists(session: AsyncSession, provider_name: str, event: ProviderEvent) -> bool:
    return (
        await session.scalar(
            select(SupportPurchase.id).where(
                SupportPurchase.provider == provider_name,
                SupportPurchase.provider_event_id == event.event_id,
            )
        )
        is not None
    )


def create_support_router(
    session_factory: async_sessionmaker[AsyncSession], config: SupportConfig
) -> APIRouter:
    router = APIRouter(prefix="/api/support")
    provider: Provider = provider_for(config)
    # A year and the lifetime pass on top of it, or a purchase and its refund, in two
    # transactions at once could each miss the other and stop nothing, and both answer
    # 200. One worker, so one at a time in this process is all that takes.
    webhook_turns = asyncio.Lock()

    async def account(request: Request) -> User:
        value = getattr(request.state, "user_id", None)
        if not value:
            raise Refusal(401, ErrorCode.SIGN_IN_REQUIRED, "Sign in first.")
        async with session_factory() as session:
            user = await session.get(User, UUID(value))
        if user is None or user.state == AccountState.DELETED.value:
            raise Refusal(401, ErrorCode.SIGN_IN_REQUIRED, "Sign in first.")
        if user.is_anonymous:
            # R-SUP-02: a guest's cookie is its only credential.
            raise Refusal(
                403,
                ErrorCode.ACCOUNT_REQUIRED,
                "Create an account to get a supporter pass.",
                params={"action": "support"},
                headers={ACCOUNT_REQUIRED_HEADER: "1"},
            )
        return user

    def throttle(limiter: RateLimiter, key: str | None) -> None:
        if key and not limiter.check(key):
            raise Refusal(
                429, ErrorCode.TOO_MANY_REQUESTS, "Too many requests. Please wait and try again."
            )

    @router.post("/checkout")
    async def checkout(body: CheckoutBody, request: Request) -> dict:
        user = await account(request)
        throttle(checkout_limiter, str(user.id))
        throttle(checkout_address_limiter, getattr(request.state, "client_ip_hash", None))
        async with session_factory() as session:
            status = await supporter_status(session, user.id)
        lifetime = status.active and status.until is None
        # A year on top of a renewing year is a second charge for nothing.
        # Moving up to a lifetime pass is fine: the webhook stops the year.
        if lifetime or (status.renews and body.product != PRODUCT_LIFETIME):
            raise Refusal(409, ErrorCode.SUPPORT_ALREADY_ACTIVE)
        try:
            url = await provider.create_checkout(
                product=body.product,
                account_id=str(user.id),
                extra_minor=body.extra_minor,
                base_url=public_base_url(),
            )
        except ProviderUnavailable as error:
            raise Refusal(502, ErrorCode.SUPPORT_UNAVAILABLE) from error
        return {"url": url}

    async def receive_webhook(body: bytes, headers) -> Response:
        now = datetime.now(timezone.utc)
        try:
            event = provider.parse_webhook(body, headers, now)
        except BadSignature:
            support_signals.saw(BAD_SIGNATURE, now)
            return Response(status_code=401)
        if event is None:
            # Kinds we do not act on get a 200, or the provider retries for days.
            support_signals.saw(IGNORED, now)
            return JSONResponse({"ok": True})
        try:
            async with webhook_turns, session_factory() as session:
                async with session.begin():
                    recorded, user_id = await apply_provider_event(
                        session, provider.name, event
                    )
                    to_stop: tuple[str, ...] = ()
                    # A retry finds a duplicate, and is the only second chance a
                    # failed cancellation gets. Nothing written means not ours.
                    if recorded or await _fact_exists(session, provider.name, event):
                        to_stop = tuple(
                            await unstopped_owners(
                                session, await _subscriptions_to_stop(session, event, user_id)
                            )
                        )
        except Exception:
            support_signals.saw(ERROR, now)
            logger.exception("support_webhook_failed")
            return Response(status_code=500)
        support_signals.saw(RECORDED if recorded else DUPLICATE, now)
        if not await cancel_quietly(session_factory, provider, to_stop):
            # The fact stands; this asks the provider to come back for the rest.
            support_signals.saw(ERROR, now)
            return Response(status_code=500)
        return JSONResponse({"ok": True})

    @router.post("/webhooks/{provider_name}")
    async def webhook(provider_name: str, request: Request):
        if provider_name != provider.name:
            return Response(status_code=404)
        return await receive_webhook(await request.body(), request.headers)

    @router.post("/cancel")
    async def cancel(request: Request) -> dict:
        """One click, signed in: the renewal stops, the time already paid stands."""
        user = await account(request)
        throttle(cancel_limiter, str(user.id))
        async with session_factory() as session:
            subscriptions = await renewing_subscriptions(session, [user.id])
        try:
            for subscription_id in subscriptions:
                await cancel_subscription(
                    session_factory, provider, subscription_id, user_id=user.id
                )
        except ProviderUnavailable as error:
            raise Refusal(502, ErrorCode.SUPPORT_CANCEL_FAILED) from error
        async with session_factory() as session:
            status = await supporter_status(session, user.id)
        return status.payload()

    async def carry_out_cancel_request(identifier: str) -> None:
        """After the answer has gone: what it found must not show in how long it
        took, or in whether the provider happened to be up (R-SUP-09). So a failure
        cannot reach the person who asked, and is left for the operator."""
        try:
            if "@" in identifier:
                named = await provider.subscriptions_of_email(identifier)
                async with session_factory() as session:
                    owners = await unstopped_owners(session, named)
            else:
                async with session_factory() as session:
                    user_id = await session.scalar(
                        select(User.id).where(
                            func.lower(User.username) == identifier.lower(),
                            User.state == AccountState.REGISTERED.value,
                        )
                    )
                    owners = (
                        dict.fromkeys(await renewing_subscriptions(session, [user_id]), user_id)
                        if user_id is not None
                        else {}
                    )
        except Exception:
            # Nothing safe to name: the identifier may be the buyer's address.
            logger.error("support_cancel_request_lookup_failed", exc_info=True)
            return
        for subscription_id, owner in owners.items():
            # One at a time: a failure must not skip the rest, and this is the
            # line that lets the operator stop it by hand.
            try:
                await cancel_subscription(
                    session_factory, provider, subscription_id, user_id=owner
                )
                if owner is None:
                    continue
                async with session_factory() as session:
                    async with session.begin():
                        session.add(
                            AuditEvent(
                                id=generate_uuid(),
                                event_type="support.cancel_requested",
                                target_user_id=owner,
                                target_type=AuditTargetType.USER.value,
                                target_id=str(owner),
                                details={"subscription": subscription_id},
                            )
                        )
            except Exception:
                logger.error(
                    "support_subscription_not_cancelled %s", subscription_id, exc_info=True
                )

    @router.post("/cancel/request")
    async def cancel_request(
        body: CancelRequestBody, request: Request, tasks: BackgroundTasks
    ) -> dict:
        """Signed out (§312k). The answer is the same whatever matched, so the
        form cannot be used to find out who holds a pass."""
        throttle(cancel_limiter, getattr(request.state, "client_ip_hash", None))
        tasks.add_task(carry_out_cancel_request, body.identifier.strip())
        return {"ok": True}

    if isinstance(provider, StubProvider):
        stub = provider

        @router.get("/stub/checkout", response_class=HTMLResponse)
        async def stub_checkout(token: str) -> HTMLResponse:
            read = stub.read_checkout_token(token)
            if read is None:
                raise Refusal(404, ErrorCode.SUPPORT_UNAVAILABLE)
            return HTMLResponse(
                STUB_PAGE.format(product=html.escape(read[0]), token=html.escape(token))
            )

        @router.post("/stub/pay")
        async def stub_pay(request: Request) -> RedirectResponse:
            """Signs what Paddle would post and takes it through the same door."""
            token = parse_qs((await request.body()).decode()).get("token", [""])[0]
            read = stub.read_checkout_token(token)
            if read is None:
                raise Refusal(404, ErrorCode.SUPPORT_UNAVAILABLE)
            now = datetime.now(timezone.utc)
            body = stub.paid_event(
                product=read[0], account_id=read[1], extra_minor=read[2], now=now
            )
            await receive_webhook(
                body,
                {SIGNATURE_HEADER: signature_header(config.webhook_secret, body, now)},
            )
            return RedirectResponse("/support/thanks", status_code=303)

    return router
