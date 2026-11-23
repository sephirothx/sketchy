"""Central policy for durable entity identifiers: how one is made, and how one
that arrived as text is read."""
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
    tokens, room codes, and invitation tokens stay cryptographically random.
    """
    return uuid7()


def parse_entity_id(value: object) -> UUID | None:
    """The UUID that `value` spells, or None when it spells none.

    For ids that arrive from outside - a path segment, above all - and are
    about to be bound into a statement. A route's path parameter is any text
    at all; `UUID(value)` raises on most of it, and that ValueError escaping
    a handler is a 500. A NUL is the sharpest case: PostgreSQL refuses it in
    any text it is handed. An id that parses to nothing names no row, so the
    caller answers it as it answers an id that is simply not there - before
    the statement, never from it.
    """
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
