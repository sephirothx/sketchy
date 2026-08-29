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

Bump this whenever any payload on the socket changes shape. It is cheap: both
ends deploy together, so the only client that ever sees a mismatch is one that
was already open across the deploy.
"""
from __future__ import annotations

PROTOCOL_VERSION = 5


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
