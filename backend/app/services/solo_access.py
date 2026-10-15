"""Who may open which of Solo's doors (#1434): the one gate, in one place.

Registered players may play every door today. The supporter pass (#1477) is
to narrow two of them - unlimited free runs and the Daily archive - and that
is a change to this function alone: every door asks it when a run is created
or resumed, never in the middle of one, so a pass that ends never cuts a run
short.
"""
from __future__ import annotations

from typing import Literal

from app.domain_values import AccountState

SoloDoor = Literal["daily_today", "free_5", "free_10", "free_unlimited", "archive"]


def free_run_door(length: int | None) -> SoloDoor:
    return "free_unlimited" if length is None else ("free_5" if length == 5 else "free_10")


def solo_door_open(*, state: str, is_anonymous: bool, door: SoloDoor) -> bool:
    """Whether an account may open `door`. A guest may not open any yet: the
    Daily for everybody is a later decision (#1434)."""
    del door  # Every door is open to every registered player until #1477.
    return not is_anonymous and state == AccountState.REGISTERED.value
