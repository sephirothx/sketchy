"""Central generation policy for durable entity identifiers."""
from __future__ import annotations

from uuid import UUID

from uuid6 import uuid7


def generate_uuid7() -> UUID:
    """Return the repository-wide RFC 9562 time-ordered UUID implementation."""
    return uuid7()
