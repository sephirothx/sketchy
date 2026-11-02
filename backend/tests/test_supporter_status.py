"""A supporter pass's facts, the status derived from them, and what deletion leaves (#1472)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.account_data import anonymize_account
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import SupportPurchase, User, generate_uuid
from app.domain_values import SupportPurchaseKind
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.supporter import (
    SupporterStatus,
    record_support_fact,
    supporter_status,
)

from tests.dbfixtures import create_test_db

NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
YEAR = timedelta(days=365)


@pytest.fixture
async def db():
    factory, engine = await create_test_db()
    try:
        yield factory
    finally:
        await engine.dispose()


async def _account(factory, name: str = "Marta") -> UUID:
    async with factory() as session:
        async with session.begin():
            user = User(
                id=generate_uuid(),
                username=name,
                display_name=name,
                password_hash="not-a-real-hash",
                state="registered",
            )
            session.add(user)
        return user.id


async def _fact(
    factory,
    user_id: UUID | None,
    *,
    event: str,
    order: str,
    kind: SupportPurchaseKind = SupportPurchaseKind.PURCHASE,
    start: datetime | None = None,
    end: datetime | None = None,
) -> bool:
    async with factory() as session:
        async with session.begin():
            return await record_support_fact(
                session,
                provider="stub",
                provider_event_id=event,
                provider_order_id=order,
                kind=kind,
                user_id=user_id,
                amount_minor=1900,
                currency="EUR",
                period_start=start,
                period_end=end,
            )


async def _status(factory, user_id: UUID, now: datetime = NOW) -> SupporterStatus:
    async with factory() as session:
        return await supporter_status(session, user_id, now=now)


async def test_the_same_provider_event_twice_leaves_one_row(db):
    user_id = await _account(db)
    assert await _fact(db, user_id, event="e1", order="o1", start=NOW, end=NOW + YEAR)
    assert not await _fact(db, user_id, event="e1", order="o1", start=NOW, end=NOW + YEAR)
    async with db() as session:
        rows = (await session.scalars(select(SupportPurchase))).all()
    assert len(rows) == 1


async def test_nobody_is_a_supporter_until_a_period_contains_now(db):
    user_id = await _account(db)
    assert await _status(db, user_id) == SupporterStatus()
    await _fact(db, user_id, event="e1", order="o1", start=NOW - YEAR, end=NOW)
    assert await _status(db, user_id) == SupporterStatus()
    await _fact(db, user_id, event="e2", order="o2", start=NOW + YEAR, end=NOW + 2 * YEAR)
    assert await _status(db, user_id) == SupporterStatus()


async def test_status_names_the_end_of_the_last_known_period(db):
    user_id = await _account(db)
    await _fact(db, user_id, event="e1", order="o1", start=NOW - YEAR, end=NOW + timedelta(days=1))
    assert await _status(db, user_id) == SupporterStatus(True, NOW + timedelta(days=1))
    # A renewal, or time still to start, extends the answer.
    await _fact(db, user_id, event="e2", order="o2", start=NOW + timedelta(days=1), end=NOW + YEAR)
    assert await _status(db, user_id) == SupporterStatus(True, NOW + YEAR)


async def test_a_lifetime_pass_has_no_end_to_name(db):
    user_id = await _account(db)
    await _fact(db, user_id, event="e1", order="o1", start=NOW - YEAR, end=NOW + YEAR)
    await _fact(db, user_id, event="e2", order="o2", start=NOW - YEAR)
    assert await _status(db, user_id) == SupporterStatus(True, None)
    assert await _status(db, user_id, NOW + 50 * YEAR) == SupporterStatus(True, None)


@pytest.mark.parametrize(
    "kind", [SupportPurchaseKind.REFUND, SupportPurchaseKind.CHARGEBACK]
)
async def test_a_reversal_wins_whichever_webhook_arrived_first(db, kind):
    before = await _account(db, "Before")
    await _fact(db, before, event="r1", order="o1", kind=kind)
    await _fact(db, before, event="e1", order="o1", start=NOW - YEAR, end=NOW + YEAR)
    assert await _status(db, before) == SupporterStatus()

    after = await _account(db, "After")
    await _fact(db, after, event="e2", order="o2", start=NOW - YEAR, end=NOW + YEAR)
    assert (await _status(db, after)).active
    await _fact(db, after, event="r2", order="o2", kind=kind)
    assert await _status(db, after) == SupporterStatus()


async def test_a_refund_of_one_order_leaves_another_active(db):
    user_id = await _account(db)
    await _fact(db, user_id, event="e1", order="o1", start=NOW - YEAR, end=NOW + timedelta(days=9))
    await _fact(db, user_id, event="e2", order="o2", start=NOW - YEAR, end=NOW + timedelta(days=5))
    await _fact(db, user_id, event="r1", order="o1", kind=SupportPurchaseKind.REFUND)
    assert await _status(db, user_id) == SupporterStatus(True, NOW + timedelta(days=5))


async def test_a_refund_naming_nobody_still_reverses_its_order(db):
    user_id = await _account(db)
    await _fact(db, user_id, event="e1", order="o1", start=NOW - YEAR, end=NOW + YEAR)
    await _fact(db, None, event="r1", order="o1", kind=SupportPurchaseKind.REFUND)
    assert await _status(db, user_id) == SupporterStatus()


async def test_an_order_number_is_only_unique_within_its_provider(db):
    user_id = await _account(db)
    await _fact(db, user_id, event="e1", order="o1", start=NOW - YEAR, end=NOW + YEAR)
    async with db() as session:
        async with session.begin():
            await record_support_fact(
                session,
                provider="paddle",
                provider_event_id="r1",
                provider_order_id="o1",
                kind=SupportPurchaseKind.REFUND,
                user_id=None,
                amount_minor=1900,
                currency="EUR",
            )
    assert (await _status(db, user_id)).active


@pytest.mark.parametrize(
    "values",
    [
        {"provider": "lemonsqueezy"},
        {"kind": "gift"},
        {"kind": "purchase", "period_start": None},
        {"kind": "purchase", "period_start": NOW, "period_end": NOW},
        {"kind": "refund", "period_start": NOW},
        {"kind": "chargeback", "period_end": NOW},
        {"amount_minor": -1},
    ],
)
async def test_the_row_refuses_what_no_writer_produces(db, values):
    fields = {
        "provider": "stub",
        "provider_event_id": "e1",
        "provider_order_id": "o1",
        "kind": "purchase",
        "period_start": NOW,
        "period_end": NOW + YEAR,
        "amount_minor": 1900,
        "currency": "EUR",
    }
    if values.get("kind") in ("refund", "chargeback"):
        fields |= {"period_start": None, "period_end": None}
    fields |= values
    async with db() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(SupportPurchase(id=generate_uuid(), **fields))


async def test_deleting_an_account_nulls_who_and_keeps_what(db):
    user_id = await _account(db)
    other = await _account(db, "Bruno")
    await _fact(db, user_id, event="e1", order="o1", start=NOW - YEAR, end=NOW + YEAR)
    await _fact(db, other, event="e2", order="o2", start=NOW - YEAR, end=NOW + YEAR)

    await anonymize_account(db, user_id=user_id)

    async with db() as session:
        rows = {
            row.provider_event_id: row
            for row in (await session.scalars(select(SupportPurchase))).all()
        }
    assert rows["e1"].user_id is None
    assert rows["e1"].provider_order_id == "o1" and rows["e1"].amount_minor == 1900
    assert rows["e2"].user_id == other
    # A later refund still finds the order and leaves no one named.
    assert await _fact(db, None, event="r1", order="o1", kind=SupportPurchaseKind.REFUND)


async def _site(factory, monkeypatch) -> AsyncClient:
    monkeypatch.setenv("IP_HASH_SECRET", "supporter-status-test-secret")
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_me_says_whether_a_registered_account_is_a_supporter(db, monkeypatch):
    async with await _site(db, monkeypatch) as http:
        await http.post("/api/auth/display-name", json={"displayName": "Marta"})
        guest = (await http.get("/api/auth/me")).json()
        assert "supporter" not in guest

        account = await http.post(
            "/api/auth/register", json={"username": "Marta", "password": "a-good-password"}
        )
        me = (await http.get("/api/auth/me")).json()
        assert me["supporter"] == {"active": False, "until": None}
        assert me["settings"]["showSupporterMark"] is True

        now = datetime.now(timezone.utc)
        await _fact(
            db,
            UUID(account.json()["id"]),
            event="e1",
            order="o1",
            start=now - YEAR,
            end=now + YEAR,
        )
        me = (await http.get("/api/auth/me")).json()
        assert me["supporter"]["active"] is True
        assert datetime.fromisoformat(me["supporter"]["until"]) == now + YEAR
