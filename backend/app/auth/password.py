"""Argon2id password hashing, kept off the event loop."""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError
from starlette.concurrency import run_in_threadpool

MIN_PASSWORD_LENGTH = 8
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
    """A password that fails the length policy before it is ever hashed."""


def validate_password(password: object) -> str:
    """Return the password if it satisfies the policy, else raise."""
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
