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
from datetime import date, datetime, time, timedelta, timezone

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


# --- the Daily -----------------------------------------------------------------

DAILY_LENGTH = 5
# A concept is not the Daily again within this many days of its last Daily.
DAILY_REUSE_DAYS = 60
# How far a local clock is from UTC at most: a date is somewhere's today from
# 14 h before its UTC midnight (UTC+14) until 14 h after the next (UTC-12 and
# a margin). The Daily rolls over at each player's own midnight, and the
# server, which cannot see the player's zone, accepts any date that is today
# somewhere.
DAY_EDGE = timedelta(hours=14)
# How long a date found too thin for a Daily waits before it is looked at
# again, while it is still open: a date first asked for before the day's
# games had finished would otherwise stay without one for good, though
# nobody could have played it.
SKIPPED_RETRY = timedelta(minutes=5)


def date_is_open(day: date, now: datetime) -> bool:
    """Whether `day` is still today somewhere at `now`."""
    start = datetime.combine(day, time.min, tzinfo=timezone.utc) - DAY_EDGE
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc) + DAY_EDGE
    return start <= now < end


def open_dates(now: datetime) -> tuple[date, ...]:
    """Every date that is today somewhere at `now`: two or three of them."""
    today = now.astimezone(timezone.utc).date()
    return tuple(
        day
        for day in (today - timedelta(days=1), today, today + timedelta(days=1))
        if date_is_open(day, now)
    )


def daily_start_key(day: date) -> int:
    """Where a date's walk through the pool starts: the same for everybody,
    and nothing a player can choose."""
    digest = hashlib.sha256(b"solo-daily:" + day.isoformat().encode("ascii")).digest()
    return int.from_bytes(digest[:4], "big") % SAMPLE_KEY_SPACE


def daily_streak(
    started_dates: list[date], today: date, *, skipped: list[date] | tuple = ()
) -> int:
    """How many days in a row ending today - or yesterday, while today's is
    still to play - the player started the Daily on its own date. A date that
    had no Daily (too thin a pool) is stepped over: it breaks nobody's streak.
    Computed from their results each time it is asked, never kept as a
    counter (N-03)."""
    played = set(started_dates)
    passed = set(skipped)
    day = today
    if day not in played:
        day -= timedelta(days=1)
    streak = 0
    while day in played or day in passed:
        if day in played:
            streak += 1
        day -= timedelta(days=1)
    return streak


def longest_daily_streak(started_dates: list[date], *, skipped: list[date] | tuple = ()) -> int:
    """The most days in a row the player ever started the Daily on its own
    date, by the same rule as `daily_streak`: a date with no Daily is stepped
    over. Computed each time it is asked, never kept (N-03)."""
    played = sorted(set(started_dates))
    passed = set(skipped)
    longest = run = 0
    previous: date | None = None
    for day in played:
        gap = previous + timedelta(days=1) if previous is not None else None
        while gap is not None and gap < day and gap in passed:
            gap += timedelta(days=1)
        run = run + 1 if gap == day else 1
        longest = max(longest, run)
        previous = day
    return longest


def daily_release_at(day: date) -> datetime:
    """When `day` has ended everywhere: the moment a Solo share of one of its
    drawings, held meanwhile, enters the Gallery."""
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc) + DAY_EDGE
