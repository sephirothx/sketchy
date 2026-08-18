"""The single naming rule shared by guest nicknames and account usernames.

A registered player always plays under their username, so it appears in the
player list, chat, and both leaderboards - all laid out for the existing 16
character nickname budget. Keeping one rule for both also means the "is this
name already taken" check is a straight comparison rather than a mapping
between two different character sets.
"""
from __future__ import annotations

import random
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


def is_valid_name(value: object) -> bool:
    try:
        validate_name(value)
    except NameError_:
        return False
    return True


# Deliberately wholesome and short: a generated name is the first thing other
# players see, it has to fit the 16-character budget alongside an adjective,
# and nobody should be embarrassed by the name they were handed.
GUEST_ADJECTIVES: tuple[str, ...] = (
    "Brisk", "Quiet", "Lucky", "Nimble", "Cosmic", "Sleepy", "Cheery",
    "Bold", "Fuzzy", "Swift", "Merry", "Clever", "Jolly", "Wobbly",
    "Sunny", "Chilly", "Snappy", "Plucky", "Breezy", "Zesty",
)

GUEST_ANIMALS: tuple[str, ...] = (
    "Otter", "Walrus", "Puffin", "Badger", "Heron", "Marmot", "Gecko",
    "Tapir", "Lemur", "Falcon", "Beaver", "Ferret", "Magpie", "Newt",
    "Quokka", "Panda", "Koala", "Yak", "Moose", "Crow",
)


def generate_guest_name() -> str:
    """Invent a display name for a brand new guest.

    Players are never asked for a name, so one has to be waiting for them.
    Guaranteed to satisfy the shared naming rule, and guests may share a name -
    it is a label, not an identity.
    """
    for _ in range(10):
        candidate = f"{random.choice(GUEST_ADJECTIVES)}{random.choice(GUEST_ANIMALS)}"
        if len(candidate) <= MAX_NAME_LENGTH:
            return candidate
    # Every adjective/animal pair fits, but never hand back an invalid name.
    return f"Player{random.randint(100, 999)}"
