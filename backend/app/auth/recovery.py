"""Getting back into an account whose password is gone.

The profile page invites guests to claim an account so their history carries
over, and until now the account they claimed could not be recovered: a lost
password lost everything behind it. This closes that, by the only channel a
player can use unaided.

Two rules shape everything here.

An address is written to `users.email` only once it has been proved. An
unverified address is held in the token instead, so a typo cannot hand the
account to whoever owns the address that was typed, and nobody can reserve a
mailbox they do not control.

A reset request answers the same way whether or not the account exists. The
response is not a place to learn which usernames are real.

Deployments with no SMTP configured are covered by `app.auth.password_reset`,
the operator command - not by recovery codes, which are one more thing to lose.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.email import EmailAddressError, normalize_email
from app.auth.mail import queue_email
from app.auth.sessions import revoke_all_sessions
from app.auth.tokens import (
    AuthTokenPurpose,
    consume_token,
    issue_token,
    token_is_usable,
)
from app.db.models import AuditEvent, User, UserSettings, generate_uuid
from app.domain_values import AccountState, AuditTargetType, EmailTemplate


# Long enough that it reads as a standing note rather than nagging, short
# enough that somebody who joins, plays for a month and forgets their password
# has been told more than once.
REMINDER_INTERVAL = timedelta(days=7)


class RecoveryError(RuntimeError):
    """A recovery step the caller must be told about by name."""


class EmailAlreadyInUse(RecoveryError):
    """Another account has already proved this address."""


@dataclass(frozen=True)
class EmailState:
    address: str | None
    verified: bool
    pending_address: str | None
    reminder_due: bool


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


async def _address_taken(
    session: AsyncSession, address: str, *, except_user_id: UUID
) -> bool:
    """Is this address already proved by somebody else?

    Only a verified address blocks: an unproved one lives in a token and
    reserves nothing, which is what stops one account from squatting on
    another person's mailbox.
    """
    owner = await session.scalar(
        select(User.id).where(
            func.lower(User.email) == address,
            User.email_verified_at.is_not(None),
            User.id != except_user_id,
        )
    )
    return owner is not None


async def email_state(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    now: datetime | None = None,
) -> EmailState:
    """What the account knows about its own recovery address."""
    from app.db.models import AuthToken

    checked_at = now or datetime.now(timezone.utc)
    async with session_factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            return EmailState(None, False, None, False)
        pending = await session.scalar(
            select(AuthToken.email).where(
                AuthToken.user_id == user_id,
                AuthToken.purpose == AuthTokenPurpose.EMAIL_VERIFY.value,
                AuthToken.expires_at > checked_at,
            )
        )
        settings = await session.get(UserSettings, user_id)
        last_shown = _aware(
            settings.email_reminder_last_shown_at if settings else None
        )
        # A guest has nothing to recover yet - claiming the account is the
        # step being asked for there, not an address.
        registered = user.state == AccountState.REGISTERED.value
        needs_address = user.email is None or user.email_verified_at is None
        due = (
            registered
            and needs_address
            and (last_shown is None or checked_at - last_shown >= REMINDER_INTERVAL)
        )
        return EmailState(
            address=user.email,
            verified=user.email_verified_at is not None,
            pending_address=pending,
            reminder_due=due,
        )


async def mark_reminder_shown(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    now: datetime | None = None,
) -> None:
    """Start the clock again, so the note returns rather than repeats."""
    shown_at = now or datetime.now(timezone.utc)
    async with session_factory() as session:
        async with session.begin():
            settings = await session.get(UserSettings, user_id)
            if settings is None:
                settings = UserSettings(user_id=user_id)
                session.add(settings)
            settings.email_reminder_last_shown_at = shown_at


async def request_email_verification(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    email: str,
    ip_hash: str | None = None,
    request_id: str | None = None,
    now: datetime | None = None,
) -> str:
    """Send a proof-of-address message, without recording the address yet."""
    address = normalize_email(email)
    if address is None:
        raise EmailAddressError("Email is not valid.")
    async with session_factory() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            if user is None or user.state != AccountState.REGISTERED.value:
                raise RecoveryError("Create an account before adding an email.")
            if await _address_taken(session, address, except_user_id=user_id):
                raise EmailAlreadyInUse("That email is already in use.")
            issued = await issue_token(
                session,
                user_id=user_id,
                purpose=AuthTokenPurpose.EMAIL_VERIFY,
                email=address,
                requested_ip_hash=ip_hash,
                now=now,
            )
            queue_email(
                session,
                to_address=address,
                template=EmailTemplate.VERIFY_EMAIL,
                payload={"token": issued.token, "displayName": user.display_name},
                user_id=user_id,
                now=now,
            )
            session.add(
                AuditEvent(
                    id=generate_uuid(),
                    event_type="account.email_verification_requested",
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    target_type=AuditTargetType.USER.value,
                    target_id=str(user_id),
                    request_id=request_id,
                    ip_hash=ip_hash,
                    details={},
                )
            )
    return address


async def confirm_email(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    token: str,
    ip_hash: str | None = None,
    request_id: str | None = None,
    now: datetime | None = None,
) -> str | None:
    """Accept a proof and record the address. Returns the address, or None."""
    async with session_factory() as session:
        async with session.begin():
            record = await consume_token(
                session, token=token, purpose=AuthTokenPurpose.EMAIL_VERIFY, now=now
            )
            if record is None or record.email is None:
                return None
            user = await session.get(User, record.user_id)
            if user is None:
                return None
            # Somebody may have proved the same address between issuing this
            # token and presenting it.
            if await _address_taken(
                session, record.email, except_user_id=record.user_id
            ):
                raise EmailAlreadyInUse("That email is already in use.")
            user.email = record.email
            user.email_verified_at = now or datetime.now(timezone.utc)
            session.add(
                AuditEvent(
                    id=generate_uuid(),
                    event_type="account.email_verified",
                    actor_user_id=user.id,
                    target_user_id=user.id,
                    target_type=AuditTargetType.USER.value,
                    target_id=str(user.id),
                    request_id=request_id,
                    ip_hash=ip_hash,
                    details={},
                )
            )
            return record.email


async def request_password_reset(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    identifier: str,
    ip_hash: str | None = None,
    request_id: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Mail a reset link if the identifier resolves to a recoverable account.

    Returns whether anything was sent, for tests and the operator log only.
    Callers must answer the request identically either way.
    """
    lookup = identifier.strip().lower()
    if not lookup:
        return False
    async with session_factory() as session:
        async with session.begin():
            user = await session.scalar(
                select(User).where(
                    User.state == AccountState.REGISTERED.value,
                    (func.lower(User.username) == lookup)
                    | (
                        (func.lower(User.email) == lookup)
                        & User.email_verified_at.is_not(None)
                    ),
                )
            )
            # No verified address means no way to prove the request came from
            # the account's owner. The operator command exists for this.
            if user is None or user.email is None or user.email_verified_at is None:
                return False
            issued = await issue_token(
                session,
                user_id=user.id,
                purpose=AuthTokenPurpose.PASSWORD_RESET,
                requested_ip_hash=ip_hash,
                now=now,
            )
            queue_email(
                session,
                to_address=user.email,
                template=EmailTemplate.RESET_PASSWORD,
                payload={"token": issued.token, "displayName": user.display_name},
                user_id=user.id,
                now=now,
            )
            session.add(
                AuditEvent(
                    id=generate_uuid(),
                    event_type="account.password_reset_requested",
                    actor_user_id=None,
                    target_user_id=user.id,
                    target_type=AuditTargetType.USER.value,
                    target_id=str(user.id),
                    request_id=request_id,
                    ip_hash=ip_hash,
                    details={},
                )
            )
            return True


async def password_reset_link_is_usable(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    token: str,
    now: datetime | None = None,
) -> bool:
    """Whether a reset link would work, so a page can say so before asking.

    Being told a link is dead after choosing a password is being asked to do
    the work twice.
    """
    async with session_factory() as session:
        return await token_is_usable(
            session,
            token=token,
            purpose=AuthTokenPurpose.PASSWORD_RESET,
            now=now,
        )


async def reset_password(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    token: str,
    password_hash: str,
    ip_hash: str | None = None,
    request_id: str | None = None,
    now: datetime | None = None,
) -> UUID | None:
    """Set a new password and sign every device out. Returns the account id."""
    changed_at = now or datetime.now(timezone.utc)
    async with session_factory() as session:
        async with session.begin():
            record = await consume_token(
                session,
                token=token,
                purpose=AuthTokenPurpose.PASSWORD_RESET,
                now=changed_at,
            )
            if record is None:
                return None
            user = await session.get(User, record.user_id)
            if user is None or user.state != AccountState.REGISTERED.value:
                return None
            user.password_hash = password_hash
            if user.email and user.email_verified_at is not None:
                queue_email(
                    session,
                    to_address=user.email,
                    template=EmailTemplate.PASSWORD_CHANGED,
                    payload={"displayName": user.display_name},
                    user_id=user.id,
                    now=changed_at,
                )
            session.add(
                AuditEvent(
                    id=generate_uuid(),
                    event_type="account.password_reset",
                    actor_user_id=user.id,
                    target_user_id=user.id,
                    target_type=AuditTargetType.USER.value,
                    target_id=str(user.id),
                    request_id=request_id,
                    ip_hash=ip_hash,
                    details={},
                )
            )
            reset_user_id = user.id

    # Outside the transaction above: revoking opens its own, and a reset that
    # changed the password but left every session standing would be the one
    # failure worth avoiding here.
    await revoke_all_sessions(
        session_factory, user_id=str(reset_user_id), now=changed_at
    )
    return reset_user_id
