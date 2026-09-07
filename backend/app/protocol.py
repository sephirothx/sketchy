"""The version both ends of a socket must agree on before anything else.

Frame layouts carry their own version bytes, but those are checked far too
late to help. A `draw` frame refused by the codec is refused inside a handler
that has no acknowledgement, so the sender is never told: it keeps drawing
into a canvas the server stopped recording, and when it finally asks for a
resync it cannot decode the reply, so it asks again. The failure is silent,
permanent, and indistinguishable to the player from the game freezing.

So the version is settled once, at the handshake, where there is somewhere to
put the answer. A mismatch is not refused - a refusal carries no diagnosable
signal, and `ConnectionRefusedError` is reserved for suspensions. The socket
connects normally and is sent `upgrade_required`, which the client answers by
reloading onto the build the server is serving.

Told, then held to it (#476). Until the reload the socket is *quarantined*:
every command it sends is refused with `protocol_mismatch` at the dispatch
door, before parsing, so a stale build cannot create or join a room, draw, or
watch the lobby on a contract the server no longer speaks - and after
`STALE_SOCKET_CLOSE_SECONDS` it is closed, so a tab that ignored the notice
does not hold a socket and a presence slot for the rest of its life. The
reload itself takes well under a second, so a client that does act never
notices either. A client that reloaded once and came back on the same stale
bundle - a proxy ignoring `no-cache`, a stale service worker - stops
reconnecting and says so on screen instead of looping through this.

REST is held to the same number: every HTTP response carries it in
`PROTOCOL_HEADER`, and the client compares it against its own constant with
the same reload-once rule, so a tab that is not on a socket - offline, or
refusing to reconnect - is caught on its next request rather than left
stale until it opens one.

Bump this whenever any payload on the socket changes shape. It is cheap: both
ends deploy together, so the only client that ever sees a mismatch is one that
was already open across the deploy.
"""
from __future__ import annotations

PROTOCOL_VERSION = 15

# How long a socket that was told to upgrade is kept before it is closed.
# Long enough for the reload the notice asks for (a fraction of a second on
# any network that completed the handshake); short enough that a tab that
# ignores it is not counted as online for long.
STALE_SOCKET_CLOSE_SECONDS = 5.0

# The response header every HTTP answer carries the version in.
PROTOCOL_HEADER = "x-sketchy-protocol"


def client_protocol_version(auth) -> int:
    """Read the protocol version a connecting client claims.

    Anything that is not a plain integer - absent, a string, a bool, a whole
    missing `auth` - reads as 0. Every build from before this handshake existed
    sends no `auth` at all, and "absent" means older than version 1, never
    "trusted".
    """
    if not isinstance(auth, dict):
        return 0
    value = auth.get("protocol")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value
