"""The doodle set a registered player may wear instead of an initial (#579).

A doodle is one of this deployment's own drawings, chosen by name. The drawing
is a symbol in `frontend/public/avatars/doodles.svg`, generated from
`scripts/brand/avatar-doodles.mjs` and painted in the disc's ink, so it takes
the player's name color the way their initial did. The server holds the list
only to refuse a name it does not have: nothing is uploaded, nothing is stored
but the name, and there is nothing in it to moderate (R-AVA-09).

`tests/test_avatars.py` holds this list, the sprite's symbol ids and the
client's list together, so a doodle cannot be added in one place only.
"""
from __future__ import annotations

import secrets

DOODLE_KEY_PREFIX = "doodle:"

# The picker's order, which is the sprite's.
DOODLES: tuple[str, ...] = (
    "fox",
    "cat",
    "owl",
    "frog",
    "crab",
    "penguin",
    "fish",
    "bear",
    "ladybug",
    "butterfly",
    "turtle",
    "alien",
    "ghost",
    "robot",
    "rocket",
    "kite",
    "boat",
    "balloon",
    "umbrella",
    "coffee",
    "cactus",
    "mushroom",
    "cloud",
    "flower",
    "donut",
    "icecream",
)


def doodle_key(name: str) -> str:
    return f"{DOODLE_KEY_PREFIX}{name}"


def doodle_name(key: str | None) -> str | None:
    """The doodle a stored key names, or None for anything else."""
    if not key or not key.startswith(DOODLE_KEY_PREFIX):
        return None
    name = key[len(DOODLE_KEY_PREFIX):]
    return name if name in DOODLES else None


def random_doodle_key() -> str:
    """What a new account wears until its owner picks something.

    Random rather than the first in the list, so a room of new players is not
    a room of foxes.
    """
    return doodle_key(secrets.choice(DOODLES))
