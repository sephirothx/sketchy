"""Who may open which of Solo's doors (#1434): the one gate, in one place.

Solo launches with today's Daily alone (owner's decision, 2026-11-23). The free
runs - 5, 10 and unlimited - and the Daily archive stay built and tested, closed
by `OPEN_DOORS`, so opening one again is a change to that set alone. Every door
asks this when a run is created or a Daily opened, never in the middle of a run,
so closing a door never cuts one short - with one exception: answering a drawing
of a Daily whose date has ended everywhere is playing it late, the archive's, so
a Daily left unfinished past its date stops there while that door is closed.
"""
from __future__ import annotations

from typing import Literal, get_args

from app.domain_values import AccountState

SoloDoor = Literal["daily_today", "free_5", "free_10", "free_unlimited", "archive"]

ALL_DOORS: frozenset[SoloDoor] = frozenset(get_args(SoloDoor))

# What a registered player may open. The rest wait for a reason to open them
# again, such as a supporter pass (#1471, parked).
OPEN_DOORS: frozenset[SoloDoor] = frozenset({"daily_today"})


def free_run_door(length: int | None) -> SoloDoor:
    return "free_unlimited" if length is None else ("free_5" if length == 5 else "free_10")


def solo_account(*, state: str, is_anonymous: bool) -> bool:
    """Whether an account may play Solo at all. A guest may not yet: the Daily
    for everybody is a later decision (#1434)."""
    return not is_anonymous and state == AccountState.REGISTERED.value


def solo_door_open(*, state: str, is_anonymous: bool, door: SoloDoor) -> bool:
    """Whether an account may open `door`: a Solo account, at an open door."""
    return solo_account(state=state, is_anonymous=is_anonymous) and door in OPEN_DOORS
