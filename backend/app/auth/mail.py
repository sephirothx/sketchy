"""Queueing and delivery for the few messages this game ever sends.

Kept apart from `app.auth.email`, which decides what a stored address may look
like. This module decides how a message reaches one.

Nothing is sent inline. A ban that could not notify its subject is still a ban,
and a reset mail lost to a blinking relay is the one message a player will
certainly retry - so the intent is written down in the same transaction as the
action that caused it, and a sweeper carries it out afterwards. That also keeps
an unreachable SMTP server from turning a moderation action into a request that
hangs until it times out.

With no SMTP host configured the console transport logs the message instead.
That is the zero-configuration default the rest of the deployment story assumes
- embedded SQLite, generated signing key - and it means a self-hoster who never
sets up mail still sees what would have been sent.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import asyncio
import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Protocol
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import EmailOutboxEntry, generate_uuid
from app.domain_values import EmailOutboxState, EmailTemplate


logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
)
DEFAULT_BATCH_SIZE = 50
# How long a claimed message is left alone before another sweep may take it.
# Comfortably longer than a send, so a lease only expires when the process
# carrying it did not come back.
CLAIM_LEASE = timedelta(minutes=5)
# One slow recipient used to delay every message behind it. A handful at a
# time is enough to drain a batch in seconds without opening a connection per
# message to a relay that will rate-limit us for it.
MAX_CONCURRENT_SENDS = 5


@dataclass(frozen=True)
class OutgoingMessage:
    to_address: str
    subject: str
    body: str
    # Derived from the outbox row rather than left to the relay, so the same
    # row sent twice is one message with one identity. Delivery is claimed
    # before it is attempted and recorded after, and a process that dies in
    # between leaves a row that will be sent again - this is what makes that
    # second send a duplicate a mail client can collapse rather than a second
    # message.
    message_id: str | None = None


def public_base_url(environ: Mapping[str, str] | None = None) -> str:
    values = os.environ if environ is None else environ
    return values.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


def sender_address(environ: Mapping[str, str] | None = None) -> str:
    values = os.environ if environ is None else environ
    return values.get("SMTP_FROM", "sketchy@localhost")


# Rendering lives here rather than in templates on disk because there are five
# messages and they are all four lines long. A template engine would be more
# machinery than content.
def render(template: str, payload: Mapping[str, object], base_url: str) -> tuple[str, str]:
    name = payload.get("displayName") or "there"
    if template == EmailTemplate.VERIFY_EMAIL.value:
        link = f"{base_url}/verify-email?token={payload.get('token')}"
        return (
            "Confirm your Sketchy email address",
            f"Hi {name},\n\n"
            f"Confirm this address so you can recover your account if you ever "
            f"lose your password:\n\n{link}\n\n"
            f"The link works for one day. If you did not ask for this, nothing "
            f"has changed and you can ignore this message.\n",
        )
    if template == EmailTemplate.RESET_PASSWORD.value:
        link = f"{base_url}/reset-password?token={payload.get('token')}"
        return (
            "Reset your Sketchy password",
            f"Hi {name},\n\n"
            f"Choose a new password here:\n\n{link}\n\n"
            f"The link works for one hour and can be used once. If you did not "
            f"ask for it, your password has not changed and you can ignore "
            f"this message.\n",
        )
    if template == EmailTemplate.PASSWORD_CHANGED.value:
        return (
            "Your Sketchy password was changed",
            f"Hi {name},\n\n"
            f"Your password has just been changed and every signed-in device "
            f"has been signed out.\n\n"
            f"If this was not you, reset your password immediately at "
            f"{base_url}/forgot-password.\n",
        )
    if template == EmailTemplate.ACCOUNT_BANNED.value:
        reason = payload.get("reason") or "a breach of the rules"
        return (
            "Your Sketchy account has been suspended",
            f"Hi {name},\n\nYour account has been suspended for {reason}.\n",
        )
    if template == EmailTemplate.CONTENT_HIDDEN.value:
        what = payload.get("what") or "some content you shared"
        return (
            "Content of yours was hidden",
            f"Hi {name},\n\n{what} has been hidden after a moderation review.\n",
        )
    raise ValueError(f"no renderer for email template {template!r}")


class EmailTransport(Protocol):
    async def send(self, message: OutgoingMessage) -> None: ...


class ConsoleTransport:
    """The zero-configuration default: log what would have been sent."""

    async def send(self, message: OutgoingMessage) -> None:
        logger.info(
            "email (not sent, no SMTP configured) to=%s subject=%s\n%s",
            message.to_address,
            message.subject,
            message.body,
        )


class MemoryTransport:
    """Collects messages so a test can read them."""

    def __init__(self) -> None:
        self.sent: list[OutgoingMessage] = []

    async def send(self, message: OutgoingMessage) -> None:
        self.sent.append(message)


class SmtpTransport:
    """stdlib smtplib on a worker thread.

    A dedicated async SMTP client would be one more dependency for five short
    messages a day, and the sweeper is already off the request path.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool,
        sender: str,
        timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._sender = sender
        self._timeout = timeout

    def _send_blocking(self, message: OutgoingMessage) -> None:
        payload = EmailMessage()
        payload["From"] = self._sender
        payload["To"] = message.to_address
        payload["Subject"] = message.subject
        if message.message_id:
            payload["Message-ID"] = message.message_id
        payload.set_content(message.body)
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as client:
            if self._use_tls:
                client.starttls()
            if self._username and self._password:
                client.login(self._username, self._password)
            client.send_message(payload)

    async def send(self, message: OutgoingMessage) -> None:
        await asyncio.to_thread(self._send_blocking, message)


def transport_from_environment(
    environ: Mapping[str, str] | None = None,
) -> EmailTransport:
    values = os.environ if environ is None else environ
    host = values.get("SMTP_HOST", "").strip()
    if not host:
        return ConsoleTransport()
    return SmtpTransport(
        host=host,
        port=int(values.get("SMTP_PORT", "587")),
        username=values.get("SMTP_USERNAME") or None,
        password=values.get("SMTP_PASSWORD") or None,
        use_tls=values.get("SMTP_STARTTLS", "1") not in {"0", "false", "no"},
        sender=sender_address(values),
    )


def mail_is_configured(environ: Mapping[str, str] | None = None) -> bool:
    values = os.environ if environ is None else environ
    return bool(values.get("SMTP_HOST", "").strip())


def queue_email(
    session: AsyncSession,
    *,
    to_address: str,
    template: EmailTemplate,
    payload: Mapping[str, object],
    user_id: UUID | None = None,
    now: datetime | None = None,
) -> EmailOutboxEntry:
    """Record a message to send, in the caller's transaction."""
    entry = EmailOutboxEntry(
        id=generate_uuid(),
        to_address=to_address,
        user_id=user_id,
        template=template.value,
        payload=dict(payload),
        state=EmailOutboxState.PENDING.value,
        next_attempt_at=now or datetime.now(timezone.utc),
    )
    session.add(entry)
    return entry


@dataclass(frozen=True)
class DeliveryResult:
    attempted: int
    sent: int
    failed: int
    deferred: int


@dataclass(frozen=True)
class _Claim:
    """One message this sweep has taken responsibility for sending."""

    id: UUID
    to_address: str
    template: str
    payload: dict
    attempts: int


def message_id_for(entry_id: UUID, sender: str | None = None) -> str:
    """A stable RFC 5322 identity for an outbox row."""
    domain = (sender or sender_address()).rpartition("@")[2] or "localhost"
    return f"<{entry_id}@{domain}>"


async def _claim_due(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    batch_size: int,
    checked_at: datetime,
) -> list[_Claim]:
    """Take a batch of due messages, in one short transaction, and let go.

    The claim is a lease on `next_attempt_at` rather than a new state: pushing
    the next attempt out is what stops a second sweep taking the same row, and
    a process that dies mid-send leaves a row that simply comes due again.
    A `SELECT ... FOR UPDATE SKIP LOCKED` would say this more directly on
    PostgreSQL and be silently ignored on SQLite, so the claim is a conditional
    UPDATE that means the same thing on both.

    The attempt is counted here rather than after the send, so a message whose
    process dies while sending it costs an attempt. That is the safe direction:
    the alternative is a message that can be retried for ever by crashing.
    """
    lease_until = checked_at + CLAIM_LEASE
    claims: list[_Claim] = []
    async with session_factory() as session:
        async with session.begin():
            due = (
                await session.scalars(
                    select(EmailOutboxEntry)
                    .where(
                        EmailOutboxEntry.state == EmailOutboxState.PENDING.value,
                        EmailOutboxEntry.next_attempt_at <= checked_at,
                    )
                    .order_by(EmailOutboxEntry.created_at)
                    .limit(batch_size)
                )
            ).all()
            for entry in due:
                won = await session.execute(
                    update(EmailOutboxEntry)
                    .where(
                        EmailOutboxEntry.id == entry.id,
                        EmailOutboxEntry.state == EmailOutboxState.PENDING.value,
                        EmailOutboxEntry.next_attempt_at <= checked_at,
                    )
                    .values(
                        attempts=EmailOutboxEntry.attempts + 1,
                        next_attempt_at=lease_until,
                    )
                    .execution_options(synchronize_session=False)
                )
                if won.rowcount == 1:
                    claims.append(
                        _Claim(
                            id=entry.id,
                            to_address=entry.to_address,
                            template=entry.template,
                            payload=dict(entry.payload),
                            attempts=entry.attempts + 1,
                        )
                    )
    return claims


async def _record_sent(
    session_factory: async_sessionmaker[AsyncSession],
    claim: _Claim,
    *,
    checked_at: datetime,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                update(EmailOutboxEntry)
                .where(EmailOutboxEntry.id == claim.id)
                .values(
                    state=EmailOutboxState.SENT.value,
                    sent_at=checked_at,
                    last_error=None,
                )
                .execution_options(synchronize_session=False)
            )


async def _record_failure(
    session_factory: async_sessionmaker[AsyncSession],
    claim: _Claim,
    error: str,
    *,
    checked_at: datetime,
) -> bool:
    """Reschedule or give up on one message. True when it was given up on."""
    given_up = claim.attempts >= MAX_ATTEMPTS
    values: dict[str, object] = {"last_error": error}
    if given_up:
        values["state"] = EmailOutboxState.FAILED.value
    else:
        backoff = RETRY_BACKOFF[min(claim.attempts - 1, len(RETRY_BACKOFF) - 1)]
        values["next_attempt_at"] = checked_at + backoff
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                update(EmailOutboxEntry)
                .where(EmailOutboxEntry.id == claim.id)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
    return given_up


async def deliver_pending(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    transport: EmailTransport | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    now: datetime | None = None,
    base_url: str | None = None,
) -> DeliveryResult:
    """Send what is due, and reschedule what fails.

    Claim, send, record - three phases, and the network is in the one that
    holds no transaction. Everything used to happen inside a single one: a
    batch of fifty against a relay timing out at ten seconds held it open for
    minutes, which on SQLite blocks every writer and on PostgreSQL keeps a
    connection and its locks for the duration.

    A message that keeps failing is given up on rather than retried for ever,
    and the row is kept as `failed` with its last error, so a silent mail
    misconfiguration is visible instead of merely quiet.
    """
    carrier = transport or transport_from_environment()
    links_from = base_url or public_base_url()
    checked_at = now or datetime.now(timezone.utc)
    claimed = await _claim_due(
        session_factory, batch_size=batch_size, checked_at=checked_at
    )
    if not claimed:
        return DeliveryResult(attempted=0, sent=0, failed=0, deferred=0)

    at_once = asyncio.Semaphore(MAX_CONCURRENT_SENDS)
    sender = sender_address()

    async def attempt(claim: _Claim) -> tuple[_Claim, str | None]:
        async with at_once:
            try:
                subject, body = render(claim.template, claim.payload, links_from)
                await carrier.send(
                    OutgoingMessage(
                        to_address=claim.to_address,
                        subject=subject,
                        body=body,
                        message_id=message_id_for(claim.id, sender),
                    )
                )
            except Exception as error:  # noqa: BLE001 - recorded, not swallowed
                # Rendering is inside the try on purpose: a row whose template
                # no longer exists is one bad message, not a dead sweep.
                return claim, str(error)[:256]
            return claim, None

    outcomes = await asyncio.gather(*(attempt(claim) for claim in claimed))

    sent = failed = deferred = 0
    for claim, error in outcomes:
        if error is None:
            await _record_sent(session_factory, claim, checked_at=checked_at)
            sent += 1
            continue
        if await _record_failure(session_factory, claim, error, checked_at=checked_at):
            failed += 1
            logger.warning(
                "giving up on %s to %s after %d attempts: %s",
                claim.template,
                claim.to_address,
                claim.attempts,
                error,
            )
        else:
            deferred += 1
    return DeliveryResult(
        attempted=len(claimed), sent=sent, failed=failed, deferred=deferred
    )
