"""The supporter pass's REST surface: checkout, webhook, cancel (#1473).

Only mounted when `SUPPORT_PROVIDER` is set. The webhook needs no exemption from
`origin_policy.py`: a provider's request carries no `Origin` and no `Referer`,
which #465 admits by design. Its proof is the signature.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import parse_qs
from uuid import UUID

from fastapi import APIRouter, Request, Response
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
    renewing_subscriptions,
    supporter_status,
)
from app.support.cancellation import cancel_quietly, cancel_subscription
from app.support.config import MAX_EXTRA_MINOR, SupportConfig
from app.support.providers import (
    PRODUCT_LIFETIME,
    SIGNATURE_HEADER,
    BadSignature,
    Provider,
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


def create_support_router(
    session_factory: async_sessionmaker[AsyncSession], config: SupportConfig
) -> APIRouter:
    router = APIRouter(prefix="/api/support")
    provider: Provider = provider_for(config)

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
            async with session_factory() as session:
                async with session.begin():
                    recorded, user_id = await apply_provider_event(
                        session, provider.name, event
                    )
                    stale_years: tuple[str, ...] = ()
                    if recorded and user_id and event.product == PRODUCT_LIFETIME:
                        stale_years = await renewing_subscriptions(session, [user_id])
        except Exception:
            support_signals.saw(ERROR, now)
            logger.exception("support_webhook_failed")
            return Response(status_code=500)
        support_signals.saw(RECORDED if recorded else DUPLICATE, now)
        await cancel_quietly(session_factory, provider, stale_years)
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
            raise Refusal(502, ErrorCode.SUPPORT_UNAVAILABLE) from error
        async with session_factory() as session:
            status = await supporter_status(session, user.id)
        return status.payload()

    @router.post("/cancel/request")
    async def cancel_request(body: CancelRequestBody, request: Request) -> dict:
        """Signed out (§312k). The answer is the same whether or not anything
        matched, so the form cannot be used to find out who holds a pass."""
        throttle(cancel_limiter, getattr(request.state, "client_ip_hash", None))
        identifier = body.identifier.strip()
        user_id: UUID | None = None
        subscriptions: tuple[str, ...] = ()
        try:
            if "@" in identifier:
                named = await provider.subscriptions_of_email(identifier)
                async with session_factory() as session:
                    known = await session.execute(
                        select(
                            SupportPurchase.provider_subscription_id, SupportPurchase.user_id
                        )
                        .where(
                            SupportPurchase.provider_subscription_id.in_(named),
                            SupportPurchase.kind == SupportPurchaseKind.PURCHASE.value,
                        )
                        .limit(len(named) or 1)
                    )
                    rows = known.all()
                subscriptions = tuple(row[0] for row in rows)
                user_id = next((row[1] for row in rows if row[1]), None)
            else:
                async with session_factory() as session:
                    user_id = await session.scalar(
                        select(User.id).where(
                            func.lower(User.username) == identifier.lower(),
                            User.state == AccountState.REGISTERED.value,
                        )
                    )
                    if user_id is not None:
                        subscriptions = await renewing_subscriptions(session, [user_id])
            for subscription_id in subscriptions:
                await cancel_subscription(
                    session_factory, provider, subscription_id, user_id=user_id
                )
        except ProviderUnavailable as error:
            raise Refusal(502, ErrorCode.SUPPORT_UNAVAILABLE) from error
        if subscriptions and user_id:
            async with session_factory() as session:
                async with session.begin():
                    session.add(
                        AuditEvent(
                            id=generate_uuid(),
                            event_type="support.cancel_requested",
                            target_user_id=user_id,
                            target_type=AuditTargetType.USER.value,
                            target_id=str(user_id),
                            details={"count": len(subscriptions)},
                        )
                    )
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
