"""The single naming rule shared by guest nicknames and account usernames.

A registered player always plays under their username, so it appears in the
player list, chat, and both leaderboards - all laid out for the existing 16
character nickname budget. Keeping one rule for both also means the "is this
name already taken" check is a straight comparison rather than a mapping
between two different character sets.
"""
from __future__ import annotations

import re

MIN_NAME_LENGTH = 3
MAX_NAME_LENGTH = 16
NAME_PATTERN = re.compile(rf"^[a-zA-Z0-9_-]{{{MIN_NAME_LENGTH},{MAX_NAME_LENGTH}}}$")

# Names that would let a player pose as the system or as an unclaimed guest.
# System chat already broadcasts an empty nickname, so this is about the
# player list and chat prefixes rather than message spoofing.
RESERVED_NAMES = frozenset({"guest", "system", "admin", "sketchy", "server", "you"})

NAME_RULE_MESSAGE = (
    f"Use {MIN_NAME_LENGTH}-{MAX_NAME_LENGTH} characters: letters, numbers, "
    "hyphens or underscores. No spaces."
)


class NameError_(ValueError):
    """A name that fails the shared naming rule."""


def normalize_name(value: object) -> str:
    """Trim a candidate name without altering its case.

    Case is preserved for display; uniqueness is enforced case-insensitively by
    the database index, so ``Stefano`` and ``stefano`` cannot coexist.
    """
    return value.strip() if isinstance(value, str) else ""


def validate_name(value: object) -> str:
    """Return the normalized name, or raise if it breaks the rule."""
    name = normalize_name(value)
    if not NAME_PATTERN.fullmatch(name):
        raise NameError_(NAME_RULE_MESSAGE)
    if name.lower() in RESERVED_NAMES:
        raise NameError_("That name is reserved. Please choose another.")
    return name
