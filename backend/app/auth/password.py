"""Argon2id password hashing, kept off the event loop."""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError
from starlette.concurrency import run_in_threadpool

from app.auth.breached_passwords import screening_failure

# Twelve rather than eight (#468). Eight characters of anything a person
# actually chooses is inside the reach of an offline guess against a stolen
# hash, however good the hashing is - Argon2id raises the cost per guess, and
# a short password lowers the number of guesses needed by more. Twelve is the
# point at which the length rule, rather than the list beside it, is doing the
# work: it removes essentially every entry in a published breach corpus on its
# own (R-AUTH-19).
MIN_PASSWORD_LENGTH = 12
# Argon2 itself has no length limit, but an unbounded password is a cheap way to
# make the server do arbitrary work per request.
MAX_PASSWORD_LENGTH = 128

# OWASP's current Argon2id baseline (19 MiB, t=2, p=1) rather than the library
# defaults, which ask for 64 MiB. This process also runs every live drawing
# stroke for every room, so the memory and latency of a login matter here in a
# way they would not in a request-per-process deployment.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


# Verified against when no account matches the given username, so that path
# costs the same as a real password check and cannot be told apart by timing.
DUMMY_HASH = _hasher.hash("no-such-account")


PASSWORD_RULE_MESSAGE = (
    f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters."
)


class PasswordPolicyError(ValueError):
    """A password refused by policy before it is ever hashed.

    Its message is shown to the person choosing the password, so it says which
    rule refused it. A refusal somebody cannot act on sends them to a password
    one character different from the one they just tried.
    """


def validate_password(
    password: object,
    *,
    username: str | None = None,
    email: str | None = None,
) -> str:
    """Return the password if it satisfies the policy, else raise.

    Length first, then screening (#468). The order matters for what people are
    told: a nine-character password is short, and saying instead that it is a
    common one - which it very likely also is - explains the wrong thing.

    The identity is passed in wherever the caller has it, because a password
    built from the name it protects is the one weak password a list can never
    hold. It is optional rather than required: a reset knows the account, and
    a registration knows the name being claimed, but neither is worth making a
    caller invent when it does not have one (R-AUTH-19).
    """
    if not isinstance(password, str):
        raise PasswordPolicyError("Password must be text")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters"
        )
    refusal = screening_failure(password, username=username, email=email)
    if refusal is not None:
        raise PasswordPolicyError(refusal)
    return password


async def hash_password(password: str) -> str:
    """Hash a password without blocking the event loop."""
    return await run_in_threadpool(_hasher.hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    """Check a password against its hash without blocking the event loop."""
    if not password_hash or not isinstance(password, str):
        return False

    def _verify() -> bool:
        try:
            return _hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    return await run_in_threadpool(_verify)


async def password_needs_rehash(password_hash: str) -> bool:
    """Whether a valid encoded hash predates the current Argon2 parameters."""
    if not password_hash:
        return False

    def _check() -> bool:
        try:
            return _hasher.check_needs_rehash(password_hash)
        except (InvalidHashError, VerificationError):
            return False

    return await run_in_threadpool(_check)
