"""Who may open which of Solo's doors (#1434, #1477): the one gate, in one place.

Today's Daily and the 5 and 10 runs are every registered player's. Endless and the
Daily archive come with the supporter pass. Every door asks this when a run is
created or a Daily opened, never in the middle of one, so a pass that ends never
cuts a run short. With no provider there is no pass to ask for, and all are open.
"""
from __future__ import annotations

from typing import Literal

from app.domain_values import AccountState

SoloDoor = Literal["daily_today", "free_5", "free_10", "free_unlimited", "archive"]

SUPPORTER_DOORS: frozenset[str] = frozenset({"free_unlimited", "archive"})


def free_run_door(length: int | None) -> SoloDoor:
    return "free_unlimited" if length is None else ("free_5" if length == 5 else "free_10")


def solo_door_open(*, state: str, is_anonymous: bool, door: SoloDoor, perks: bool) -> bool:
    """Whether an account may open `door`. `perks` is whether it holds the pass, or
    there is no tier to hold one of. A guest may not open any yet: the Daily for
    everybody is a later decision (#1434)."""
    if is_anonymous or state != AccountState.REGISTERED.value:
        return False
    return perks or door not in SUPPORTER_DOORS
