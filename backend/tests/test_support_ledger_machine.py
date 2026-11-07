"""Random histories of a supporter pass, checked against a model of the ledger (#1471).

Purchases, renewals with and without our custom data, lifetime passes, gifts,
refunds and chargebacks - some arriving before the purchase they reverse -
cancellations, redeliveries and purchases that are not ours, all through the
signed webhook in whatever order Hypothesis picks. After every step each
account's status, its payments, what still renews and what it may still wear
are compared with a model built from the same events by the rules
docs/requirements.md states (R-SUP-01, -03, -09, -16, -17, -19), not by reading
the code.

Derandomized and short on every run; `FUZZ_SCALE=<n>` (tests/fuzzing.py) runs
longer histories, more of them, and new ones each time. `TEST_DATABASE_URL`
runs it on PostgreSQL.
"""
from __future__ import annotations

import calendar
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule
from sqlalchemy import select, update

from app.db.models import SupportPurchase, User
from app.services.supporter import (
    payments_of,
    renewals_nothing_pays_for,
    supporter_status,
    tell_ending_supporters,
)
from app.support.cancellation import stop_renewals_nothing_pays_for
from app.support.config import STUB_WEBHOOK_SECRET
from app.support.providers import (
    STUB_EXTRA_PRODUCT,
    ProviderUnavailable,
    StubProvider,
    signature_header,
)

from tests.fuzzing import FUZZ_SCALE, budget
from tests.test_support_fuzz import Site

YEAR = timedelta(days=365)
# What the histories reached, across every one a run plays: a generator that
# drifted into, say, never attributing a purchase would pass while testing little.
REACHED: Counter = Counter()
# While true the stub provider is down: it cannot cancel or move a renewal.
OUTAGE = [False]


def _months_later(moment: datetime, months: int) -> datetime:
    """Twelve calendar months on, the day clamped to the month's last: R-SUP-16's year."""
    index = moment.month - 1 + months
    year = moment.year + index // 12
    month = index % 12 + 1
    return moment.replace(year=year, month=month, day=min(moment.day, calendar.monthrange(year, month)[1]))


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


@dataclass
class Fact:
    """One row the ledger should hold, as the model expects it."""

    kind: str
    order: str
    user: str | None
    start: datetime | None = None
    end: datetime | None = None
    subscription: str | None = None
    amount: int = 0
    extra: int = 0
    gift: bool = False
    giver: str | None = None


@dataclass
class Model:
    facts: dict[str, Fact] = field(default_factory=dict)
    # Cancellations, keyed by subscription: ours, the provider's, and those the
    # webhook itself makes (R-SUP-09).
    stopped: set[str] = field(default_factory=set)
    styles: dict[str, str | None] = field(default_factory=dict)

    def purchases(self) -> list[Fact]:
        return [fact for fact in self.facts.values() if fact.kind == "purchase"]

    def reversed(self, order: str) -> bool:
        return any(
            fact.order == order and fact.kind in ("refund", "chargeback") for fact in self.facts.values()
        )

    def kept(self, user: str) -> list[Fact]:
        return [fact for fact in self.purchases() if fact.user == user and not self.reversed(fact.order)]

    def until(self, user: str, now: datetime) -> datetime | None:
        ends = [fact.end for fact in self.kept(user) if fact.end is not None and fact.end > now]
        return max(ends) if ends else None

    def status(self, user: str, now: datetime) -> tuple[bool, datetime | None, bool]:
        """(active, until, renews), as R-SUP-01 defines them."""
        running = [
            fact
            for fact in self.kept(user)
            if fact.start <= now and (fact.end is None or fact.end > now)
        ]
        renews = any(
            fact.subscription is not None and fact.subscription not in self.stopped
            for fact in self.kept(user)
        )
        if not running:
            return False, None, renews
        if any(fact.end is None for fact in running):
            return True, None, renews
        return True, self.until(user, now), renews

    def still_paid(self, user: str, now: datetime) -> bool:
        return any(fact.end is None or fact.end > now for fact in self.kept(user))

    def owner(self, order: str | None = None, subscription: str | None = None) -> str | None:
        for fact in self.facts.values():
            if fact.user is None:
                continue
            if (order and fact.order == order) or (subscription and fact.subscription == subscription):
                return fact.user
        return None


@dataclass
class Sale:
    """A purchase as the provider would report it, delivered or still on its way."""

    order: str
    account: str | None
    product: str
    start: datetime
    end: datetime | None
    subscription: str | None
    amount: int
    extra: int
    custom: bool = True
    giver: str | None = None
    event_id: str = ""


class LedgerMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        OUTAGE[0] = False
        self.site = Site()
        self.accounts = self.site.accounts
        self.model = Model(styles={account: None for account in self.accounts})
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.sent: list[bytes] = []
        self.pending: list[Sale] = []
        self.orders: list[str] = []
        self.subscriptions: dict[str, Sale] = {}
        self.serial = 0
        # A stop that failed in an outage and nothing has retried yet.
        self.unsettled = False
        # Stops an outage left for the sweep, with whom a lifetime pass replaced
        # them for (None: a reversal or no owner, which hold for good).
        self.deferred: dict[str, str | None] = {}

    def next_id(self, prefix: str) -> str:
        """Numbered, not random: a failing history has to replay to shrink."""
        self.serial += 1
        return f"{prefix}_{self.serial:04d}"

    def teardown(self) -> None:
        self.site.close()

    # ------------------------------------------------------------ delivering

    def post(self, envelope: dict) -> None:
        body = json.dumps(envelope).encode()
        self.sent.append(body)
        status = self.site.run(
            self.site.post(body, signature_header(STUB_WEBHOOK_SECRET, body, datetime.now(timezone.utc)))
        )
        if OUTAGE[0] and status == 500:
            # The fact stands; the provider is asked to come back (R-SUP-09).
            self.unsettled = True
            REACHED["answered 500 in an outage"] += 1
            return
        assert status == 200, f"{envelope['event_type']} answered {status}: {envelope}"

    def deliver(self, sale: Sale) -> None:
        data: dict = {
            "id": sale.order,
            "currency_code": "EUR",
            "billed_at": _iso(sale.start),
            "details": {
                "totals": {"total": str(sale.amount)},
                "line_items": (
                    [{"product": {"id": STUB_EXTRA_PRODUCT}, "totals": {"total": str(sale.extra)}}]
                    if sale.extra
                    else []
                ),
            },
        }
        if sale.custom:
            data["custom_data"] = {"account_id": sale.account, "product": sale.product}
            if sale.giver:
                data["custom_data"] |= {"giver_id": sale.giver, "gift_anonymous": False}
        if sale.subscription:
            data["subscription_id"] = sale.subscription
        if sale.product != "gift":
            data["billing_period"] = {"starts_at": _iso(sale.start)}
            if sale.end is not None:
                data["billing_period"]["ends_at"] = _iso(sale.end)
        self.expect_sale(sale)
        self.post({"event_id": sale.event_id, "event_type": "transaction.completed", "data": data})
        if sale.subscription and sale.account is not None:
            # Renewable once its purchase has been told: Paddle renews a year on,
            # never ahead of the sale itself. Somebody else's renews under their
            # custom data, never ours.
            self.subscriptions.setdefault(sale.subscription, sale)

    def expect_sale(self, sale: Sale) -> None:
        """What the ledger should make of this sale, before it is posted."""
        if sale.event_id in self.model.facts:
            return
        known = self.model.owner(order=sale.order, subscription=sale.subscription)
        any_row = any(
            fact.kind == "purchase"
            and (fact.order == sale.order or (sale.subscription and fact.subscription == sale.subscription))
            for fact in self.model.facts.values()
        )
        if not sale.custom and not any_row:
            # Not ours: a Paddle account can sell other things (R-SUP-03).
            return
        user = sale.account if sale.custom else known
        start, end = sale.start, sale.end
        if sale.product == "gift":
            if user is not None:
                later = self.model.until(user, start)
                if later is not None and later > start:
                    start = later
            end = _months_later(start, 12)
        self.model.facts[sale.event_id] = Fact(
            kind="purchase",
            order=sale.order,
            user=user,
            start=start,
            end=end,
            subscription=sale.subscription,
            amount=sale.amount,
            extra=min(sale.extra, sale.amount),
            gift=sale.product == "gift",
            giver=sale.giver,
        )
        # What the webhook stops on its own (R-SUP-09).
        if sale.subscription and (user is None or self.model.reversed(sale.order)):
            self.stop(sale.subscription, None)
        elif sale.subscription and user is not None:
            active, until, _ = self.model.status(user, datetime.now(timezone.utc))
            if active and until is None and not self._lifetime_is(sale.order):
                self.stop(sale.subscription, user)
        if sale.product == "lifetime" and user is not None and not self.model.reversed(sale.order):
            for fact in self.model.kept(user):
                if fact.subscription:
                    self.stop(fact.subscription, user)

    def stop(self, subscription: str, replaced_for: str | None) -> None:
        """A stop the webhook makes. In an outage it fails and waits for the sweep,
        which makes it only if its reason still holds: a reversal holds for good,
        a lifetime pass replacing the year only while that pass stands."""
        if OUTAGE[0]:
            self.deferred[subscription] = replaced_for
        else:
            self.model.stopped.add(subscription)

    def still_owed(self, subscription: str, replaced_for: str | None) -> bool:
        if replaced_for is None:
            return True
        return any(fact.end is None for fact in self.model.kept(replaced_for))

    def _lifetime_is(self, order: str) -> bool:
        return any(f.order == order and f.end is None for f in self.model.purchases())

    def reverse(self, order: str, kind: str, event_id: str | None = None) -> None:
        event_id = event_id or self.next_id("evt")
        if event_id not in self.model.facts:
            user = self.model.owner(order=order)
            REACHED["reversed before its sale was told"] += user is None
            self.model.facts[event_id] = Fact(kind=kind, order=order, user=user)
            for fact in self.model.purchases():
                if fact.order == order and fact.subscription:
                    self.stop(fact.subscription, None)
            if user is not None and not self.model.still_paid(user, datetime.now(timezone.utc)):
                if self.model.styles[user] is not None:
                    REACHED["style taken back"] += 1
                self.model.styles[user] = None
        self.post(
            {
                "event_id": event_id,
                "event_type": "adjustment.created",
                "data": {
                    "action": kind,
                    "status": "approved",
                    "transaction_id": order,
                    "currency_code": "EUR",
                    "totals": {"total": "100"},
                },
            }
        )

    def sale(self, account: str, product: str, offset_days: int, extra: int, *, custom: bool = True,
             giver: str | None = None, subscription: str | None = None, start: datetime | None = None) -> Sale:
        begins = start or self.now + timedelta(days=offset_days)
        end = None if product in ("lifetime", "gift") else begins + YEAR
        base = {"year": 1900, "lifetime": 6900, "gift": 1900}[product]
        sale = Sale(
            order=self.next_id("txn"),
            account=account,
            product=product,
            start=begins,
            end=end,
            subscription=subscription or (self.next_id("sub") if product == "year" else None),
            amount=base + extra,
            extra=extra,
            custom=custom,
            giver=giver,
            event_id=self.next_id("evt"),
        )
        self.orders.append(sale.order)
        return sale

    # ------------------------------------------------------------ what happens

    accounts_ = st.integers(min_value=0, max_value=1)
    # Lapsed, running and not yet begun: never a day either side of a boundary.
    # -355 ends in ten days: inside the fourteen-day ending notice.
    offsets = st.sampled_from([-500, -400, -355, -200, -30, -1, 0, 3])
    extras = st.sampled_from([0, 0, 0, 1, 750, 50_000])

    @rule(who=accounts_, offset=offsets, extra=extras)
    def buy_a_year(self, who, offset, extra):
        self.deliver(self.sale(self.accounts[who], "year", offset, extra))

    @rule(who=accounts_, extra=extras)
    def buy_for_life(self, who, extra):
        self.deliver(self.sale(self.accounts[who], "lifetime", 0, extra))

    @rule(giver=accounts_, extra=extras)
    def gift_the_other(self, giver, extra):
        recipient = self.accounts[1 - giver]
        self.deliver(self.sale(recipient, "gift", 0, extra, giver=self.accounts[giver]))

    @precondition(lambda self: self.subscriptions)
    @rule(data=st.data(), with_custom=st.booleans())
    def renew(self, data, with_custom):
        first = self.subscriptions[data.draw(st.sampled_from(sorted(self.subscriptions)))]
        ends = [
            fact.end
            for fact in self.model.purchases()
            if fact.subscription == first.subscription and fact.end is not None
        ]
        start = max(ends) if ends else first.end
        renewal = self.sale(
            first.account, "year", 0, 0, custom=with_custom, subscription=first.subscription, start=start
        )
        self.deliver(renewal)

    @rule(who=accounts_)
    def a_year_about_to_end(self, who):
        """Ten days left, then the sweep: the notice goes once, and only if nothing
        later carries the pass on."""
        self.deliver(self.sale(self.accounts[who], "year", -355, 0))
        self.the_hourly_sweep()

    @rule(who=accounts_, offset=offsets)
    def bought_but_not_yet_told(self, who, offset):
        """A sale whose webhook is still on its way: a refund may beat it."""
        self.pending.append(self.sale(self.accounts[who], "year", offset, 0))

    @precondition(lambda self: self.pending)
    @rule(data=st.data())
    def told_at_last(self, data):
        self.deliver(self.pending.pop(data.draw(st.integers(0, len(self.pending) - 1))))

    @precondition(lambda self: self.orders)
    @rule(data=st.data(), kind=st.sampled_from(["refund", "chargeback"]))
    def take_it_back(self, data, kind):
        self.reverse(data.draw(st.sampled_from(self.orders)), kind)

    @precondition(lambda self: any(self.model.styles.values()))
    @rule(data=st.data(), kind=st.sampled_from(["refund", "chargeback"]))
    def take_back_everything_a_wearer_has(self, data, kind):
        """Buy, choose, charge back (R-SUP-17): the goods must go with the money."""
        wearer = data.draw(st.sampled_from([a for a, style in self.model.styles.items() if style]))
        for order in sorted({fact.order for fact in self.model.kept(wearer)}):
            self.reverse(order, kind)

    @precondition(lambda self: self.subscriptions)
    @rule(data=st.data())
    def cancel(self, data):
        subscription = data.draw(st.sampled_from(sorted(self.subscriptions)))
        self.model.stopped.add(subscription)
        self.post(
            {
                "event_id": self.next_id("evt"),
                "event_type": "subscription.canceled",
                "data": {"id": subscription},
            }
        )

    @rule()
    def somebody_elses_sale(self):
        """A Paddle account sells other things: no custom data, an order we never saw."""
        self.deliver(self.sale(None, "year", 0, 0, custom=False))

    @precondition(lambda self: self.sent)
    @rule(data=st.data())
    def delivered_again(self, data):
        body = data.draw(st.sampled_from(self.sent))
        before = self.site.run(self.site.count())
        status = self.site.run(
            self.site.post(body, signature_header(STUB_WEBHOOK_SECRET, body, datetime.now(timezone.utc)))
        )
        if OUTAGE[0] and status == 500:
            # A retry that still cannot reach the provider asks to come back again.
            self.unsettled = True
        else:
            assert status == 200
        assert self.site.run(self.site.count()) == before, "a redelivery wrote a second fact"

    @rule(who=accounts_)
    def choose_a_style(self, who):
        """Only a supporter can choose; whatever they chose stays through a lapse."""
        account = self.accounts[who]
        if not self.model.status(account, datetime.now(timezone.utc))[0]:
            return
        self.model.styles[account] = "sunset"

        async def wear() -> None:
            async with self.site.factory() as session:
                async with session.begin():
                    await session.execute(
                        update(User).where(User.id == UUID(account)).values(name_style="sunset")
                    )

        self.site.run(wear())

    @precondition(lambda self: not OUTAGE[0])
    @rule()
    def the_provider_goes_down(self):
        OUTAGE[0] = True

    @precondition(lambda self: OUTAGE[0])
    @rule()
    def the_provider_comes_back(self):
        """The stop sweep then stops what the outage left running: the ledger ends
        where it would have without one."""
        OUTAGE[0] = False
        for _ in range(10):
            if not int(self.site.run(stop_renewals_nothing_pays_for(self.site.factory))):
                break
        for subscription, replaced_for in self.deferred.items():
            if self.still_owed(subscription, replaced_for):
                self.model.stopped.add(subscription)
            else:
                REACHED["a deferred stop no longer owed"] += 1
        self.deferred.clear()
        self.unsettled = False

    @rule()
    def the_hourly_sweep(self):
        """Ending notices go once per pass, however often the sweep runs."""
        first = self.site.run(tell_ending_supporters(self.site.factory))
        again = self.site.run(tell_ending_supporters(self.site.factory))
        REACHED["ending noticed"] += int(first)
        assert int(again) == 0, "a supporter was told their pass is ending twice"

    # ------------------------------------------------------------ what must hold

    @invariant()
    def nothing_is_left_for_the_sweep_to_stop(self):
        """With a provider that answers, each webhook stops what it should at once
        (R-SUP-09): the sweep is for outages, so it must find nothing here."""
        if not hasattr(self, "site") or OUTAGE[0] or self.unsettled:
            return
        assert self.site.run(self._owed()) == [], "a renewal nothing pays for was left running"

    async def _owed(self):
        async with self.site.factory() as session:
            return await renewals_nothing_pays_for(session)

    @invariant()
    def the_ledger_holds_what_the_model_does(self):
        if not hasattr(self, "site"):
            return
        now = datetime.now(timezone.utc)
        for account in self.accounts:
            active, until, renews = self.model.status(account, now)
            REACHED["active"] += active
            REACHED["lifetime"] += active and until is None
            REACHED["renews"] += renews
            REACHED["styled"] += self.model.styles[account] is not None
        REACHED["stopped"] += len(self.model.stopped)
        for fact in self.model.facts.values():
            REACHED[f"{fact.kind}{'' if fact.user else ' unattributed'}{' gift' if fact.gift else ''}"] += 1
        rows = self.site.run(self.site.rows())
        written = {row.provider_event_id: row for row in rows if row.kind != "cancellation"}
        assert set(written) == set(self.model.facts), (
            f"unexpected: {set(written) - set(self.model.facts)}, missing: {set(self.model.facts) - set(written)}"
        )
        for event_id, fact in self.model.facts.items():
            row = written[event_id]
            assert row.kind == fact.kind
            assert (str(row.user_id) if row.user_id else None) == fact.user, event_id
            if fact.kind == "purchase":
                assert (row.period_start, row.period_end) == (fact.start, fact.end), event_id
                assert (row.amount_minor, row.extra_minor) == (fact.amount, fact.extra)
                assert row.is_gift == fact.gift
        stopped = {row.provider_subscription_id for row in rows if row.kind == "cancellation"}
        if OUTAGE[0] or self.unsettled:
            # Every stop the outage cost, while its reason holds, is one the sweep
            # can see and will make; nothing else is stopped.
            owed = {sub for sub, _ in self.site.run(self._owed())}
            due = {sub for sub, why in self.deferred.items() if self.still_owed(sub, why)}
            assert self.model.stopped <= stopped, self.model.stopped - stopped
            assert stopped <= self.model.stopped | set(self.deferred), stopped - self.model.stopped
            assert due - stopped <= owed, f"left running and out of the sweep's sight: {due - stopped - owed}"
            return
        assert stopped == self.model.stopped, (
            f"stopped but should renew: {stopped - self.model.stopped}, "
            f"renewing but should be stopped: {self.model.stopped - stopped}"
        )

    @invariant()
    def every_account_reads_as_the_model_says(self):
        if not hasattr(self, "site"):
            return
        now = datetime.now(timezone.utc)

        async def read(account: str):
            async with self.site.factory() as session:
                status = await supporter_status(session, UUID(account), now=now)
                payments = await payments_of(session, UUID(account))
                style = await session.scalar(select(User.name_style).where(User.id == UUID(account)))
            return status, payments, style

        for account in self.accounts:
            status, payments, style = self.site.run(read(account))
            active, until, renews = self.model.status(account, now)
            if OUTAGE[0] or self.unsettled:
                # A stop the outage cost still renews until the sweep makes it:
                # the status is right to say so.
                renews = status.renews
            assert (status.active, status.until, status.renews) == (active, until, renews), account
            assert style == self.model.styles[account], account
            paid = sorted(
                (fact.order, fact.amount, fact.extra, self.model.reversed(fact.order))
                for fact in self.model.purchases()
                if fact.amount > 0
                and ((fact.user == account and not fact.gift) or (fact.gift and fact.giver == account))
            )
            listed = sorted((p.order_id, p.amount_minor, p.extra_minor, p.refunded) for p in payments)
            assert listed == paid, account


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "support-ledger-machine-secret")
    monkeypatch.setenv("SUPPORT_PROVIDER", "stub")
    for name in ("app.support.providers", "app.support.cancellation", "app.api.support"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    real_cancel, real_move = StubProvider.cancel_at_period_end, StubProvider.move_renewal

    async def cancel(self, subscription_id):
        if OUTAGE[0]:
            raise ProviderUnavailable("down")
        return await real_cancel(self, subscription_id)

    async def move(self, subscription_id, when):
        if OUTAGE[0]:
            raise ProviderUnavailable("down")
        return await real_move(self, subscription_id, when)

    monkeypatch.setattr(StubProvider, "cancel_at_period_end", cancel)
    monkeypatch.setattr(StubProvider, "move_renewal", move)
    OUTAGE[0] = False


def test_random_histories_keep_the_ledger_and_the_model_in_step(quiet):
    from tests.fuzzing import stall_guard

    machine = LedgerMachine.TestCase
    machine.settings = settings(
        max_examples=budget(30),
        stateful_step_count=25 if FUZZ_SCALE == 1 else 60,
    )
    REACHED.clear()
    with stall_guard():
        machine("runTest").runTest()
    for reached in ("active", "lifetime", "renews", "styled", "style taken back", "ending noticed", "answered 500 in an outage", "stopped", "purchase", "purchase gift",
                    "refund", "chargeback", "reversed before its sale was told"):
        assert REACHED[reached], f"no history reached {reached!r}: {dict(REACHED)}"
