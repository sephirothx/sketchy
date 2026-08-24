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

from sqlalchemy import select
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


@dataclass(frozen=True)
class OutgoingMessage:
    to_address: str
    subject: str
    body: str


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


async def deliver_pending(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    transport: EmailTransport | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    now: datetime | None = None,
    base_url: str | None = None,
) -> DeliveryResult:
    """Send what is due, and reschedule what fails.

    A message that keeps failing is given up on rather than retried for ever,
    and the row is kept as `failed` with its last error, so a silent mail
    misconfiguration is visible instead of merely quiet.
    """
    carrier = transport or transport_from_environment()
    links_from = base_url or public_base_url()
    checked_at = now or datetime.now(timezone.utc)
    sent = failed = deferred = 0
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
                subject, body = render(entry.template, entry.payload, links_from)
                entry.attempts += 1
                try:
                    await carrier.send(
                        OutgoingMessage(
                            to_address=entry.to_address, subject=subject, body=body
                        )
                    )
                except Exception as error:  # noqa: BLE001 - recorded, not swallowed
                    entry.last_error = str(error)[:256]
                    if entry.attempts >= MAX_ATTEMPTS:
                        entry.state = EmailOutboxState.FAILED.value
                        failed += 1
                        logger.warning(
                            "giving up on %s to %s after %d attempts: %s",
                            entry.template,
                            entry.to_address,
                            entry.attempts,
                            entry.last_error,
                        )
                    else:
                        backoff = RETRY_BACKOFF[
                            min(entry.attempts - 1, len(RETRY_BACKOFF) - 1)
                        ]
                        entry.next_attempt_at = checked_at + backoff
                        deferred += 1
                else:
                    entry.state = EmailOutboxState.SENT.value
                    entry.sent_at = checked_at
                    entry.last_error = None
                    sent += 1
    return DeliveryResult(
        attempted=len(due), sent=sent, failed=failed, deferred=deferred
    )
