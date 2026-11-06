"""Generated input against the supporter webhook and the ledger it writes (#1471).

The webhook is the one door money comes through, and a provider retries a 500
for days, so the property is: a delivery signed with our secret is answered 200
- a shape we cannot read included, which is logged and dropped - and whatever it
writes keeps the ledger's rules. A delivery we cannot prove is refused 401 and
writes nothing. The parser is held to the same rules on its own, many times
faster, so the door test can spend its budget on the database.

Derandomized and small on every run; `FUZZ_SCALE=<n>` (tests/fuzzing.py) is the
long search. Set `TEST_DATABASE_URL` for PostgreSQL, whose column limits SQLite
does not enforce.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from hypothesis import example, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select

from app.api.errors import install_refusal_handler
from app.api.support import create_support_router
from app.db.models import SupportPurchase, User
from app.support.config import STUB_WEBHOOK_SECRET, SupportConfig
from app.support.providers import (
    PRODUCTS,
    STUB_EXTRA_PRODUCT,
    parse_paddle_event,
    signature_header,
)

from tests.dbfixtures import create_test_db
from tests.fuzzing import budget, stall_guard

STUB = SupportConfig(provider="stub", webhook_secret=STUB_WEBHOOK_SECRET)
NOW = datetime.now(timezone.utc)
# The ledger's columns: what a readable event has to fit.
ID_LENGTH = 128
INT_MAX = 2**31 - 1

# ---------------------------------------------------------------- generated deliveries

junk = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=12),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=6), inner, max_size=3),
    max_leaves=6,
)


def maybe(good: st.SearchStrategy) -> st.SearchStrategy:
    """Mostly a value Paddle would send, sometimes anything at all."""
    return st.one_of(good, good, good, junk)


moments = st.datetimes(
    min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1), timezones=st.just(timezone.utc)
)
iso_times = st.one_of(
    moments.map(lambda moment: moment.isoformat().replace("+00:00", "Z")),
    # Naive, and offsets other than UTC: well-formed ISO 8601, all of them.
    moments.map(lambda moment: moment.replace(tzinfo=None).isoformat()),
    moments.map(lambda moment: moment.astimezone(timezone(timedelta(hours=-7))).isoformat()),
    st.sampled_from(["", "2026-13-01T00:00:00Z", "yesterday", "2026-11-07"]),
)
ids = st.one_of(
    st.text(alphabet="abcdef0123456789_", min_size=1, max_size=20).map(lambda tail: f"txn_{tail}"),
    st.text(min_size=0, max_size=3),
    st.integers(min_value=10**126, max_value=10**135).map(str),
    # Either side of the column's limit, prefix included.
    st.integers(min_value=ID_LENGTH - 8, max_value=ID_LENGTH + 1).map(lambda size: "x" * size),
)
amounts = st.one_of(
    st.integers(min_value=0, max_value=200_000).map(str),
    st.integers(min_value=-10**3, max_value=10**15).map(str),
    st.sampled_from(["", "1e3", "19.00", " 1900", "NaN"]),
)
currencies = st.one_of(st.just("EUR"), st.sampled_from(["USD", "eur", "EURO", "", "€"]), st.text(max_size=5))


@st.composite
def custom_data(draw, accounts: list[str]):
    fields = {}
    if draw(st.booleans()):
        fields["account_id"] = draw(maybe(st.sampled_from(accounts) | st.uuids().map(str)))
    if draw(st.booleans()):
        fields["product"] = draw(maybe(st.sampled_from(PRODUCTS)))
    if draw(st.booleans()):
        fields["giver_id"] = draw(maybe(st.sampled_from(accounts)))
        fields["gift_anonymous"] = draw(maybe(st.booleans()))
    return fields


@st.composite
def transactions(draw, accounts: list[str]):
    data: dict = {
        "id": draw(maybe(ids)),
        "currency_code": draw(maybe(currencies)),
        "billed_at": draw(maybe(iso_times)),
        "custom_data": draw(maybe(custom_data(accounts))),
        "details": {
            "totals": {"total": draw(maybe(amounts))},
            "line_items": draw(
                maybe(
                    st.lists(
                        st.fixed_dictionaries(
                            {
                                "product": st.fixed_dictionaries(
                                    {"id": st.sampled_from([STUB_EXTRA_PRODUCT, "pro_other"])}
                                ),
                                "totals": st.fixed_dictionaries({"total": maybe(amounts)}),
                            }
                        ),
                        max_size=3,
                    )
                )
            ),
        },
    }
    if draw(st.booleans()):
        data["subscription_id"] = draw(maybe(ids.map(lambda tail: f"sub_{tail}")))
    if draw(st.booleans()):
        data["billing_period"] = draw(
            maybe(st.fixed_dictionaries({"starts_at": maybe(iso_times), "ends_at": maybe(iso_times)}))
        )
    return data


adjustments = st.fixed_dictionaries(
    {
        "action": maybe(st.sampled_from(["refund", "chargeback", "credit", "chargeback_reverse"])),
        "status": maybe(st.sampled_from(["approved", "pending_approval", "rejected"])),
        "transaction_id": maybe(ids),
        "currency_code": maybe(currencies),
        "totals": maybe(st.fixed_dictionaries({"total": maybe(amounts)})),
    }
)
subscriptions = st.fixed_dictionaries(
    {
        "id": maybe(ids.map(lambda tail: f"sub_{tail}")),
        "scheduled_change": maybe(
            st.none() | st.fixed_dictionaries({"action": st.sampled_from(["cancel", "pause"])})
        ),
    }
)


@st.composite
def deliveries(draw, accounts: list[str]) -> bytes:
    """A whole webhook body, as bytes: mostly Paddle's shape, sometimes not JSON."""
    kind = draw(
        st.sampled_from(
            [
                "transaction.completed",
                "adjustment.created",
                "adjustment.updated",
                "subscription.canceled",
                "subscription.updated",
                "customer.created",
            ]
        )
    )
    data = {
        "transaction.completed": transactions(accounts),
        "adjustment.created": adjustments,
        "adjustment.updated": adjustments,
        "subscription.canceled": subscriptions,
        "subscription.updated": subscriptions,
        "customer.created": st.just({"id": "ctm_1"}),
    }[kind]
    envelope = {
        "event_id": draw(maybe(st.uuids().map(lambda value: f"evt_{value.hex}"))),
        "event_type": kind,
        "data": draw(maybe(data)),
    }
    if draw(st.integers(min_value=0, max_value=19)) == 0:
        return draw(st.binary(max_size=40))
    return json.dumps(envelope).encode()


# ---------------------------------------------------------------- what a readable event must be


def _readable(event) -> None:
    """Everything the ledger needs of an event the parser let through."""
    for value in (event.event_id, event.order_id):
        assert isinstance(value, str) and 0 < len(value) <= ID_LENGTH, value
    for value in (event.subscription_id, event.account_id, event.giver_id, event.product):
        assert value is None or isinstance(value, str), value
    if event.subscription_id is not None:
        assert 0 < len(event.subscription_id) <= ID_LENGTH
    for moment in (event.period_start, event.period_end):
        assert moment is None or moment.utcoffset() is not None, moment
    if event.period_start and event.period_end:
        assert event.period_end > event.period_start
    assert 0 <= event.extra_minor <= event.amount_minor <= INT_MAX
    assert len(event.currency) == 3 and event.currency.isascii() and event.currency.isupper()


ACCOUNTS = [str(uuid4()), str(uuid4())]


def test_the_parser_reads_a_shape_or_says_it_cannot():
    seen = {"read": 0, "dropped": 0}

    @settings(max_examples=budget(4000))
    @example(
        body=json.dumps(
            {
                "event_id": "evt_naive",
                "event_type": "transaction.completed",
                "data": {
                    "id": "txn_1",
                    "subscription_id": "sub_1",
                    "billing_period": {"starts_at": "2026-11-07T00:00:00", "ends_at": "2027-11-07T00:00:00"},
                    "custom_data": {"account_id": ACCOUNTS[0], "product": "year"},
                    "details": {"totals": {"total": "1900"}},
                },
            }
        ).encode()
    )
    @given(body=deliveries(ACCOUNTS))
    def check(body: bytes):
        event = parse_paddle_event(body, STUB_EXTRA_PRODUCT)
        if event is None:
            seen["dropped"] += 1
            return
        seen["read"] += 1
        _readable(event)

    with stall_guard():
        check()
    # A generator that drifted into producing only unreadable bodies would pass
    # while testing nothing.
    assert seen["read"] > 0 and seen["dropped"] > 0, seen


# ---------------------------------------------------------------- through the door, into a database


class Site:
    """The support router on a database, driven on a loop of its own so one
    database serves every generated example."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.run(self._open())

    def run(self, coroutine):
        return self.loop.run_until_complete(asyncio.wait_for(coroutine, 30))

    async def _open(self) -> None:
        self.factory, self.engine = await create_test_db()
        async with self.factory() as session:
            async with session.begin():
                users = [User(display_name=f"Fuzz{n}") for n in range(2)]
                session.add_all(users)
        self.accounts = [str(user.id) for user in users]
        app = FastAPI()
        install_refusal_handler(app)
        app.include_router(create_support_router(self.factory, STUB))
        self.http = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def post(self, body: bytes, signature: str | None) -> int:
        headers = {"Paddle-Signature": signature} if signature is not None else {}
        response = await self.http.post("/api/support/webhooks/stub", content=body, headers=headers)
        return response.status_code

    async def rows(self) -> list[SupportPurchase]:
        async with self.factory() as session:
            return list((await session.scalars(select(SupportPurchase))).all())

    async def count(self) -> int:
        async with self.factory() as session:
            return await session.scalar(select(func.count()).select_from(SupportPurchase))

    def close(self) -> None:
        async def shut() -> None:
            await self.http.aclose()
            await self.engine.dispose()

        self.run(shut())
        self.loop.close()


@pytest.fixture
def site(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "support-fuzz-test-secret")
    monkeypatch.setenv("SUPPORT_PROVIDER", "stub")
    # Every unreadable delivery is logged on purpose; thousands of them are noise.
    logging.getLogger("app.support.providers").setLevel(logging.ERROR)
    opened = Site()
    yield opened
    opened.close()


def _ledger_rule(row: SupportPurchase) -> None:
    assert 0 <= row.extra_minor <= row.amount_minor <= INT_MAX
    assert len(row.currency) == 3
    if row.kind == "purchase":
        assert row.period_start is not None
        assert row.period_end is None or row.period_end > row.period_start
    if row.user_id is not None:
        assert isinstance(row.user_id, UUID)


LONGEST_SUBSCRIPTION = json.dumps(
    {"event_id": "evt_long_cancel", "event_type": "subscription.canceled", "data": {"id": "s" * ID_LENGTH}}
).encode()


def test_a_signed_delivery_is_never_a_500_and_writes_only_what_fits(site: Site):
    answers: dict[int, int] = {}

    @settings(max_examples=budget(400))
    @example(data=None)
    @given(data=st.data())
    def check(data):
        body = LONGEST_SUBSCRIPTION if data is None else data.draw(deliveries(site.accounts))
        status = site.run(site.post(body, signature_header(STUB_WEBHOOK_SECRET, body, datetime.now(timezone.utc))))
        answers[status] = answers.get(status, 0) + 1
        assert status == 200, f"a signed delivery was answered {status}: {body[:400]!r}"

    with stall_guard():
        check()
    for row in site.run(site.rows()):
        _ledger_rule(row)
    assert site.run(site.count()) > 0, "nothing generated was ever recorded"


def test_an_unproven_delivery_is_refused_and_writes_nothing(site: Site):
    @settings(max_examples=budget(150))
    @given(
        data=st.data(),
        forgery=st.sampled_from(["none", "garbage", "wrong_secret", "tampered", "stale", "future"]),
    )
    def check(data, forgery: str):
        body = data.draw(deliveries(site.accounts))
        now = datetime.now(timezone.utc)
        signature = {
            "none": None,
            "garbage": data.draw(st.text(st.characters(min_codepoint=32, max_codepoint=126), max_size=60)),
            "wrong_secret": signature_header("not-the-secret", body, now),
            "tampered": signature_header(STUB_WEBHOOK_SECRET, body + b" ", now),
            "stale": signature_header(STUB_WEBHOOK_SECRET, body, now - timedelta(minutes=6)),
            "future": signature_header(STUB_WEBHOOK_SECRET, body, now + timedelta(minutes=6)),
        }[forgery]
        before = site.run(site.count())
        assert site.run(site.post(body, signature)) == 401
        assert site.run(site.count()) == before

    with stall_guard():
        check()
