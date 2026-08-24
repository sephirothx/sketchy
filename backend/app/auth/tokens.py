"""One-shot tokens for flows that leave the app and come back.

Password reset and email verification are the same mechanism wearing two
labels: issue a high-entropy secret, mail it, accept it exactly once before it
expires. Only the digest is stored, for the reason a password hash is - the row
exists to check a token somebody presents, never to reproduce one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthToken
from app.domain_values import AuthTokenPurpose


TOKEN_BYTES = 32

# A reset window short enough that a mailbox left open on a shared machine
# stops being a way in, and long enough to survive a slow relay. Verification
# is not a credential in the same way - it proves an address the account
# already asked to use - so it is given the day someone might take to notice
# the message.
TOKEN_TTL = {
    AuthTokenPurpose.PASSWORD_RESET: timedelta(hours=1),
    AuthTokenPurpose.EMAIL_VERIFY: timedelta(days=1),
}


@dataclass(frozen=True)
class IssuedToken:
    """The secret to mail, and the row that will recognise it."""

    token: str
    expires_at: datetime


def hash_token(token: str) -> str:
    """One-way digest for a high-entropy token; raw tokens never enter storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue_token(
    session: AsyncSession,
    *,
    user_id: UUID,
    purpose: AuthTokenPurpose,
    email: str | None = None,
    requested_ip_hash: str | None = None,
    now: datetime | None = None,
) -> IssuedToken:
    """Mint a token, retiring any earlier one for the same account and purpose.

    Retiring rather than accumulating: two live reset links are two ways in,
    and the second request is the one the person is actually waiting for.
    """
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + TOKEN_TTL[purpose]
    await session.execute(
        delete(AuthToken).where(
            AuthToken.user_id == user_id,
            AuthToken.purpose == purpose.value,
        )
    )
    token = secrets.token_urlsafe(TOKEN_BYTES)
    session.add(
        AuthToken(
            token_hash=hash_token(token),
            purpose=purpose.value,
            user_id=user_id,
            email=email,
            expires_at=expires_at,
            requested_ip_hash=requested_ip_hash,
        )
    )
    return IssuedToken(token=token, expires_at=expires_at)


async def consume_token(
    session: AsyncSession,
    *,
    token: str,
    purpose: AuthTokenPurpose,
    now: datetime | None = None,
) -> AuthToken | None:
    """Accept a token once, or refuse it.

    The row is deleted rather than marked consumed. `consumed_at` exists for a
    token that has to be shown as spent - none does today - and keeping the
    table empty of spent rows is what stops it growing without bound.
    """
    checked_at = now or datetime.now(timezone.utc)
    record = await session.scalar(
        select(AuthToken).where(
            AuthToken.token_hash == hash_token(token),
            AuthToken.purpose == purpose.value,
        )
    )
    if record is None:
        return None
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    await session.delete(record)
    if expires_at <= checked_at or record.consumed_at is not None:
        return None
    return record


async def token_is_usable(
    session: AsyncSession,
    *,
    token: str,
    purpose: AuthTokenPurpose,
    now: datetime | None = None,
) -> bool:
    """Would this token be accepted, without accepting it?

    Deliberately separate from `consume_token`, which deletes the row it looked
    up. A page that checks a link on arrival must not be the thing that spends
    it - the person has not chosen a password yet.

    This answers no faster than yes for a token that never existed, which is
    not a leak worth avoiding: the token is 32 random bytes, so anyone able to
    tell them apart could simply present one.
    """
    checked_at = now or datetime.now(timezone.utc)
    record = await session.scalar(
        select(AuthToken).where(
            AuthToken.token_hash == hash_token(token),
            AuthToken.purpose == purpose.value,
        )
    )
    if record is None or record.consumed_at is not None:
        return False
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > checked_at


async def purge_expired_tokens(
    session: AsyncSession, *, now: datetime | None = None
) -> int:
    """Drop tokens nobody can use any more."""
    checked_at = now or datetime.now(timezone.utc)
    result = await session.execute(
        delete(AuthToken).where(AuthToken.expires_at <= checked_at)
    )
    return int(result.rowcount or 0)
