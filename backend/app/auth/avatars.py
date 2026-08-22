"""Canonical keys for avatar visuals hosted by the Sketchy deployment."""
from __future__ import annotations


BUILT_IN_AVATAR_KEYS = ("initial", "pencil", "palette", "spark")


def validate_avatar_key(value: str | None) -> str | None:
    """Accept only a key from the fixed, deployment-hosted avatar catalog."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Avatar key must be a string.")
    key = value.strip().lower()
    if not key:
        return None
    if key not in BUILT_IN_AVATAR_KEYS:
        raise ValueError("Unknown built-in avatar key.")
    return key
