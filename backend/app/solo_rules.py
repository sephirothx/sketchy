"""Solo's rules (#1434): which drawings it may serve, as numbers and pure functions.

Solo is a game of one: a registered player guesses drawings from public games
they were not in. It is not a Room or a Game (R-ROOM-05 wants two players);
its state is in the database and its routes are REST. This module holds the
parts that need no database, so a test can reach them without one.
"""
from __future__ import annotations

import hashlib
import uuid

# A drawing needs this many canvas actions (`turn_records.stroke_count`) to
# be served: one line and a dot is not a drawing anybody can be asked to name,
# and the one-correct-guesser bar below catches most of what is left.
MIN_POOL_STROKES = 5
# Somebody in the original game named it: a drawing nobody got is either a
# hard prompt or an unreadable drawing, and Solo cannot tell which.
MIN_POOL_CORRECT_GUESSERS = 1
# Only prompts every audience may see (R-PROMPT content ratings): a Solo
# player chose no room, so nothing a room's host opted into reaches them.
SOLO_CONTENT_RATING = "everyone"

# `solo_pool.sample_key` is in [0, SAMPLE_KEY_SPACE): an int keeps the index
# small, and 31 bits stays positive on every engine.
SAMPLE_KEY_SPACE = 2**31


def sample_key(turn_id: uuid.UUID | str) -> int:
    """Where a drawing sits in the pool's random order.

    Derived from the turn id rather than drawn at write time, so a rebuild
    puts every row back where it was and a test can say where a row lands.
    Clients never see turn ids (#1434's serve ids), so nobody can steer by it.
    """
    raw = turn_id.bytes if isinstance(turn_id, uuid.UUID) else uuid.UUID(str(turn_id)).bytes
    return int.from_bytes(hashlib.sha256(b"solo-pool:" + raw).digest()[:4], "big") % SAMPLE_KEY_SPACE
