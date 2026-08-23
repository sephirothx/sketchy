"""Central generation policy for durable entity identifiers."""
from __future__ import annotations

from uuid import UUID, uuid7


def generate_uuid7() -> UUID:
    """Return the repository-wide RFC 9562 time-ordered UUID implementation.

    This is the standard library's implementation, which keeps a 42-bit
    counter inside each millisecond (RFC 9562, section 6.2, method 1). The
    embedded timestamp therefore stays truthful under burst generation,
    unlike an implementation that orders IDs by pushing the timestamp
    forward one millisecond per UUID.

    These identifiers are not credentials. Within a single millisecond the
    counter makes consecutive values guessable from a neighbour, which is
    irrelevant for entity IDs and unacceptable for capabilities - session
    tokens, room codes, and share codes stay cryptographically random.
    """
    return uuid7()
