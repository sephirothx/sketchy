"""Provider-agnostic normalization for account email identities."""
from __future__ import annotations


MAX_EMAIL_LENGTH = 255


class EmailAddressError(ValueError):
    """Raised when an email value cannot be stored as an account identity."""


def normalize_email(value: str | None) -> str | None:
    """Trim and lowercase an address without provider-specific rewriting."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise EmailAddressError("Email must be a string.")
    normalized = value.strip().lower()
    if not normalized:
        return None
    if len(normalized) > MAX_EMAIL_LENGTH:
        raise EmailAddressError("Email is too long.")
    if any(character.isspace() or ord(character) < 32 for character in normalized):
        raise EmailAddressError("Email cannot contain whitespace or control characters.")
    local, separator, domain = normalized.rpartition("@")
    if separator != "@" or not local or not domain or "." not in domain:
        raise EmailAddressError("Email is not valid.")
    return normalized
