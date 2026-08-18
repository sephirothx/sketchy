"""Password hashing and verification utilities using Argon2id."""
from __future__ import annotations

import logging
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

logger = logging.getLogger(__name__)

# Standard Argon2id configuration with secure defaults
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against an Argon2id hash."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception:
        logger.exception("Unexpected error verifying password hash")
        return False
