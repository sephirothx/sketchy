"""Settings → Support lists what an account paid, each with its receipt (R-SUP-19)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.errors import install_refusal_handler
from app.api.support import (
    checkout_address_limiter,
    checkout_limiter,
    create_support_router,
    receipt_limiter,
)
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.support.config import STUB_WEBHOOK_SECRET, SupportConfig
from app.support.providers import (
    PaddleProvider,
    ProviderRefused,
    parse_paddle_event,
    signature_header,
)

from tests.dbfixtures import create_test_db

STUB = SupportConfig(provider="stub", webhook_secret=STUB_WEBHOOK_SECRET)


@pytest.fixture
async def site(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "support-payments-test-secret")
    monkeypatch.setenv("SUPPORT_PROVIDER", "stub")
    for limiter in (checkout_limiter, checkout_address_limiter, receipt_limiter):
        limiter.reset()
    factory, engine = await create_test_db()
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    app.include_router(create_support_router(factory, STUB))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    await engine.dispose()


async def _register(http, name: str) -> UUID:
    http.cookies.clear()
    await http.post("/api/auth/display-name", json={"displayName": name})
    response = await http.post(
        "/api/auth/register", json={"username": name, "password": "a-good-password"}
    )
    return UUID(response.json()["id"])


async def _sign_in(http, name: str) -> None:
    http.cookies.clear()
    response = await http.post(
        "/api/auth/login", json={"username": name, "password": "a-good-password"}
    )
    assert response.status_code == 200, response.text


async def _pay(http, path: str, body: dict) -> None:
    started = await http.post(path, json=body)
    assert started.status_code == 200, started.text
    token = started.json()["url"].split("token=")[1]
    paid = await http.post(
        "/api/support/stub/pay",
        content=f"token={token}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert paid.status_code == 303, paid.text


async def _payments(http) -> list[dict]:
    response = await http.get("/api/support/payments")
    assert response.status_code == 200, response.text
    return response.json()["payments"]


async def test_a_buyer_sees_their_own_passes_and_the_gifts_they_gave(site):
    http = site
    bruno = await _register(http, "Bruno")
    await _register(http, "Marta")
    await _pay(http, "/api/support/checkout", {"product": "year", "extraMinor": 500})
    await _pay(http, "/api/support/gift", {"recipientId": str(bruno)})

    gift, year = await _payments(http)
    assert (year["product"], year["amountMinor"], year["currency"]) == ("year", 2400, "EUR")
    assert (year["extraMinor"], gift["extraMinor"]) == (500, 0)
    assert year["giftTo"] is None and year["refunded"] is False
    assert datetime.fromisoformat(year["at"]) <= datetime.now(timezone.utc)
    assert (gift["product"], gift["amountMinor"], gift["giftTo"]) == ("gift", 1900, "Bruno")

    # Bruno holds a pass now, but somebody else paid for it, and how much is theirs.
    await _sign_in(http, "Bruno")
    assert await _payments(http) == []


async def test_a_refunded_payment_says_so(site):
    http = site
    await _register(http, "Marta")
    await _pay(http, "/api/support/checkout", {"product": "lifetime"})
    (payment,) = await _payments(http)
    body = json.dumps(
        {
            "event_id": "evt_refund",
            "event_type": "adjustment.created",
            "data": {
                "action": "refund",
                "status": "approved",
                "transaction_id": payment["orderId"],
                "currency_code": "EUR",
                "totals": {"total": "6900"},
            },
        }
    ).encode()
    refunded = await http.post(
        "/api/support/webhooks/stub",
        content=body,
        headers={
            "Paddle-Signature": signature_header(STUB_WEBHOOK_SECRET, body, datetime.now(timezone.utc))
        },
    )
    assert refunded.status_code == 200, refunded.text

    (payment,) = await _payments(http)
    assert (payment["product"], payment["refunded"]) == ("lifetime", True)


async def test_a_receipt_is_only_the_payers(site):
    http = site
    await _register(http, "Bruno")
    await _register(http, "Marta")
    await _pay(http, "/api/support/checkout", {"product": "year"})
    (payment,) = await _payments(http)

    mine = await http.get(f"/api/support/receipts/{payment['orderId']}")
    assert mine.status_code == 200, mine.text
    assert mine.json()["url"].endswith("/api/support/stub/receipt")

    await _sign_in(http, "Bruno")
    theirs = await http.get(f"/api/support/receipts/{payment['orderId']}")
    assert theirs.status_code == 404
    assert theirs.json()["errorCode"] == "support_receipt_not_found"

    http.cookies.clear()
    assert (await http.get("/api/support/payments")).status_code == 401


async def test_paddle_receipts_are_asked_for_at_the_click():
    provider = PaddleProvider(SupportConfig(provider="paddle", webhook_secret="x", api_key="k"))
    asked: list[str] = []

    async def invoice(method: str, path: str, payload: dict | None = None) -> dict:
        asked.append(f"{method} {path}")
        return {"data": {"url": "https://receipts.example/txn_1.pdf"}}

    provider._call = invoice  # type: ignore[method-assign]
    assert await provider.receipt_url("txn_1", base_url="https://sketchy.test") == (
        "https://receipts.example/txn_1.pdf"
    )
    assert asked == ["GET /transactions/txn_1/invoice?disposition=inline"]

    async def refused(method: str, path: str, payload: dict | None = None) -> dict:
        raise ProviderRefused("400")

    provider._call = refused  # type: ignore[method-assign]
    assert await provider.receipt_url("txn_1", base_url="https://sketchy.test") is None


def test_the_extra_is_read_from_paddles_line_items():
    """Paddle's own split, tax included per line: the €26.50 sandbox payment that
    carried a €7.50 extra."""
    body = json.dumps(
        {
            "event_id": "evt_1",
            "event_type": "transaction.completed",
            "data": {
                "id": "txn_1",
                "currency_code": "EUR",
                "billed_at": "2026-11-06T18:41:00Z",
                "subscription_id": "sub_1",
                "billing_period": {"starts_at": "2026-11-06T18:41:00Z", "ends_at": "2027-11-06T18:41:00Z"},
                "custom_data": {"account_id": "a", "product": "year"},
                "details": {
                    "totals": {"total": "2650"},
                    "line_items": [
                        {"product": {"id": "pro_year"}, "totals": {"total": "1900"}},
                        {"product": {"id": "pro_extra"}, "totals": {"total": "750"}},
                    ],
                },
            },
        }
    ).encode()
    event = parse_paddle_event(body, "pro_extra")
    assert event is not None and (event.amount_minor, event.extra_minor) == (2650, 750)
    # Without the product to look for, nothing is taken for an extra.
    assert parse_paddle_event(body).extra_minor == 0
