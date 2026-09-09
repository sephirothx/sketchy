"""Claim, send, record - and the network in the phase that holds no transaction.

Delivery used to select, send, and commit inside one transaction. A batch of
fifty against a relay timing out at ten seconds held it open for minutes: on
SQLite that blocks every writer, on PostgreSQL it holds a connection and its
locks, and either way a second sweep could take the same row.
"""
from __future__ import annotations

import asyncio
import smtplib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import create_db_engine

from app.auth.mail import (
    CLAIM_LEASE,
    ConsoleTransport,
    MAX_ATTEMPTS,
    MAX_CONCURRENT_SENDS,
    EmailTemplate,
    OutgoingMessage,
    deliver_pending,
    render,
    OUTBOX_RETENTION,
    purge_expired_outbox_entries,
    message_id_for,
    queue_email,
)
from app.db.models import Base, EmailOutboxEntry, generate_uuid
from app.domain_values import EmailOutboxState


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
        await connection.run_sync(Base.metadata.create_all, checkfirst=False)
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
                old_failed.last_error = "given up"
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


async def test_the_console_transport_writes_the_whole_message_outside_production(caplog):
    """The link with its token in it, which is what makes recovery completable
    on a checkout that has no relay (R-AUTH-12)."""
    import logging

    with caplog.at_level(logging.INFO, logger="app.auth.mail"):
        await ConsoleTransport({"SKETCHY_ENV": "development"}).send(
            OutgoingMessage(
                to_address="player@example.test",
                subject="Reset your Sketchy password",
                body="Choose a new password here: http://localhost:8000/reset-password?token=abc123",
            )
        )
    assert "token=abc123" in caplog.text


async def test_the_console_transport_refuses_to_log_a_body_in_production(caplog):
    """#466: a reset link in a log store is a live credential somewhere
    nobody scoped for one. Startup already refuses a production process with
    no relay; this is the lock on the statement that would write the body."""
    import logging

    message = OutgoingMessage(
        to_address="player@example.test",
        subject="Reset your Sketchy password",
        body="Choose a new password here: https://sketchy.example/reset-password?token=abc123",
    )
    with caplog.at_level(logging.DEBUG, logger="app.auth.mail"):
        with pytest.raises(RuntimeError, match="must not run in production"):
            await ConsoleTransport({"SKETCHY_ENV": "production"}).send(message)
    assert "abc123" not in caplog.text
    assert "player@example.test" not in caplog.text


async def test_production_with_no_relay_selects_a_transport_that_will_not_log():
    """Belt and braces on the startup guard: even reached from an operator
    command in an environment that got past it, the fallback sends nothing to
    the log."""
    from app.auth.mail import transport_from_environment

    carrier = transport_from_environment({"SKETCHY_ENV": "production"})
    assert isinstance(carrier, ConsoleTransport)
    with pytest.raises(RuntimeError, match="must not run in production"):
        await carrier.send(
            OutgoingMessage(to_address="p@example.test", subject="s", body="b")
        )


async def test_giving_up_on_a_message_names_the_domain_and_not_the_person(tmp_path, caplog):
    """The line a failing relay is diagnosed from. The domain says which
    provider was involved; the local part only names somebody, and this is
    redacted here rather than left to the JSON formatter so it holds under
    `LOG_FORMAT=text` too."""
    import logging

    engine, factory = await outbox(tmp_path)

    class BrokenTransport:
        async def send(self, message: OutgoingMessage) -> None:
            raise RuntimeError("relay refused")

    try:
        with caplog.at_level(logging.WARNING, logger="app.auth.mail"):
            at = datetime.now(timezone.utc)
            for _ in range(MAX_ATTEMPTS):
                await deliver_pending(factory, transport=BrokenTransport(), now=at)
                at += timedelta(hours=3)
        assert "player0@example.test" not in caplog.text
        assert "***@example.test" in caplog.text
        # Still diagnosable: the template and the relay's own answer.
        assert "relay refused" in caplog.text
    finally:
        await engine.dispose()


async def test_a_relay_that_names_the_recipient_in_its_refusal_is_redacted_too(
    tmp_path, caplog
):
    """`SMTPRecipientsRefused` stringifies with the address inside it, so the
    error a relay hands back carries the recipient whether or not the line
    reporting it redacts the one on the outbox row. Redacted where the string
    is made, so the log line and `last_error` - a column kept 30 days - are
    both safe under `LOG_FORMAT=text`, which switches the JSON formatter's
    redaction off."""
    import logging

    engine, factory = await outbox(tmp_path)

    class RefusingTransport:
        async def send(self, message: OutgoingMessage) -> None:
            raise smtplib.SMTPRecipientsRefused(
                {message.to_address: (550, b"5.1.1 no such mailbox")}
            )

    try:
        with caplog.at_level(logging.WARNING, logger="app.auth.mail"):
            at = datetime.now(timezone.utc)
            for _ in range(MAX_ATTEMPTS):
                await deliver_pending(factory, transport=RefusingTransport(), now=at)
                at += timedelta(hours=3)
        assert "player0@example.test" not in caplog.text
        assert "***@example.test" in caplog.text
        # And the same string as it was stored, not only as it was logged.
        async with factory() as session:
            entry = await session.scalar(select(EmailOutboxEntry))
        assert entry.state == EmailOutboxState.FAILED.value
        assert "player0@example.test" not in entry.last_error
        # Still the relay's own answer, which is what diagnoses this.
        assert "5.1.1" in entry.last_error
    finally:
        await engine.dispose()


async def test_a_long_relay_error_cannot_be_cut_into_a_visible_address(tmp_path):
    """`last_error` is a 256-character column. Redacting after that cut would
    let it land inside the address - past the `@`, before enough of the domain
    for the pattern to recognise one - and leave the local part standing.
    Redacting first spends the budget on text that is already safe.

    The padding is the length that tells the two orders apart; a relay that
    answers at length before naming who it refused is the real shape of it.
    """
    engine, factory = await outbox(tmp_path)

    class VerboseTransport:
        async def send(self, message: OutgoingMessage) -> None:
            raise RuntimeError("x" * 239 + message.to_address)

    try:
        at = datetime.now(timezone.utc)
        for _ in range(MAX_ATTEMPTS):
            await deliver_pending(factory, transport=VerboseTransport(), now=at)
            at += timedelta(hours=3)
        async with factory() as session:
            entry = await session.scalar(select(EmailOutboxEntry))
        assert entry.state == EmailOutboxState.FAILED.value
        assert "player0@" not in entry.last_error
    finally:
        await engine.dispose()


# The local parts are a sentinel rather than a name, so the assertion can be
# "no fragment of it survives" rather than "the whole of it does not" - the
# pattern this replaces masked `foo!bar@x` as `foo!***@x`, which passes the
# weaker check while leaking the half that identifies somebody.
@pytest.mark.parametrize(
    "address",
    [
        "zqx!zqx@example.test",
        '"zqx"@example.test',
        "zqx'zqx@example.test",
        "zqx@a.b",
        "a=zqx#{zqx}@example.test",
    ],
)
async def test_any_address_the_account_layer_stores_is_masked_on_the_way_out(
    tmp_path, caplog, address
):
    """`normalize_email` asks only for a non-blank local part, an `@`, and a
    domain with a dot in it. The recipient is masked by splitting the address
    this row already holds, not by finding one in text, so the shapes that
    slip past a pattern - a local part with atext specials in it, a quoted
    one, a single-character final label - are masked here the same as any
    other, in the log line and in `last_error` alike."""
    import logging

    engine = create_db_engine(f"sqlite+aiosqlite:///{tmp_path / 'shapes.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, checkfirst=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            queue_email(
                session,
                to_address=address,
                template=EmailTemplate.VERIFY_EMAIL,
                payload={"displayName": "Player", "token": "t"},
            )

    _, _, domain = address.rpartition("@")

    class RefusingTransport:
        async def send(self, message: OutgoingMessage) -> None:
            raise smtplib.SMTPRecipientsRefused(
                {message.to_address: (550, b"5.1.1 no such mailbox")}
            )

    try:
        with caplog.at_level(logging.WARNING, logger="app.auth.mail"):
            at = datetime.now(timezone.utc)
            for _ in range(MAX_ATTEMPTS):
                await deliver_pending(factory, transport=RefusingTransport(), now=at)
                at += timedelta(hours=3)
        async with factory() as session:
            entry = await session.scalar(select(EmailOutboxEntry))
        assert entry.state == EmailOutboxState.FAILED.value
        for written in (caplog.text, entry.last_error):
            assert "zqx" not in written
            # The domain stays: it is what says which relay was involved.
            assert f"***@{domain}" in written
        assert "5.1.1" in entry.last_error
    finally:
        await engine.dispose()


async def test_a_recipient_whose_domain_could_be_read_as_a_backreference(tmp_path):
    """The mask carries a domain this process did not choose. Substituted by
    a function rather than a replacement string, so a backslash in it is a
    character and not a group reference."""
    engine = create_db_engine(f"sqlite+aiosqlite:///{tmp_path / 'odd.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, checkfirst=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    address = "player@ex\\1ample.test"
    async with factory() as session:
        async with session.begin():
            queue_email(
                session,
                to_address=address,
                template=EmailTemplate.VERIFY_EMAIL,
                payload={"displayName": "Player", "token": "t"},
            )

    class RefusingTransport:
        async def send(self, message: OutgoingMessage) -> None:
            raise RuntimeError(f"550 no mailbox {message.to_address}")

    try:
        at = datetime.now(timezone.utc)
        for _ in range(MAX_ATTEMPTS):
            await deliver_pending(factory, transport=RefusingTransport(), now=at)
            at += timedelta(hours=3)
        async with factory() as session:
            entry = await session.scalar(select(EmailOutboxEntry))
        assert entry.state == EmailOutboxState.FAILED.value
        assert "player@" not in entry.last_error
    finally:
        await engine.dispose()


def test_a_suspension_mail_says_what_it_was_and_when_it_lifts():
    """The only message that reaches an account once it cannot sign in. It
    carries no evidence: their own words stay behind the sign-in rather than
    in an inbox we do not control and an outbox row that keeps them for
    thirty days (R-MOD-19)."""
    subject, body = render(
        EmailTemplate.ACCOUNT_BANNED.value,
        {
            "displayName": "Ada",
            "reason": "Repeated abuse in chat.",
            "category": "harassment",
            "expiresAt": "2026-09-16T12:00:00+00:00",
        },
        "https://example.test",
    )
    assert "suspended" in subject.lower()
    assert "Repeated abuse in chat." in body
    assert "harassment" in body
    # The thing a suspended player most needs.
    assert "16 Sep 2026" in body
    assert "Signing in will show you what it was about." in body


def test_a_suspension_mail_without_an_end_date_says_so():
    _, body = render(
        EmailTemplate.ACCOUNT_BANNED.value,
        {"displayName": "Ada", "reason": "Enough.", "expiresAt": None},
        "https://example.test",
    )
    assert "does not expire on its own" in body
    # No category recorded, so none is claimed.
    assert "recorded as" not in body.lower()


def test_a_suspension_mail_survives_a_timestamp_it_cannot_read():
    """A mail that renders the raw string beats one that raises on send."""
    _, body = render(
        EmailTemplate.ACCOUNT_BANNED.value,
        {"displayName": "Ada", "reason": "Enough.", "expiresAt": "not a date"},
        "https://example.test",
    )
    assert "not a date" in body
