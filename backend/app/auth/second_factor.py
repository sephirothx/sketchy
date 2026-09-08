"""Enrolling, proving and revoking the second factor a staff account needs.

The rule this exists to enforce is R-AUTH-20: a moderator or administrator has
to hold something besides their password before their role does anything, and
R-AUTH-21: they have to use it again, inside a short window, for each action
that suspends somebody, changes a role, or reconfigures a live server.

Enrolment is deliberately two steps with nothing stored in between. The secret
is generated, handed to the browser once, and written only when a code
computed from it comes back - so a secret somebody generated and never
finished setting up is not a credential sitting in the database, and an
account cannot end up locked out by an enrolment it never completed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.totp import (
    MAX_SECOND_FACTOR_FAILURES,
    generate_recovery_codes,
    generate_secret,
    hash_recovery_code,
    matching_step,
    provisioning_uri,
)
from app.db.models import UserRecoveryCode, UserSecondFactor, generate_uuid


# Long enough to find the authenticator app and short enough that a machine
# grinding six digits gets nowhere. Failures are consecutive: one correct code
# clears the count.
SECOND_FACTOR_LOCKOUT = timedelta(minutes=15)


class SecondFactorOutcome(Enum):
    """What a proof attempt established."""

    ACCEPTED = "accepted"
    RECOVERY_CODE_SPENT = "recovery_code_spent"
    REJECTED = "rejected"
    LOCKED = "locked"
    NOT_ENROLLED = "not_enrolled"


@dataclass(frozen=True)
class EnrolmentOffer:
    """A secret held by the browser alone until a code proves it arrived."""

    secret: str
    uri: str


@dataclass(frozen=True)
class SecondFactorState:
    enrolled: bool
    confirmed_at: datetime | None = None
    recovery_codes_remaining: int = 0
    locked_until: datetime | None = None
    # Whether anybody proved the password while binding it. Only a staff role
    # asks (R-AUTH-20); an ordinary player never sees this.
    password_proved: bool = False


def begin_enrolment(*, account: str) -> EnrolmentOffer:
    """Offer a fresh secret. Nothing is written until it is confirmed."""
    secret = generate_secret()
    return EnrolmentOffer(secret=secret, uri=provisioning_uri(secret, account=account))


async def second_factor_state(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
) -> SecondFactorState:
    """What this account holds, without ever returning the secret itself."""
    async with session_factory() as database:
        record = await database.get(UserSecondFactor, UUID(user_id))
        if record is None:
            return SecondFactorState(enrolled=False)
        remaining = await database.scalar(
            select(func.count(UserRecoveryCode.id)).where(
                UserRecoveryCode.user_id == UUID(user_id),
                UserRecoveryCode.used_at.is_(None),
            )
        )
        return SecondFactorState(
            enrolled=True,
            confirmed_at=record.confirmed_at,
            recovery_codes_remaining=int(remaining or 0),
            locked_until=record.locked_until,
            password_proved=record.password_proved_at is not None,
        )


async def confirm_enrolment(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    secret: str,
    code: str,
    password_proved: bool = False,
    now: datetime | None = None,
) -> list[str] | None:
    """Store the secret if this code proves it, and hand back recovery codes.

    Returns the codes in the clear exactly once - this is the only moment they
    exist outside a hash - or None when the code does not match, which leaves
    nothing written.

    Re-enrolling replaces everything: the old secret, and every recovery code
    issued against it. A recovery code that still opened an account after its
    authenticator had been replaced would be the hole this is meant to close.
    """
    confirmed_at = now or datetime.now(timezone.utc)
    step = matching_step(secret, code, timestamp=confirmed_at.timestamp())
    if step is None:
        return None
    codes = generate_recovery_codes()
    async with session_factory() as database:
        async with database.begin():
            await database.execute(
                delete(UserRecoveryCode).where(UserRecoveryCode.user_id == UUID(user_id))
            )
            existing = await database.get(UserSecondFactor, UUID(user_id))
            if existing is None:
                database.add(
                    UserSecondFactor(
                        user_id=UUID(user_id),
                        secret=secret,
                        confirmed_at=confirmed_at,
                        created_at=confirmed_at,
                        password_proved_at=confirmed_at if password_proved else None,
                        last_step=step,
                        failed_attempts=0,
                    )
                )
            else:
                existing.secret = secret
                existing.confirmed_at = confirmed_at
                # A replacement carries its own proof, and losing the old
                # one's would silently un-promote somebody.
                existing.password_proved_at = (
                    confirmed_at if password_proved else existing.password_proved_at
                )
                existing.last_step = step
                existing.failed_attempts = 0
                existing.locked_until = None
            for code_value in codes:
                database.add(
                    UserRecoveryCode(
                        id=generate_uuid(),
                        user_id=UUID(user_id),
                        code_hash=hash_recovery_code(code_value),
                        created_at=confirmed_at,
                    )
                )
    return codes


async def prove_second_factor_owner(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    now: datetime | None = None,
) -> bool:
    """Record that the account's own password was proved for this factor.

    The caller checks the password; this only writes what that established.
    It exists so somebody who set a factor up without one - which is the
    ordinary path - can satisfy R-AUTH-20 without tearing the factor down and
    scanning it again.
    """
    async with session_factory() as database:
        async with database.begin():
            record = await database.get(UserSecondFactor, UUID(user_id))
            if record is None:
                return False
            record.password_proved_at = now or datetime.now(timezone.utc)
            return True


async def verify_second_factor(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    code: str,
    now: datetime | None = None,
) -> SecondFactorOutcome:
    """Check one code, spending it so the same code cannot be used twice.

    Spending is what makes a relayed code worth less than it looks. A code is
    valid for its whole thirty-second step and one step either side, so
    somebody who reads a code off a victim in real time has a window to use
    it; recording the step it belonged to means the victim's own login has
    already spent it, and the second use finds it gone.

    A recovery code is tried only when the digits are not a TOTP code at all,
    so an ordinary mistyped code never burns one.
    """
    checked_at = now or datetime.now(timezone.utc)
    async with session_factory() as database:
        async with database.begin():
            record = await database.get(UserSecondFactor, UUID(user_id))
            if record is None:
                return SecondFactorOutcome.NOT_ENROLLED
            if record.locked_until is not None and record.locked_until > checked_at:
                return SecondFactorOutcome.LOCKED

            step = matching_step(
                record.secret, code, timestamp=checked_at.timestamp()
            )
            if step is not None and step > record.last_step:
                record.last_step = step
                record.failed_attempts = 0
                record.locked_until = None
                return SecondFactorOutcome.ACCEPTED

            if step is None:
                spent = await _spend_recovery_code(
                    database, user_id=user_id, code=code, now=checked_at
                )
                if spent:
                    record.failed_attempts = 0
                    record.locked_until = None
                    return SecondFactorOutcome.RECOVERY_CODE_SPENT

            # Either the code was wrong, or it was right and already spent.
            # Both are counted: a replayed code is not an honest mistake.
            record.failed_attempts = (record.failed_attempts or 0) + 1
            if record.failed_attempts >= MAX_SECOND_FACTOR_FAILURES:
                record.locked_until = checked_at + SECOND_FACTOR_LOCKOUT
                record.failed_attempts = 0
                return SecondFactorOutcome.LOCKED
            return SecondFactorOutcome.REJECTED


async def _spend_recovery_code(
    database: AsyncSession, *, user_id: str, code: str, now: datetime
) -> bool:
    """Claim one unused recovery code, decided by the database.

    The condition travels with the UPDATE for the reason it does everywhere
    else in this package: two requests carrying the same code must not both
    be told yes, and they would if this read a row and then wrote a decision
    made from it.
    """
    digest = hash_recovery_code(code)
    if not digest:
        return False
    claimed = await database.execute(
        update(UserRecoveryCode)
        .where(
            UserRecoveryCode.user_id == UUID(user_id),
            UserRecoveryCode.code_hash == digest,
            UserRecoveryCode.used_at.is_(None),
        )
        .values(used_at=now)
    )
    return bool(claimed.rowcount)


async def replace_recovery_codes(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    now: datetime | None = None,
) -> list[str]:
    """Issue a fresh set, invalidating every code issued before."""
    issued_at = now or datetime.now(timezone.utc)
    codes = generate_recovery_codes()
    async with session_factory() as database:
        async with database.begin():
            await database.execute(
                delete(UserRecoveryCode).where(UserRecoveryCode.user_id == UUID(user_id))
            )
            for code_value in codes:
                database.add(
                    UserRecoveryCode(
                        id=generate_uuid(),
                        user_id=UUID(user_id),
                        code_hash=hash_recovery_code(code_value),
                        created_at=issued_at,
                    )
                )
    return codes


async def disable_second_factor(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
) -> bool:
    """Remove the secret and every recovery code with it.

    Whether this account is *allowed* to be without one is decided by the
    caller, not here: a staff account that dropped its second factor would
    simply be refused its role at the next request (R-AUTH-20).
    """
    async with session_factory() as database:
        async with database.begin():
            await database.execute(
                delete(UserRecoveryCode).where(UserRecoveryCode.user_id == UUID(user_id))
            )
            removed = await database.execute(
                delete(UserSecondFactor).where(
                    UserSecondFactor.user_id == UUID(user_id)
                )
            )
            return bool(removed.rowcount)
