"""Client-side cadences the server decides, and the notice that carries them.

Most tunables change something the server does. This one changes something the
*client* does, which is the harder half of #446 and the half the issue was
actually about: the drawer's flush interval is the largest single lever on
drawing bandwidth, and the value that turned out to be right was not the one
the byte curve pointed at. It was found by looking at a viewer's screen, and a
value that can only be found by looking is a value somebody has to be able to
change while looking.

So they are shipped rather than compiled. The carrier is a notice sent to each
socket at the handshake and re-sent to everyone when a value changes — not
`room_state`, which is per-room and never reaches somebody sitting in the
lobby, and not the acknowledgement, which the handshake does not have.

`contractVersion` follows `server_shutdown`: this payload has a shape of its
own that can change without the whole protocol moving.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.handlers.budgets import Budget

CLIENT_CONFIG_CONTRACT_VERSION = 4


def _compiled_drawing_budget() -> Budget:
    # Imported here: the handlers package imports this module at load time.
    from app.handlers.budgets import DRAWING

    return DRAWING.default


@dataclass
class ClientConfig:
    """The cadences this server is asking its clients to run at."""

    # How long queued path points wait before going out as one frame. The
    # drawer never feels it - their own canvas is rasterized on every
    # pointermove. A viewer used to paint each batch the moment it landed,
    # which made 56 ms and 80 ms read as steppy on a viewer's screen and kept
    # this at 40; since #559 a viewer plays each batch out over the interval
    # that follows it, at the screen's own rate, so the interval no longer
    # shows as steps and the byte curve gets its way: 80 ms halves the
    # point messages a drawer sends, at the cost of a viewer seeing ink up
    # to 80 ms behind the drawer's hand instead of 40. Still shipped, so it
    # can be moved back from the admin panel while somebody watches.
    flush_interval_ms: int = 80

    # Where the drawing budget in force is read from. Version 3 (#597) tells
    # the client the allowance its `draw` frames spend, so a client replaying
    # a stroke after a stall can pace itself under it instead of bursting into
    # a refusal that drops the frame nobody is waiting on. It is a callable,
    # not a copy: the budget is a tunable, and the notice is re-sent when it
    # moves (`announce_client_config`), so the value read must be the live one.
    drawing_budget: Callable[[], Budget] = field(default=_compiled_drawing_budget)

    # How recently a client must have seen a pointer or a key to answer an
    # AFK check on the player's behalf (#677). Version 4, and it belongs here
    # for the reason the module exists: it changes something the *client*
    # does, and it is the one number in the feature that can only be settled
    # by watching somebody play. Too short and a person who is reading the
    # canvas gets a dialog; too long and a client answers for somebody who
    # left a minute ago. Shipped, so it can be moved while somebody watches.
    afk_input_window_ms: int = 60_000

    def payload(self) -> dict:
        """The `client_config` notice, in the names the client reads."""
        budget = self.drawing_budget()
        return {
            "contractVersion": CLIENT_CONFIG_CONTRACT_VERSION,
            "flushIntervalMs": self.flush_interval_ms,
            "drawingFramesPerWindow": budget.limit,
            "drawingWindowSeconds": budget.window_seconds,
            "afkInputWindowMs": self.afk_input_window_ms,
        }


# One process, one answer for every client that connects to it.
client_config = ClientConfig()
