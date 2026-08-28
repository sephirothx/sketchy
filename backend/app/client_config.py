"""Client-side cadences the server decides, and the notice that carries them.

Most tunables change something the server does. These two change something the
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

from dataclasses import dataclass

CLIENT_CONFIG_CONTRACT_VERSION = 1


@dataclass
class ClientConfig:
    """The cadences this server is asking its clients to run at."""

    # How long queued path points wait before going out as one frame. The
    # drawer never feels it - their own canvas is rasterized on every
    # pointermove - but a viewer receives a whole batch at once and draws it as
    # one polyline, so a fast curve arrives as visible facets. The byte curve
    # says to raise this; measured against a viewer's screen, 56ms and 80ms
    # both read as steppy and 40ms did not.
    flush_interval_ms: int = 40
    # How often the lobby asks for the room list. Freshness against request
    # volume; the poll already stops while the tab is hidden.
    lobby_poll_interval_ms: int = 4_000

    def payload(self) -> dict:
        """The `client_config` notice, in the names the client reads."""
        return {
            "contractVersion": CLIENT_CONFIG_CONTRACT_VERSION,
            "flushIntervalMs": self.flush_interval_ms,
            "lobbyPollIntervalMs": self.lobby_poll_interval_ms,
        }


# One process, one answer for every client that connects to it.
client_config = ClientConfig()
