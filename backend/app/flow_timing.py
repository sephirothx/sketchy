"""How long each phase of a turn waits, in one place a request can reach.

These were six constants in four modules, and two of them were the same number
written twice. That is not why they moved. They moved because a constant
cannot be tuned: `from app.game import TURN_RESULTS_SECONDS` copies the number
into the importing module at import time, so an administrator changing it at
runtime would change a value nobody reads. Held on one object, every call site
asks at the moment it needs an answer, and there is exactly one answer.

The defaults are the numbers these have always been. What changed is that a
deployment can now try different ones without a deploy (#446), and that
`reconnect_grace_seconds` is stated once rather than declared in
`handlers/connection.py` and again, unused, in `services/game_flow.py`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FlowTiming:
    """The phase lengths in force for this process."""

    # Long enough to read four prompts, short enough that a distracted drawer
    # does not hold three other people. The client shows it as a countdown.
    choose_prompt_seconds: float = 15
    # The pause on the turn-results screen. Clients read the length off the
    # payload rather than assuming it, so a shorter one is still a faithful
    # turn - which is what lets the E2E suite run whole games at 0.5s.
    turn_results_seconds: float = 5
    # A disconnected player keeps their seat this long. Long enough to cover a
    # tab switch, a transport bounce or a lift; short enough that a room is
    # not held by somebody who has gone.
    reconnect_grace_seconds: float = 30
    # How long a restart vote stays open before it lapses.
    restart_vote_seconds: float = 20
    # How long after a vote before another may be called, so a losing side
    # cannot simply call it again.
    restart_vote_cooldown_seconds: float = 60
    # The pause between a passed vote and the restart, so the room can read
    # what happened before the board clears.
    restart_delay_seconds: float = 3


# One process, one set of phase lengths. Handlers, the flow service and the
# payload presenters all read this object rather than importing its numbers.
timing = FlowTiming()
