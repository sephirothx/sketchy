"""One interface over whoever sells the pass: Paddle Billing, or a local stub (#1473).

Hosted checkout by redirect, signed webhook back. No provider script runs on
this origin and no card reaches it (R-PLAT-20, R-SUP-06). `stub` speaks Paddle's
webhook format, so development and the end-to-end suite run the same parser and
signature check production does, with no network.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import http.client
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import uuid4

from app.domain_values import SupportProvider, SupportPurchaseKind
from app.support.config import SupportConfig

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "paddle-signature"
# Older than this and a correctly signed delivery is a replay, not a retry:
# Paddle stamps each attempt afresh.
SIGNATURE_TOLERANCE = timedelta(minutes=5)
API_TIMEOUT_SECONDS = 10
PRODUCT_YEAR = "year"
PRODUCT_LIFETIME = "lifetime"
PRODUCT_GIFT = "gift"
PRODUCTS = (PRODUCT_YEAR, PRODUCT_LIFETIME, PRODUCT_GIFT)
_STUB_YEAR = timedelta(days=365)


class BadSignature(Exception):
    """A webhook this deployment cannot prove came from its provider."""


class ProviderUnavailable(Exception):
    """The provider could not be reached, or refused what we asked."""


class ProviderRefused(ProviderUnavailable):
    """It answered, and the answer was no: asking again will not change it. Anything
    else may have worked, or may yet."""


@dataclass(frozen=True)
class ProviderEvent:
    """What a webhook said, in our words. Carries nothing about the buyer but
    the account id we put there ourselves."""

    event_id: str
    kind: SupportPurchaseKind
    order_id: str
    subscription_id: str | None = None
    account_id: str | None = None
    product: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    amount_minor: int = 0
    currency: str = "EUR"
    # A gift: `account_id` is who it is for. Its period is decided on arrival
    # (`apply_provider_event`), because it starts when their time ends.
    giver_id: str | None = None
    gift_anonymous: bool = False


@dataclass(frozen=True)
class Cancellation:
    subscription_id: str
    # Where the provider says the confirmation should go, if it knows.
    email: str | None = None


class Provider(Protocol):
    name: str

    def parse_webhook(
        self, body: bytes, headers: Mapping[str, str], now: datetime
    ) -> ProviderEvent | None:
        """Verify a delivery. Raises BadSignature; None for what we do not act on."""
        ...

    async def create_checkout(
        self,
        *,
        product: str,
        account_id: str,
        extra_minor: int,
        base_url: str,
        giver_id: str | None = None,
        gift_anonymous: bool = False,
    ) -> str:
        """Where to send the buyer. `account_id` is who the pass is for."""
        ...

    async def cancel_at_period_end(self, subscription_id: str) -> Cancellation: ...

    async def stop_if_unpaid(self, subscription_id: str) -> bool:
        """Stop a subscription that has stopped paying, at once. False for a healthy
        one: its renewal has been paid, or is about to be."""
        ...

    async def move_renewal(self, subscription_id: str, when: datetime) -> None:
        """Charge next at `when`, and nothing for the change. Raises ProviderUnavailable."""
        ...

    async def subscriptions_of_email(self, email: str) -> tuple[str, ...]: ...

    async def receipt_url(self, order_id: str, *, base_url: str) -> str | None:
        """A short-lived link to the order's receipt, or None when there is none.
        Raises ProviderUnavailable."""
        ...


def _sign(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(
        secret.encode(), f"{timestamp}:".encode() + body, hashlib.sha256
    ).hexdigest()


def signature_header(secret: str, body: bytes, now: datetime) -> str:
    """A `Paddle-Signature` value: how the stub signs what it posts to itself."""
    timestamp = int(now.timestamp())
    return f"ts={timestamp};h1={_sign(secret, timestamp, body)}"


def verify_signature(
    secret: str, body: bytes, header: str | None, now: datetime
) -> None:
    fields = dict(
        part.split("=", 1) for part in (header or "").split(";") if "=" in part
    )
    try:
        timestamp = int(fields["ts"])
        supplied = fields["h1"]
    except (KeyError, ValueError) as error:
        raise BadSignature("no signature") from error
    # As bytes: `compare_digest` raises on non-ASCII text, and anybody can send that.
    if not secret or not hmac.compare_digest(
        _sign(secret, timestamp, body).encode(), supplied.encode("utf-8", "replace")
    ):
        raise BadSignature("signature does not match")
    if abs(now.timestamp() - timestamp) > SIGNATURE_TOLERANCE.total_seconds():
        raise BadSignature("signature too old")


def _moment(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _minor(value: object) -> int:
    try:
        return max(0, int(str(value)))
    except ValueError:
        return 0


def _transaction_event(event_id: str, data: dict) -> ProviderEvent | None:
    custom = data.get("custom_data") or {}
    product = custom.get("product")
    period = data.get("billing_period") or {}
    start = _moment(period.get("starts_at"))
    end = _moment(period.get("ends_at"))
    subscription_id = data.get("subscription_id")
    if end is None and (subscription_id or product not in (PRODUCT_LIFETIME, PRODUCT_GIFT)):
        # Only a lifetime pass may have no end, and a gift gets its end on
        # arrival: anything else without one must not silently become a pass for life.
        return None
    start = start or _moment(data.get("billed_at")) or _moment(data.get("created_at"))
    if start is None:
        return None
    totals = (data.get("details") or {}).get("totals") or {}
    return ProviderEvent(
        event_id=event_id,
        kind=SupportPurchaseKind.PURCHASE,
        order_id=str(data["id"]),
        subscription_id=subscription_id,
        account_id=custom.get("account_id"),
        product=product,
        period_start=start,
        period_end=end,
        amount_minor=_minor(totals.get("total")),
        currency=str(data.get("currency_code") or "EUR"),
        giver_id=custom.get("giver_id"),
        gift_anonymous=custom.get("gift_anonymous") is True,
    )


def _adjustment_event(event_id: str, data: dict) -> ProviderEvent | None:
    # Any approved refund ends the pass, partial ones included: a withdrawal
    # within the fourteen days is refunded pro rata, so partial is the normal
    # shape of "this contract is over" (#1471). A chargeback the seller later
    # wins (`chargeback_reverse`) is deliberately not acted on: the pass stays
    # ended, and the operator can grant it back.
    kinds = {
        "refund": SupportPurchaseKind.REFUND,
        "chargeback": SupportPurchaseKind.CHARGEBACK,
    }
    kind = kinds.get(data.get("action"))
    if kind is None or data.get("status") != "approved":
        return None
    return ProviderEvent(
        event_id=event_id,
        kind=kind,
        order_id=str(data["transaction_id"]),
        amount_minor=_minor((data.get("totals") or {}).get("total")),
        currency=str(data.get("currency_code") or "EUR"),
    )


def cancellation_event(subscription_id: str) -> ProviderEvent:
    """The one fact a subscription's cancellation leaves.

    Keyed by the subscription: our own click and each webhook about it arrive
    separately, and are one thing that happened.
    """
    return ProviderEvent(
        event_id=f"cancel:{subscription_id}",
        kind=SupportPurchaseKind.CANCELLATION,
        order_id=subscription_id,
        subscription_id=subscription_id,
    )


def parse_paddle_event(body: bytes) -> ProviderEvent | None:
    """Paddle's event, in our words, or None for a kind we do not act on."""
    try:
        event = json.loads(body)
        event_id = str(event["event_id"])
        event_type = str(event["event_type"])
        data = event["data"]
        if event_type == "transaction.completed":
            return _transaction_event(event_id, data)
        if event_type in ("adjustment.created", "adjustment.updated"):
            return _adjustment_event(event_id, data)
        if event_type == "subscription.canceled" or (
            event_type == "subscription.updated"
            and (data.get("scheduled_change") or {}).get("action") == "cancel"
        ):
            return cancellation_event(str(data["id"]))
    except (KeyError, TypeError, ValueError, AttributeError):
        # Signed, so it is Paddle's; a shape we cannot read must not make it
        # retry for days. Logged by type alone: the body names the buyer.
        logger.warning("support_webhook_unreadable", exc_info=False)
    return None


class PaddleProvider:
    name = SupportProvider.PADDLE.value

    def __init__(self, config: SupportConfig) -> None:
        self._config = config

    def parse_webhook(
        self, body: bytes, headers: Mapping[str, str], now: datetime
    ) -> ProviderEvent | None:
        verify_signature(
            self._config.webhook_secret, body, headers.get(SIGNATURE_HEADER), now
        )
        return parse_paddle_event(body)

    async def _call(self, method: str, path: str, payload: dict | None = None) -> dict:
        request = urllib.request.Request(
            f"{self._config.api_url}{path}",
            method=method,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
                "Paddle-Version": "1",
            },
        )

        def send() -> dict:
            with urllib.request.urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
                return json.loads(response.read())

        try:
            return await asyncio.to_thread(send)
        except urllib.error.HTTPError as error:
            logger.warning(
                "support_provider_call_failed %s %s: %s",
                method,
                path.partition("?")[0],
                error.code,
            )
            # Not a timeout, a lock on a change in progress, or a rate limit.
            if 400 <= error.code < 500 and error.code not in (408, 409, 425, 429):
                raise ProviderRefused(str(error.code)) from error
            raise ProviderUnavailable(str(error.code)) from error
        # OSError covers URLError and timeouts; HTTPException a connection that
        # dropped mid-response. Either way the provider did not answer.
        except (OSError, http.client.HTTPException, ValueError) as error:
            # Never the query: a lookup by e-mail carries the buyer's address.
            logger.warning(
                "support_provider_call_failed %s %s: %s",
                method,
                path.partition("?")[0],
                type(error).__name__,
            )
            raise ProviderUnavailable(type(error).__name__) from error

    async def create_checkout(
        self,
        *,
        product: str,
        account_id: str,
        extra_minor: int,
        base_url: str,
        giver_id: str | None = None,
        gift_anonymous: bool = False,
    ) -> str:
        price = {
            PRODUCT_YEAR: self._config.price_year,
            PRODUCT_LIFETIME: self._config.price_lifetime,
            PRODUCT_GIFT: self._config.price_gift,
        }[product]
        items: list[dict] = [{"price_id": price, "quantity": 1}]
        payload: dict = {
            "items": items,
            "collection_mode": "automatic",
            # The account travels here, never in a query string we wrote.
            "custom_data": {"account_id": account_id, "product": product},
        }
        if giver_id:
            payload["custom_data"] |= {"giver_id": giver_id, "gift_anonymous": gift_anonymous}
        if extra_minor:
            # One non-catalog line on this first charge only: a subscription's
            # renewals repeat its catalog prices, not one-time lines.
            items.append(
                {
                    "quantity": 1,
                    "price": {
                        "name": "One-time extra",
                        "description": "An optional extra, on top of the pass",
                        "product_id": self._config.extra_product_id,
                        "tax_mode": "account_setting",
                        "unit_price": {"amount": str(extra_minor), "currency_code": "EUR"},
                    },
                }
            )
            payload["currency_code"] = "EUR"
        if self._config.checkout_url:
            payload["checkout"] = {"url": self._config.checkout_url}
        response = await self._call("POST", "/transactions", payload)
        try:
            return str(response["data"]["checkout"]["url"])
        except (KeyError, TypeError) as error:
            raise ProviderUnavailable("no checkout link came back") from error

    async def cancel_at_period_end(self, subscription_id: str) -> Cancellation:
        quoted = urllib.parse.quote(subscription_id, safe="")
        try:
            response = await self._call(
                "POST",
                f"/subscriptions/{quoted}/cancel",
                {"effective_from": "next_billing_period"},
            )
        except ProviderRefused:
            # Already over, when a webhook saying so was lost: that is what was
            # asked for, and retrying it would fail for ever. And a paused one has
            # no next period to stop at.
            response = await self._call("GET", f"/subscriptions/{quoted}")
            status = (response.get("data") or {}).get("status")
            if status == "paused":
                response = await self._call(
                    "POST", f"/subscriptions/{quoted}/cancel", {"effective_from": "immediately"}
                )
            elif status != "canceled":
                raise
        return Cancellation(
            subscription_id=subscription_id,
            email=await self._email_of((response.get("data") or {}).get("customer_id")),
        )

    async def stop_if_unpaid(self, subscription_id: str) -> bool:
        quoted = urllib.parse.quote(subscription_id, safe="")
        response = await self._call("GET", f"/subscriptions/{quoted}")
        status = (response.get("data") or {}).get("status")
        if status == "canceled":
            return True
        if status in ("past_due", "paused"):
            # At the end of the period would be too late: Paddle goes on trying to
            # collect a past-due one until then.
            await self._call(
                "POST", f"/subscriptions/{quoted}/cancel", {"effective_from": "immediately"}
            )
            return True
        return False

    async def move_renewal(self, subscription_id: str, when: datetime) -> None:
        # Refused for a subscription past due or within 30 minutes of renewing. Read
        # first: a redelivered webhook must not risk that on what has already moved.
        quoted = urllib.parse.quote(subscription_id, safe="")
        current = await self._call("GET", f"/subscriptions/{quoted}")
        try:
            billed = datetime.fromisoformat(str((current.get("data") or {}).get("next_billed_at")))
        except ValueError:
            billed = None
        if billed is not None and billed >= when.replace(microsecond=0):
            return
        await self._call(
            "PATCH",
            f"/subscriptions/{quoted}",
            {
                "next_billed_at": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "proration_billing_mode": "do_not_bill",
            },
        )

    async def receipt_url(self, order_id: str, *, base_url: str) -> str | None:
        # Paddle calls it the invoice; its link lasts an hour, so it is asked for
        # at each click rather than kept.
        quoted = urllib.parse.quote(order_id, safe="")
        try:
            response = await self._call("GET", f"/transactions/{quoted}/invoice")
        except ProviderRefused:
            return None
        url = (response.get("data") or {}).get("url")
        return url if isinstance(url, str) and url.startswith("https://") else None

    async def _email_of(self, customer_id: object) -> str | None:
        """Best effort: the cancellation has happened whether or not this works."""
        if not isinstance(customer_id, str):
            return None
        try:
            quoted = urllib.parse.quote(customer_id, safe="")
            customer = await self._call("GET", f"/customers/{quoted}")
        except ProviderUnavailable:
            return None
        return (customer.get("data") or {}).get("email")

    async def subscriptions_of_email(self, email: str) -> tuple[str, ...]:
        query = urllib.parse.urlencode({"email": email})
        customers = await self._call("GET", f"/customers?{query}")
        found: list[str] = []
        for customer in customers.get("data") or []:
            query = urllib.parse.urlencode(
                # `past_due` too: it can still be cancelled, and still charges.
                {"customer_id": customer["id"], "status": "active,past_due"}
            )
            subscriptions = await self._call("GET", f"/subscriptions?{query}")
            found += [item["id"] for item in subscriptions.get("data") or []]
        return tuple(found)


class StubProvider:
    """Checkout that runs here: a page with a Pay button (`api/support.py`)."""

    name = SupportProvider.STUB.value

    def __init__(self, config: SupportConfig) -> None:
        self._config = config

    def parse_webhook(
        self, body: bytes, headers: Mapping[str, str], now: datetime
    ) -> ProviderEvent | None:
        verify_signature(
            self._config.webhook_secret, body, headers.get(SIGNATURE_HEADER), now
        )
        return parse_paddle_event(body)

    def checkout_token(
        self,
        *,
        product: str,
        account_id: str,
        extra_minor: int,
        giver_id: str = "",
        gift_anonymous: bool = False,
    ) -> str:
        fields = f"{product}.{account_id}.{extra_minor}.{giver_id}.{int(gift_anonymous)}"
        proof = hmac.new(
            self._config.webhook_secret.encode(), fields.encode(), hashlib.sha256
        ).hexdigest()
        return f"{fields}.{proof}"

    def read_checkout_token(self, token: str) -> dict | None:
        parts = token.split(".")
        if len(parts) != 6 or parts[0] not in PRODUCTS or not parts[2].isdigit():
            return None
        read = {
            "product": parts[0],
            "account_id": parts[1],
            "extra_minor": int(parts[2]),
            "giver_id": parts[3],
            "gift_anonymous": parts[4] == "1",
        }
        return read if hmac.compare_digest(self.checkout_token(**read), token) else None

    async def create_checkout(
        self,
        *,
        product: str,
        account_id: str,
        extra_minor: int,
        base_url: str,
        giver_id: str | None = None,
        gift_anonymous: bool = False,
    ) -> str:
        token = self.checkout_token(
            product=product,
            account_id=account_id,
            extra_minor=extra_minor,
            giver_id=giver_id or "",
            gift_anonymous=gift_anonymous,
        )
        return f"{base_url}/api/support/stub/checkout?token={token}"

    def paid_event(
        self,
        *,
        product: str,
        account_id: str,
        extra_minor: int,
        now: datetime,
        giver_id: str = "",
        gift_anonymous: bool = False,
    ) -> bytes:
        """What Paddle would post once this checkout was paid."""
        order = f"txn_stub_{uuid4().hex}"
        amount = (6900 if product == PRODUCT_LIFETIME else 1900) + extra_minor
        data: dict = {
            "id": order,
            "currency_code": "EUR",
            "billed_at": now.isoformat(),
            "custom_data": {
                "account_id": account_id,
                "product": product,
                **({"giver_id": giver_id, "gift_anonymous": gift_anonymous} if giver_id else {}),
            },
            "details": {"totals": {"total": str(amount)}},
        }
        if product == PRODUCT_YEAR:
            data["subscription_id"] = f"sub_stub_{uuid4().hex}"
            data["billing_period"] = {
                "starts_at": now.isoformat(),
                "ends_at": (now + _STUB_YEAR).isoformat(),
            }
        return json.dumps(
            {
                "event_id": f"evt_stub_{uuid4().hex}",
                "event_type": "transaction.completed",
                "data": data,
            }
        ).encode()

    async def cancel_at_period_end(self, subscription_id: str) -> Cancellation:
        return Cancellation(subscription_id=subscription_id)

    async def stop_if_unpaid(self, subscription_id: str) -> bool:
        return True

    async def move_renewal(self, subscription_id: str, when: datetime) -> None:
        return None

    async def subscriptions_of_email(self, email: str) -> tuple[str, ...]:
        return ()

    async def receipt_url(self, order_id: str, *, base_url: str) -> str | None:
        return f"{base_url}/api/support/stub/receipt"


def provider_for(config: SupportConfig) -> Provider:
    if config.provider == SupportProvider.PADDLE.value:
        return PaddleProvider(config)
    if config.provider == SupportProvider.STUB.value:
        return StubProvider(config)
    raise ValueError(f"no provider called {config.provider!r}")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
