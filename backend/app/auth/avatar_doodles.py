"""The doodle set a registered player may wear instead of an initial (R-AVA-06).

A doodle is one of this deployment's own drawings, chosen by name; the
drawing itself is a symbol in `frontend/public/avatars/doodles.svg`, painted
in the disc's ink so it takes the player's name colour. The server holds the
list only to refuse a name it does not have: nothing is uploaded, nothing is
stored but the name, and nothing about it needs moderating.

`tests/test_avatars.py` holds this list, the sprite's symbol ids and the
client's list together, so a doodle cannot be added in one place only.
"""
from __future__ import annotations

DOODLE_KEY_PREFIX = "doodle:"

DOODLES: tuple[str, ...] = (
    "fox",
    "cat",
    "ghost",
    "dog",
    "owl",
    "bear",
    "frog",
    "rabbit",
    "penguin",
    "whale",
    "bee",
    "snail",
    "turtle",
    "robot",
    "alien",
    "mushroom",
    "cactus",
    "rocket",
    "planet",
    "star",
    "cloud",
    "icecream",
    "pencil",
    "palette",
)


def doodle_key(name: str) -> str:
    return f"{DOODLE_KEY_PREFIX}{name}"


def doodle_name(key: str) -> str | None:
    """The doodle a stored key names, or None for a content address."""
    if not key.startswith(DOODLE_KEY_PREFIX):
        return None
    name = key[len(DOODLE_KEY_PREFIX) :]
    return name if name in DOODLES else None
