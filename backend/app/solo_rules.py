"""Solo's rules (#1434): which drawings it may serve, as numbers and pure functions.

Solo is a game of one: a registered player guesses drawings from public games
they were not in. It is not a Room or a Game (R-ROOM-05 wants two players);
its state is in the database and its routes are REST. This module holds the
parts that need no database, so a test can reach them without one.
"""
from __future__ import annotations

import base64
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


# --- a run -------------------------------------------------------------------

# A free run is this many drawings, or `None`: unlimited, until the first miss.
FREE_RUN_LENGTHS: tuple[int | None, ...] = (5, 10, None)
# The clock a drawing is guessed against, and the part of it the strokes take
# to replay (#1434): the last ten seconds show the finished drawing.
CLOCK_SECONDS = 30
REPLAY_SECONDS = 20
# A room's default scoring, over Solo's clock (R-SCORE-03): 300 for a guess
# at the first instant, 100 at the last.
MIN_POINTS = 100
MAX_POINTS = 300
# How many drawings a run may hold served and not yet settled: the one being
# guessed and the one the client fetched ahead, so the next appears at once.
MAX_OPEN_SERVES = 2

SOLVED = "solved"
GIVEN_UP = "given_up"
TIMED_OUT = "timed_out"
OUTCOMES = (SOLVED, GIVEN_UP, TIMED_OUT)


def points_for(seconds: float) -> int:
    """What a drawing named after `seconds` scores: the room formula, from
    `MAX_POINTS` at once to `MIN_POINTS` at the buzzer.

    Seconds are the client's (#1434: play is local). They are bounded here,
    which is the only check a self-reported time can have: nothing scores
    more than a guess at the first instant could.
    """
    elapsed = min(max(float(seconds), 0.0), float(CLOCK_SECONDS))
    remaining = CLOCK_SECONDS - elapsed
    return round(MIN_POINTS + (MAX_POINTS - MIN_POINTS) * remaining / CLOCK_SECONDS)


def run_is_over(length: int | None, *, settled: int, missed: bool) -> bool:
    """Whether a run ends with this drawing: a finite run when every drawing
    is settled, an unlimited one at its first miss."""
    if length is None:
        return missed
    return settled >= length


# --- the answer a serve carries ------------------------------------------------


def encode_answers(serve_id: uuid.UUID | str, forms: str) -> str:
    """The answer forms as a serve carries them: XOR with the serve id, then
    base64.

    Not a secret. Play is local (#1434), so the answer has to reach the
    browser before the guess; this only keeps it from being read off the
    network panel at a glance by a player who did not go looking. There is
    no leaderboard (N-03) for a player who does go looking to climb.
    """
    key = uuid.UUID(str(serve_id)).bytes
    data = forms.encode("utf-8")
    mixed = bytes(byte ^ key[index % len(key)] for index, byte in enumerate(data))
    return base64.b64encode(mixed).decode("ascii")


def decode_answers(serve_id: uuid.UUID | str, encoded: str) -> str:
    """`encode_answers` undone, for tests and for anybody reading the wire."""
    key = uuid.UUID(str(serve_id)).bytes
    mixed = base64.b64decode(encoded)
    return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(mixed)).decode("utf-8")
