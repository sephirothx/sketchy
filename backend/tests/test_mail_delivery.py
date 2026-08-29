"""Claim, send, record - and the network in the phase that holds no transaction.

Delivery used to select, send, and commit inside one transaction. A batch of
fifty against a relay timing out at ten seconds held it open for minutes: on
SQLite that blocks every writer, on PostgreSQL it holds a connection and its
locks, and either way a second sweep could take the same row.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import create_db_engine

from app.auth.mail import (
    CLAIM_LEASE,
    MAX_ATTEMPTS,
    MAX_CONCURRENT_SENDS,
    EmailTemplate,
    OutgoingMessage,
    deliver_pending,
    OUTBOX_RETENTION,
    purge_expired_outbox_entries,
    message_id_for,
    queue_email,
)
from app.db.models import Base, EmailOutboxEntry, generate_uuid
from app.domain_values import EmailOutboxState


pytestmark = pytest.mark.asyncio


class TrackingFactory:
    """A session factory that knows how many sessions are open right now."""

    def __init__(self, factory) -> None:
        self._factory = factory
        self.open = 0

    def __call__(self):
        return _TrackedSession(self, self._factory())


class _TrackedSession:
    def __init__(self, tracker: TrackingFactory, session) -> None:
        self._tracker = tracker
        self._session = session

    async def __aenter__(self):
        self._tracker.open += 1
        return await self._session.__aenter__()

    async def __aexit__(self, *exc):
        self._tracker.open -= 1
        return await self._session.__aexit__(*exc)


async def outbox(tmp_path, count: int = 1, template=EmailTemplate.VERIFY_EMAIL):
    # A file, which is what `tmp_path` was always here for. An in-memory
    # SQLite engine gets a StaticPool, handing every session the *same*
    # connection - so two sweeps running "at once" would share one real
    # transaction, and the claim this file exists to test would never be
    # contended. `create_db_engine` also applies the deployment's pragmas.
    engine = create_db_engine(f"sqlite+aiosqlite:///{tmp_path / 'outbox.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            for index in range(count):
                queue_email(
                    session,
                    to_address=f"player{index}@example.test",
                    template=template,
                    payload={"displayName": f"Player {index}", "token": "t"},
                )
    return engine, factory


async def test_the_network_happens_with_no_session_open(tmp_path):
    """The property the rewrite exists for, asserted directly rather than by
    timing: while a message is being sent, nothing is holding a transaction."""
    engine, factory = await outbox(tmp_path)
    tracker = TrackingFactory(factory)
    open_during_send: list[int] = []

    class WatchfulTransport:
        async def send(self, message: OutgoingMessage) -> None:
            open_during_send.append(tracker.open)

    try:
        result = await deliver_pending(tracker, transport=WatchfulTransport())
        assert result.sent == 1
        assert open_during_send == [0]
    finally:
        await engine.dispose()


async def test_two_sweeps_running_at_once_send_each_message_once(tmp_path):
    """The claim is what makes a second sweep - the cron command run beside
    the loop, or a restart overlapping the old process - safe."""
    engine, factory = await outbox(tmp_path, count=8)
    sent: list[str] = []
    started = asyncio.Event()

    class SlowTransport:
        async def send(self, message: OutgoingMessage) -> None:
            started.set()
            await asyncio.sleep(0.05)
            sent.append(message.to_address)

    try:
        first, second = await asyncio.gather(
            deliver_pending(factory, transport=SlowTransport()),
            deliver_pending(factory, transport=SlowTransport()),
        )
        assert sorted(sent) == sorted(set(sent))
        assert len(sent) == 8
        assert first.sent + second.sent == 8
        async with factory() as session:
            states = (await session.scalars(select(EmailOutboxEntry.state))).all()
        assert set(states) == {EmailOutboxState.SENT.value}
    finally:
        await engine.dispose()


async def test_a_batch_is_sent_a_few_at_a_time(tmp_path):
    """One slow recipient no longer delays every message behind it."""
    engine, factory = await outbox(tmp_path, count=20)
    in_flight = 0
    peak = 0

    class CountingTransport:
        async def send(self, message: OutgoingMessage) -> None:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1

    try:
        result = await deliver_pending(factory, transport=CountingTransport())
        assert result.sent == 20
        assert 1 < peak <= MAX_CONCURRENT_SENDS
    finally:
        await engine.dispose()


async def test_a_claim_is_leased_so_a_crash_costs_an_attempt_not_the_message(tmp_path):
    """Nothing marks a row as being sent. The next attempt is pushed out
    instead, so a process that dies mid-send leaves a message that comes due
    again rather than one stuck in a state nobody clears."""
    engine, factory = await outbox(tmp_path)
    checked_at = datetime.now(timezone.utc)
    seen: list[tuple[int, datetime]] = []

    class DyingTransport:
        async def send(self, message: OutgoingMessage) -> None:
            async with factory() as session:
                entry = await session.scalar(select(EmailOutboxEntry))
            seen.append((entry.attempts, entry.next_attempt_at))
            raise RuntimeError("the process is about to go away")

    try:
        await deliver_pending(factory, transport=DyingTransport(), now=checked_at)
        attempts, leased = seen[0]
        # Counted and leased before the send, not after it.
        assert attempts == 1
        assert leased == checked_at + CLAIM_LEASE
        async with factory() as session:
            entry = await session.scalar(select(EmailOutboxEntry))
        assert entry.state == EmailOutboxState.PENDING.value
        assert entry.attempts == 1
        assert entry.next_attempt_at < checked_at + CLAIM_LEASE
        assert "about to go away" in entry.last_error
    finally:
        await engine.dispose()


async def test_a_message_that_keeps_failing_is_given_up_on(tmp_path):
    engine, factory = await outbox(tmp_path)

    class BrokenTransport:
        async def send(self, message: OutgoingMessage) -> None:
            raise RuntimeError("relay refused")

    try:
        at = datetime.now(timezone.utc)
        for _ in range(MAX_ATTEMPTS):
            result = await deliver_pending(factory, transport=BrokenTransport(), now=at)
            assert result.attempted == 1
            at += timedelta(hours=3)
        async with factory() as session:
            entry = await session.scalar(select(EmailOutboxEntry))
        assert entry.state == EmailOutboxState.FAILED.value
        assert entry.attempts == MAX_ATTEMPTS
        # Given up on, so no later sweep picks it up again.
        assert (await deliver_pending(factory, transport=BrokenTransport())).attempted == 0
    finally:
        await engine.dispose()


async def test_every_message_carries_the_identity_of_its_row(tmp_path):
    """Sent twice - a crash between sending and recording - it is one message
    with one identity, which a mail client can collapse."""
    engine, factory = await outbox(tmp_path)
    carried: list[str | None] = []

    class RecordingTransport:
        async def send(self, message: OutgoingMessage) -> None:
            carried.append(message.message_id)

    try:
        async with factory() as session:
            entry = await session.scalar(select(EmailOutboxEntry))
        await deliver_pending(factory, transport=RecordingTransport())
        assert carried == [message_id_for(entry.id)]
        assert str(entry.id) in carried[0]
    finally:
        await engine.dispose()


async def test_one_bad_recipient_does_not_hold_up_the_rest(tmp_path):
    """The sweep used to walk the batch in order inside one transaction, so a
    recipient that timed out was time every later message waited."""
    engine, factory = await outbox(tmp_path, count=5)

    class PickyTransport:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, message: OutgoingMessage) -> None:
            if message.to_address == "player2@example.test":
                await asyncio.sleep(0.05)
                raise RuntimeError("relay refused this one")
            self.sent.append(message.to_address)

    try:
        carrier = PickyTransport()
        result = await deliver_pending(factory, transport=carrier)
        assert result.attempted == 5
        assert result.sent == 4
        assert result.deferred == 1
        assert "player2@example.test" not in carrier.sent
        async with factory() as session:
            refused = await session.scalar(
                select(EmailOutboxEntry).where(
                    EmailOutboxEntry.to_address == "player2@example.test"
                )
            )
        assert refused.state == EmailOutboxState.PENDING.value
        assert refused.last_error == "relay refused this one"
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "sender, domain",
    [
        ("no-reply@sketchy.example", "sketchy.example"),
        ("Sketchy <no-reply@sketchy.example>", "sketchy.example"),
        ("Sketchy Mailer <NO-REPLY@sketchy.example> ", "sketchy.example"),
        ("not-an-address", "localhost"),
    ],
    ids=["bare", "display name", "display name and spacing", "nonsense"],
)
async def test_a_message_id_is_valid_however_the_sender_is_written(sender, domain):
    """`SMTP_FROM` is allowed to carry a display name. Split on "@" rather
    than parsed, that yields a domain ending in ">" - an invalid Message-ID a
    relay may reject, and one that would defeat the deduplication it is for."""
    entry_id = generate_uuid()
    assert message_id_for(entry_id, sender) == f"<{entry_id}@{domain}>"


async def test_a_delivered_message_no_longer_holds_its_token(tmp_path):
    """The row outlives the send; the credential must not. `auth_tokens` keeps
    only hashes so the database never holds a replayable secret - a delivered
    outbox row keeping the raw link token would quietly undo that."""
    engine, factory = await outbox(tmp_path)

    class QuietTransport:
        async def send(self, message: OutgoingMessage) -> None:
            pass

    try:
        result = await deliver_pending(factory, transport=QuietTransport())
        assert result.sent == 1
        async with factory() as session:
            entry = await session.scalar(select(EmailOutboxEntry))
        assert entry.state == EmailOutboxState.SENT.value
        assert "token" not in entry.payload
        # Only the secret goes; the rest of the payload is delivery record.
        assert entry.payload.get("displayName") == "Player 0"
    finally:
        await engine.dispose()


async def test_a_given_up_message_no_longer_holds_its_token(tmp_path):
    """`failed` is as terminal as `sent`: no later sweep renders this payload
    again, so the token has nothing left to do but leak."""
    engine, factory = await outbox(tmp_path)

    class BrokenTransport:
        async def send(self, message: OutgoingMessage) -> None:
            raise RuntimeError("relay refused")

    try:
        at = datetime.now(timezone.utc)
        for _ in range(MAX_ATTEMPTS):
            await deliver_pending(factory, transport=BrokenTransport(), now=at)
            at += timedelta(hours=3)
        async with factory() as session:
            entry = await session.scalar(select(EmailOutboxEntry))
        assert entry.state == EmailOutboxState.FAILED.value
        assert "token" not in entry.payload
    finally:
        await engine.dispose()


async def test_a_deferred_message_keeps_its_token_for_the_retry(tmp_path):
    """A retry renders the link from the stored payload, so scrubbing early
    would turn every transient relay error into a dead reset link."""
    engine, factory = await outbox(tmp_path)

    class FlakyTransport:
        def __init__(self) -> None:
            self.calls = 0
            self.bodies: list[str] = []

        async def send(self, message: OutgoingMessage) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("relay blinked")
            self.bodies.append(message.body)

    transport = FlakyTransport()
    try:
        at = datetime.now(timezone.utc)
        await deliver_pending(factory, transport=transport, now=at)
        async with factory() as session:
            entry = await session.scalar(select(EmailOutboxEntry))
        assert entry.state == EmailOutboxState.PENDING.value
        assert entry.payload.get("token") == "t"
        result = await deliver_pending(
            factory, transport=transport, now=at + timedelta(hours=1)
        )
        assert result.sent == 1
        # The retried message carried a working link, then the row let go.
        assert "token=t" in transport.bodies[0]
        async with factory() as session:
            entry = await session.scalar(select(EmailOutboxEntry))
        assert "token" not in entry.payload
    finally:
        await engine.dispose()


async def test_purge_removes_old_terminal_rows_and_keeps_the_rest(tmp_path):
    """Terminal rows past retention go; a pending row is never purged however
    old it is, because it is still owed a delivery attempt or a give-up."""
    engine, factory = await outbox(tmp_path, count=4)
    now = datetime.now(timezone.utc)
    old = now - OUTBOX_RETENTION - timedelta(days=1)
    fresh = now - timedelta(days=1)
    try:
        async with factory() as session:
            async with session.begin():
                entries = (
                    await session.scalars(
                        select(EmailOutboxEntry).order_by(
                            EmailOutboxEntry.to_address
                        )
                    )
                ).all()
                old_sent, fresh_sent, old_failed, old_pending = entries
                old_sent.state = EmailOutboxState.SENT.value
                old_sent.sent_at = old
                fresh_sent.state = EmailOutboxState.SENT.value
                fresh_sent.sent_at = fresh
                old_failed.state = EmailOutboxState.FAILED.value
                old_failed.created_at = old
                old_pending.created_at = old

        removed = await purge_expired_outbox_entries(
            factory, now=now, batch_size=1
        )
        assert removed == 2
        async with factory() as session:
            kept = (
                await session.scalars(select(EmailOutboxEntry.to_address))
            ).all()
        assert sorted(kept) == sorted(
            [fresh_sent.to_address, old_pending.to_address]
        )
    finally:
        await engine.dispose()


async def test_purge_refuses_a_batch_size_that_cannot_finish(tmp_path):
    """LIMIT 0 returns nothing for ever, so a non-positive batch is an
    infinite loop, not a smaller sweep."""
    engine, factory = await outbox(tmp_path)
    try:
        with pytest.raises(ValueError):
            await purge_expired_outbox_entries(factory, batch_size=0)
    finally:
        await engine.dispose()
