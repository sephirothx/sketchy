"""The supporter ledger under overlapping work (#1471).

Webhooks take turns inside the one worker, but an account deletion, a sweep or a
name-style save do not wait for them. These run the overlaps that can really
happen, in many interleavings, on a database where two transactions can overlap:
PostgreSQL with `TEST_DATABASE_URL`, otherwise a SQLite file.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.errors import install_refusal_handler
from app.api.support import create_support_router
from app.auth.account_data import anonymize_account
from app.db.models import Base, SupportPurchase, User
from app.domain_values import AccountState
from app.services.supporter import renewals_nothing_pays_for, supporter_status
from app.support.config import STUB_WEBHOOK_SECRET, SupportConfig
from app.support.providers import signature_header

from tests.dbfixtures import create_test_db

STUB = SupportConfig(provider="stub", webhook_secret=STUB_WEBHOOK_SECRET)
NOW = datetime.now(timezone.utc).replace(microsecond=0)
ROUNDS = int(os.environ.get("RACE_ROUNDS", "12"))
# Which side finished first, across the rounds: a race that always ends the same
# way is not testing the other order.
FIRST: dict[str, int] = {}


@pytest.fixture
async def racing(tmp_path, monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "support-races-test-secret")
    monkeypatch.setenv("SUPPORT_PROVIDER", "stub")
    if os.environ.get("TEST_DATABASE_URL"):
        factory, engine = await create_test_db()
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'races.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all, checkfirst=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    install_refusal_handler(app)
    app.include_router(create_support_router(factory, STUB))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http, factory
    await engine.dispose()


async def _account(factory) -> UUID:
    async with factory() as session:
        async with session.begin():
            user = User(
                display_name="Racer",
                username=f"racer_{uuid4().hex[:10]}",
                password_hash="not-a-real-hash",
                state=AccountState.REGISTERED.value,
            )
            session.add(user)
    return user.id


def _year(account: UUID | None, *, order: str, subscription: str, start: datetime) -> bytes:
    data = {
        "id": order,
        "currency_code": "EUR",
        "billed_at": start.isoformat(),
        "subscription_id": subscription,
        "billing_period": {"starts_at": start.isoformat(), "ends_at": (start + timedelta(days=365)).isoformat()},
        "details": {"totals": {"total": "1900"}},
    }
    if account is not None:
        data["custom_data"] = {"account_id": str(account), "product": "year"}
    return json.dumps({"event_id": f"evt_{uuid4().hex}", "event_type": "transaction.completed", "data": data}).encode()


def _refund(order: str) -> bytes:
    return json.dumps(
        {
            "event_id": f"evt_{uuid4().hex}",
            "event_type": "adjustment.created",
            "data": {"action": "refund", "status": "approved", "transaction_id": order, "totals": {"total": "1900"}},
        }
    ).encode()


async def _post(http, body: bytes) -> int:
    response = await http.post(
        "/api/support/webhooks/stub",
        content=body,
        headers={"Paddle-Signature": signature_header(STUB_WEBHOOK_SECRET, body, datetime.now(timezone.utc))},
    )
    return response.status_code


async def _renew_after(http, renewal: bytes, wait: float, finished: list[str]) -> int:
    await asyncio.sleep(wait)
    answer = await _post(http, renewal)
    finished.append("renewed")
    return answer


async def _delete_after(factory, account: UUID, wait: float, finished: list[str]) -> None:
    await asyncio.sleep(wait)
    await anonymize_account(factory, user_id=account)
    finished.append("deleted")


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    # The webhook reads the account under a shared row lock, which is what makes a
    # deletion in flight finish first. SQLite has no row locks, and a renewal can
    # write the account's id after the deletion cleared it - acceptable only
    # because production refuses SQLite (validate_database_configuration).
    reason="needs row locks: PostgreSQL",
)
async def test_a_renewal_landing_beside_a_deletion_names_nobody_and_does_not_renew(racing):
    """R-SUP-03 and R-SUP-09, in every order the two can finish in: no row is left
    naming the deleted account, and what would renew is stopped now or owed a stop
    the sweep will make."""
    http, factory = racing
    rng = random.Random(1471)
    FIRST.clear()
    for round_ in range(ROUNDS):
        account = await _account(factory)
        subscription = f"sub_race_{round_}_{uuid4().hex[:6]}"
        assert await _post(http, _year(account, order=f"txn_a_{round_}", subscription=subscription, start=NOW)) == 200
        renewal = _year(
            # Half without our custom data: found by the subscription instead.
            account if rng.random() < 0.5 else None,
            order=f"txn_b_{round_}",
            subscription=subscription,
            start=NOW + timedelta(days=365),
        )
        # Either may start first, by a few milliseconds: about what either takes.
        delay = rng.uniform(-0.008, 0.008)

        finished: list[str] = []
        status, _ = await asyncio.gather(
            _renew_after(http, renewal, max(-delay, 0), finished),
            _delete_after(factory, account, max(delay, 0), finished),
        )
        FIRST[finished[0]] = FIRST.get(finished[0], 0) + 1
        assert status in (200, 500)
        if status == 500:
            # Asked to come back: the retry must settle it.
            assert await _post(http, renewal) == 200
        async with factory() as session:
            named = await session.scalar(
                select(SupportPurchase.id).where(SupportPurchase.user_id == account).limit(1)
            )
            stopped = await session.scalar(
                select(SupportPurchase.id).where(
                    SupportPurchase.kind == "cancellation",
                    SupportPurchase.provider_subscription_id == subscription,
                )
            )
            owed = {sub for sub, _ in await renewals_nothing_pays_for(session)}
        assert named is None, f"round {round_}: a row still names the deleted account"
        assert stopped is not None or subscription in owed, (
            f"round {round_} (delay {delay:.3f}s): the renewal would charge again unnoticed"
        )
    if ROUNDS >= 12:
        assert len(FIRST) == 2, f"every round finished the same way: {FIRST}"


async def test_a_flood_of_deliveries_is_each_recorded_once(racing):
    """Paddle retries on its own clock: the same events, at once and out of order."""
    http, factory = racing
    rng = random.Random(2026)
    for round_ in range(ROUNDS):
        accounts = [await _account(factory) for _ in range(3)]
        sales = [
            _year(account, order=f"txn_f_{round_}_{n}", subscription=f"sub_f_{round_}_{n}", start=NOW)
            for n, account in enumerate(accounts)
        ]
        refund = _refund(f"txn_f_{round_}_0")
        bodies = sales * 3 + [refund] * 3
        rng.shuffle(bodies)
        answers = await asyncio.gather(*(_post(http, body) for body in bodies))
        assert set(answers) == {200}, answers
        async with factory() as session:
            event_ids = (
                await session.scalars(
                    select(SupportPurchase.provider_event_id).where(SupportPurchase.kind != "cancellation")
                )
            ).all()
            statuses = [await supporter_status(session, account) for account in accounts]
            stopped = set(
                (
                    await session.scalars(
                        select(SupportPurchase.provider_subscription_id).where(
                            SupportPurchase.kind == "cancellation"
                        )
                    )
                ).all()
            )
        assert len(event_ids) == len(set(event_ids)), "an event was written twice"
        assert [status.active for status in statuses] == [False, True, True], round_
        assert f"sub_f_{round_}_0" in stopped, "the refunded year still renews"
