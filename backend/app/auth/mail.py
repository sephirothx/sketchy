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

Outside production only. A reset link in a log store is a credential in a
place nobody scoped for one, so `SKETCHY_ENV=production` refuses to start
without a relay (`deployment.validate_mail_configuration`) and the console
transport refuses to write a body there even if something reaches it anyway
(#466).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import asyncio
import logging
import os
import re
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.deployment import is_production, public_base_url
from app.logging_config import redact
from app.services.sweeps import (
    SweepBudget,
    SweepReport,
    delete_in_batches,
    overdue_probe,
    sweep_budget_from_env,
)
from app.db.models import EmailOutboxEntry, UserSettings, generate_uuid
from app.auth.mail_copy import copy_for
from app.domain_values import EmailOutboxState, EmailTemplate, InterfaceLocale


logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
)
DEFAULT_BATCH_SIZE = 50
# How long a delivered or given-up row is kept as a delivery record. Long
# enough to answer "did the mail go out" for any dispute that is still live,
# and aligned with the 30-day window retained messages already use. A row
# past it is a list of addresses, not evidence.
OUTBOX_RETENTION = timedelta(days=30)
PURGE_BATCH_SIZE = 500
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


def sender_address(environ: Mapping[str, str] | None = None) -> str:
    values = os.environ if environ is None else environ
    return values.get("SMTP_FROM", "sketchy@localhost")


# Rendering lives here rather than in templates on disk because there are five
# messages and they are all four lines long. A template engine would be more
# machinery than content. The *words* moved to `mail_copy.py` when there
# became seven languages of them (#766); the assembly stayed here, so a
# locale supplies sentences and never has to know how they are put together.
def render(
    template: str,
    payload: Mapping[str, object],
    base_url: str,
    locale: str | None = None,
) -> tuple[str, str]:
    """The subject and body for one message, in the language it was queued in.

    `locale` is the row's, frozen when the message was queued rather than
    resolved now: the sweep can run hours later, and a preference changed in
    between must not re-language a message that was already composed - least
    of all the one about the security event that prompted the change
    (R-I18N-08).
    """
    words = copy_for(locale)
    name = payload.get("displayName")
    greeting = words.greeting.format(name=name) if name else words.greeting_unnamed
    if template == EmailTemplate.VERIFY_EMAIL.value:
        link = f"{base_url}/verify-email?token={payload.get('token')}"
        return (
            words.verify_subject,
            f"{greeting}\n\n{words.verify_body.format(link=link)}\n",
        )
    if template == EmailTemplate.RESET_PASSWORD.value:
        link = f"{base_url}/reset-password?token={payload.get('token')}"
        return (
            words.reset_subject,
            f"{greeting}\n\n{words.reset_body.format(link=link)}\n",
        )
    if template == EmailTemplate.PASSWORD_CHANGED.value:
        return (
            words.changed_subject,
            f"{greeting}\n\n"
            f"{words.changed_body.format(link=f'{base_url}/forgot-password')}\n",
        )
    if template == EmailTemplate.ACCOUNT_BANNED.value:
        reason = payload.get("reason") or words.banned_default_reason
        # The one thing a suspended account most needs, and the only message
        # that reaches it once it cannot sign in: whether this ends. Without
        # it, "suspended for spam" reads as permanent when it is usually a day.
        # Both clauses are built from the locale's own words rather than
        # handed to it in English (R-I18N-02).
        expires_at = payload.get("expiresAt")
        when = (
            words.banned_until.format(date=_readable_date(expires_at))
            if expires_at
            else words.banned_forever
        )
        category = payload.get("category")
        about = (
            words.banned_about.format(category=str(category).replace("_", " "))
            if category
            else ""
        )
        # No evidence in the mail. Their own words stay behind the sign-in,
        # where the notice shows them, rather than in an inbox we do not
        # control and an outbox row that keeps them for thirty days.
        return (
            words.banned_subject,
            f"{greeting}\n\n"
            f"{words.banned_body.format(reason=reason, about=about, when=when)}\n",
        )
    if template == EmailTemplate.CONTENT_HIDDEN.value:
        # A kind, not a phrase: older rows queued before #766 carry the
        # English sentence itself, and are rendered as they were written
        # rather than mangled into a category that did not exist yet.
        kinds = {
            "prompt": words.hidden_prompt,
            "prompt_list": words.hidden_prompt_list,
        }
        raw = payload.get("what")
        what = kinds.get(str(raw), str(raw)) if raw else words.hidden_default_what
        return (
            words.hidden_subject,
            f"{greeting}\n\n{words.hidden_body.format(what=what)}\n",
        )
    raise ValueError(f"no renderer for email template {template!r}")


class EmailTransport(Protocol):
    async def send(self, message: OutgoingMessage) -> None: ...


class ConsoleTransport:
    """The zero-configuration default: log what would have been sent.

    The whole body, unredacted, link token included - that is the point of it
    on a checkout with no relay, and `LOG_FORMAT=text` leaves it readable so
    the account flow can actually be completed there.

    Which is precisely why it must not run in production, where the same line
    puts a live reset link into a log store kept longer than the hour the
    token lives and readable by everyone with access to it. Startup already
    refuses a production process with no relay; this is the second lock, on
    the one statement that writes a body, so the prohibition holds for any
    caller that builds a console transport by hand. Raising rather than
    logging a redacted line leaves a failed outbox row with the reason on it,
    which is a misconfiguration somebody can see.
    """

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = environ

    async def send(self, message: OutgoingMessage) -> None:
        if is_production(self._environ):
            raise RuntimeError(
                "the console transport logs the message body and must not run "
                "in production; configure SMTP_HOST"
            )
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
        # Handed the same mapping, so the transport judges the environment
        # this selection was made from rather than a live one that may have
        # been monkeypatched apart from it.
        return ConsoleTransport(values)
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


async def recipient_locale(session: AsyncSession, user_id: UUID | None) -> str:
    """The language this account reads in, for a message about to be queued.

    Read once, here, and written onto the row: everything after that point
    uses the frozen value (R-I18N-08). English for an account with no
    settings row - a guest being told something, or one that never opened
    Settings - which is what it would have been written in anyway.
    """
    if user_id is None:
        return InterfaceLocale.ENGLISH.value
    locale = await session.scalar(
        select(UserSettings.locale).where(UserSettings.user_id == user_id)
    )
    return locale or InterfaceLocale.ENGLISH.value


def queue_email(
    session: AsyncSession,
    *,
    to_address: str,
    template: EmailTemplate,
    payload: Mapping[str, object],
    user_id: UUID | None = None,
    locale: str | None = None,
    now: datetime | None = None,
) -> EmailOutboxEntry:
    """Record a message to send, in the caller's transaction.

    `locale` is **frozen here**, not read when the sweep sends: the outbox is
    a durable queue and a send can happen hours later, so resolving late
    would let a preference changed in between re-language a message that was
    already composed (R-I18N-08). A caller with no locale to hand leaves it
    out and the message is written in English.
    """
    entry = EmailOutboxEntry(
        id=generate_uuid(),
        to_address=to_address,
        user_id=user_id,
        template=template.value,
        locale=(locale or InterfaceLocale.ENGLISH.value),
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
    # The language the row was queued in. Carried on the claim so the sweep
    # never has to ask the account again - which is the whole point of
    # freezing it (R-I18N-08).
    locale: str
    payload: dict
    attempts: int


def message_id_for(entry_id: UUID, sender: str | None = None) -> str:
    """A stable RFC 5322 identity for an outbox row.

    The sender is parsed rather than split on "@": `SMTP_FROM` is allowed to
    carry a display name, and `Sketchy <no-reply@example.test>` split naively
    yields a domain ending in ">" - an invalid Message-ID, which a relay may
    reject and which would defeat the deduplication this exists for.
    """
    address = parseaddr(sender or sender_address())[1]
    # `rpartition` hands back the whole string when there is no "@" at all, so
    # a misconfigured sender would otherwise become the domain.
    _, at, domain = address.rpartition("@")
    return f"<{entry_id}@{(domain.strip() if at else '') or 'localhost'}>"


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
                            locale=entry.locale,
                            payload=dict(entry.payload),
                            attempts=entry.attempts + 1,
                        )
                    )
    return claims


def _masked_recipient(address: str) -> str:
    """`***@domain` for a stored address, whatever shape it has.

    Split, not matched. `auth.email.normalize_email` accepts any non-blank
    local part before the last `@` and any domain with a dot in it, so the
    stored set includes `foo!bar@example.test`, `"foo"@example.test` and
    `foo@a.b` - none of which a pattern hunting an address inside arbitrary
    prose recognises without becoming wide enough to eat the prose. Here
    there is nothing to recognise: the address is known, and this is the
    same `rpartition` split `normalize_email` made when it accepted it.

    The domain survives because that is what says which relay or provider
    was involved, which is what a delivery failure is diagnosed from.
    """
    local, at, domain = address.rpartition("@")
    return f"***@{domain}" if at and local else "***"


def _without_recipient(text: str, address: str) -> str:
    """Take one known address out of arbitrary text, then the general pass.

    A relay's own answer carries the address it refused - `SMTPRecipientsRefused`
    stringifies the dict it was built with - and it is echoed back in whatever
    case it was typed, hence the fold. The general pass still runs, for a
    second address the relay mentioned and for anything else `redact` knows.

    The replacement is a function rather than a string because the mask
    carries a domain this process did not choose: a backslash in it would
    otherwise be read as a group reference.
    """
    if address:
        mask = _masked_recipient(address)
        text = re.sub(re.escape(address), lambda _: mask, text, flags=re.IGNORECASE)
    return redact(text)


def _readable_date(value: object) -> str:
    """A date somebody can read, in any language, or the raw string.

    ISO - `2026-09-11` - rather than `11 Sep 2026`, because the month name is
    the one part of a date that needs a locale database, and this project
    carries none. A date nobody can misread beats one that is charming in
    English and wrong in six other languages (R-I18N-08). A value that is not
    a timestamp renders as itself: a mail showing the raw string beats one
    that fails to send.
    """
    try:
        return datetime.fromisoformat(str(value)).date().isoformat()
    except (TypeError, ValueError):
        return str(value)


def _scrubbed(payload: Mapping[str, object]) -> dict:
    """The payload minus its secret, for a row no sweep will render again.

    `auth_tokens` stores only hashes precisely so the database never holds a
    replayable credential; the raw token has to ride the outbox row so a retry
    can rebuild the link, and this is where the ride ends. Scrubbing happens
    in the same update that makes the row terminal, so there is no state in
    which a row both says it is done and still carries the secret.
    """
    return {key: value for key, value in payload.items() if key != "token"}


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
                    payload=_scrubbed(claim.payload),
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
        # As terminal as sent: nothing will render this payload again, so a
        # kept token could only leak. A deferred row keeps its token, or the
        # retry the backoff promises would send a dead link.
        values["payload"] = _scrubbed(claim.payload)
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
                subject, body = render(
                    claim.template, claim.payload, links_from, claim.locale
                )
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
                #
                # Scrubbed before it is truncated, and here rather than at
                # the two places it is used. `SMTPRecipientsRefused`
                # stringifies with the address it refused inside it, so
                # masking the recipient beside this string would leave the
                # same address in the same line; and this is what
                # `last_error` stores, a column kept 30 days and read back by
                # an operator command. Truncating afterwards would let a
                # 256-character cut land mid-address and leave the local part
                # standing.
                return claim, _without_recipient(str(error), claim.to_address)[:256]
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
            # Masked at the call site rather than left to the JSON
            # formatter, so the line is safe under `LOG_FORMAT=text` too.
            # `error` arrives scrubbed already.
            logger.warning(
                "giving up on %s to %s after %d attempts: %s",
                claim.template,
                _masked_recipient(claim.to_address),
                claim.attempts,
                error,
            )
        else:
            deferred += 1
    return DeliveryResult(
        attempted=len(claimed), sent=sent, failed=failed, deferred=deferred
    )


async def purge_expired_outbox_entries(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    batch_size: int = PURGE_BATCH_SIZE,
    budget: SweepBudget | None = None,
) -> SweepReport:
    """Remove delivered and given-up rows past retention, in bounded batches.

    Only terminal rows: a pending row is still owed a delivery attempt or a
    give-up, however old it is, and purging one would silently drop mail.
    Sent rows age from the moment they were sent; failed rows have no
    terminal timestamp of their own, so they age from creation - which by
    then trails the give-up by at most the backoff ladder, hours against a
    thirty-day window. The two branches are written out rather than folded
    into one `coalesce`, so each can use an index on its own column; the
    meaning is the one `coalesce(sent_at, created_at) <= cutoff` had.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    cutoff = (now or datetime.now(timezone.utc)) - OUTBOX_RETENTION
    resolved = budget or sweep_budget_from_env()
    branch_budget = SweepBudget(
        rows=resolved.rows, batch=min(batch_size, resolved.batch), seconds=resolved.seconds
    )
    # Literal states rather than bound ones: the partial index over sent
    # rows only matches a plan whose predicate names 'sent' (#554).
    sent = await delete_in_batches(
        session_factory,
        name="email_outbox",
        candidates=select(EmailOutboxEntry.id)
        .where(
            EmailOutboxEntry.state == literal(EmailOutboxState.SENT.value, literal_execute=True),
            EmailOutboxEntry.sent_at <= cutoff,
        )
        .order_by(EmailOutboxEntry.sent_at, EmailOutboxEntry.id),
        delete_for=lambda ids: delete(EmailOutboxEntry).where(EmailOutboxEntry.id.in_(ids)),
        budget=branch_budget,
        probe=overdue_probe(
            EmailOutboxEntry.sent_at,
            EmailOutboxEntry.state == literal(EmailOutboxState.SENT.value, literal_execute=True),
            EmailOutboxEntry.sent_at <= cutoff,
        ),
        now=cutoff,
    )
    failed = await delete_in_batches(
        session_factory,
        name="email_outbox",
        candidates=select(EmailOutboxEntry.id)
        .where(
            EmailOutboxEntry.state == literal(EmailOutboxState.FAILED.value, literal_execute=True),
            EmailOutboxEntry.created_at <= cutoff,
        )
        .order_by(EmailOutboxEntry.created_at, EmailOutboxEntry.id),
        delete_for=lambda ids: delete(EmailOutboxEntry).where(EmailOutboxEntry.id.in_(ids)),
        budget=SweepBudget(
            rows=max(1, resolved.rows - int(sent)),
            batch=branch_budget.batch,
            seconds=max(0.001, resolved.seconds - sent.seconds),
        ),
        probe=overdue_probe(
            EmailOutboxEntry.created_at,
            EmailOutboxEntry.state == literal(EmailOutboxState.FAILED.value, literal_execute=True),
            EmailOutboxEntry.created_at <= cutoff,
        ),
        now=cutoff,
    )
    return SweepReport(
        int(sent) + int(failed),
        name="email_outbox",
        batches=sent.batches + failed.batches,
        seconds=sent.seconds + failed.seconds,
        exhausted=sent.exhausted or failed.exhausted,
        oldest_overdue_seconds=max(
            (value for value in (sent.oldest_overdue_seconds, failed.oldest_overdue_seconds) if value is not None),
            default=None,
        ),
        # Two branches over one table, so the table's backlog is their sum.
        backlog=(
            None
            if sent.backlog is None and failed.backlog is None
            else (sent.backlog or 0) + (failed.backlog or 0)
        ),
    )

