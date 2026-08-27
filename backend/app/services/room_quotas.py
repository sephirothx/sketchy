"""Ceilings on rooms: who may open one, and how many may crowd into one.

Creating a room is the only command an ordinary socket can issue that
allocates unbounded process memory - a `Room`, its `CanvasSession`, its recap
buffer, and its quick prompts - and claims a durable code reservation. Sketchy
runs one worker by design (N-01), so "unbounded" means the whole service.

Three ceilings, answering three different questions:

* **This account** - how many rooms may one player hold open at once, and how
  often may they open one. The first is live state and is counted in memory;
  the second is a rate and uses the same persistent bucket the authentication
  limits use, so it survives a restart.
* **This process** - how many rooms exist at all, and how many characters of
  quick prompts they are collectively holding.

Per-IP creation quotas are deliberately absent until there is a client address
worth keying on: behind the reverse proxy #457 introduces, every socket
presents the proxy's address, and the forwarded header is attacker-controlled
(see `auth/rate_limit.client_key`).
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.rate_limit import PersistentRateLimiter, RateLimiter
from app.rooms import Room, RoomManager

logger = logging.getLogger("sketchy.room_quotas")

# Four times the 50-room validation target in `docs/requirements.md`, so the
# documented target is not also the wall, and still a number one process can
# be reasoned about holding.
DEFAULT_GLOBAL_ROOMS = 200
# Enough for a host running a couple of rooms and setting up a third; far
# below what a script would want.
DEFAULT_PER_ACCOUNT_ROOMS = 3
DEFAULT_CREATIONS_PER_HOUR = 10
# The per-room ceiling (MAX_RAW_INPUT_LENGTH) bounds one room; this bounds the
# sum, which is otherwise that ceiling multiplied by DEFAULT_GLOBAL_ROOMS.
DEFAULT_PROMPT_CHARACTERS = 4 * 1024 * 1024


# Watching is cheaper than playing but not free: every spectator is another
# recipient of every broadcast, and `max_players` never counted them.
DEFAULT_SPECTATORS_PER_ROOM = 8
# Above the 400-seat validation target in `docs/requirements.md` with room to
# spare, and still a number one process can be reasoned about holding.
DEFAULT_SOCKETS = 600
# A client re-enters a room for ordinary reasons - a reconnect, a stall
# recovery - but a seating join costs the room a broadcast, so the churn is
# worth bounding. Confirmations of a seat already held are free.
DEFAULT_JOINS_PER_SOCKET = 20
# Rebinding an existing seat to a new socket costs the room the same full
# broadcast a fresh join does, and per-socket limits cannot see it: every
# attempt arrives on a new socket with a fresh allowance, and the socket it
# supersedes is closed, so the connection ceiling never notices either. Keyed
# by the seat, which is the part the attacker is not replacing.
DEFAULT_TAKEOVERS_PER_SEAT = 20
JOIN_WINDOW_SECONDS = 60.0


class RoomQuotaExceeded(Exception):
    """A ceiling refused this room. The message is written for the player."""


def _ceiling(values: Mapping[str, str], name: str, default: int) -> int:
    """Read a ceiling from the environment, falling back to the default.

    Configurable for the same reason the authentication limits are: the right
    number depends on the host, and a test harness needs it out of the way.
    """
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s is not a number; using %d", name, default)
        return default
    if value <= 0:
        logger.warning("%s must be positive; using %d", name, default)
        return default
    return value


def prompt_characters(prompts: Iterable[str]) -> int:
    """What a room's quick prompts cost, in the unit the ceiling is set in."""
    return sum(len(prompt) for prompt in prompts)


class RoomQuotaService:
    """Answer whether this account may open one more room, right now."""

    def __init__(
        self,
        room_manager: RoomManager,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        values = os.environ if environ is None else environ
        self._rooms = room_manager
        self.global_rooms = _ceiling(values, "ROOM_GLOBAL_LIMIT", DEFAULT_GLOBAL_ROOMS)
        self.per_account_rooms = _ceiling(
            values, "ROOM_PER_ACCOUNT_LIMIT", DEFAULT_PER_ACCOUNT_ROOMS
        )
        self.prompt_characters = _ceiling(
            values, "ROOM_PROMPT_CHARACTER_LIMIT", DEFAULT_PROMPT_CHARACTERS
        )
        self._creations = (
            PersistentRateLimiter(
                session_factory,
                scope="room_create",
                limit=_ceiling(
                    values, "ROOM_CREATE_LIMIT", DEFAULT_CREATIONS_PER_HOUR
                ),
                window_seconds=3600,
            )
            if session_factory is not None
            else None
        )

    def check_capacity(self, user_id: str) -> None:
        """Refuse a room the process, or this account, has no room for.

        Deliberately synchronous and in-memory: the caller runs it again
        immediately before the room is created, where there is no await left
        for a second creation to arrive in.
        """
        if len(self._rooms.rooms) >= self.global_rooms:
            raise RoomQuotaExceeded(
                "This server is holding as many rooms as it can. "
                "Try again in a few minutes."
            )
        held = self._rooms.rooms_created_by(user_id)
        if held >= self.per_account_rooms:
            raise RoomQuotaExceeded(
                f"You already have {held} rooms open. "
                "Close one before opening another."
            )

    def check_retained_prompts(
        self, prompts: Iterable[str], *, replacing: Room | None = None
    ) -> None:
        """Refuse quick prompts the process cannot afford to hold.

        `replacing` is the room whose own prompts these would take the place
        of, so editing a room's list is measured as the change it is rather
        than as a second copy.
        """
        held = self._rooms.retained_prompt_characters()
        if replacing is not None:
            held -= replacing.custom_prompt_characters
        if held + prompt_characters(prompts) > self.prompt_characters:
            raise RoomQuotaExceeded(
                "This server is holding as many custom prompts as it can. "
                "Try again with a shorter list."
            )

    async def check_creation_rate(self, user_id: str) -> None:
        """Refuse an account opening rooms faster than a person would.

        Persistent, so a restart is not a way to get a fresh allowance, and
        keyed by account rather than address for the reason in the module
        docstring.
        """
        if self._creations is None:
            return
        if not await self._creations.check(user_id):
            raise RoomQuotaExceeded(
                "You have opened a lot of rooms recently. Try again later."
            )

    async def refund_creation(self, user_id: str) -> None:
        """Give the allowance back when the room was not opened after all.

        The rate is charged before the room code and the persistent row are
        claimed, so that an account already over its allowance fails without
        costing a reservation. Everything after that point can still refuse -
        a drain starting, an allocation failing, the capacity re-check losing
        its race - and an attempt that opened no room must not be spent.
        """
        if self._creations is None:
            return
        await self._creations.refund(user_id)


class RoomCapacityService:
    """How many may crowd into one room, and into this process.

    Separate from `RoomQuotaService` because it answers a different question:
    that one decides whether a room may exist, this one decides how much of
    the server one room - or one socket - may occupy. Both are process-local
    and synchronous; neither needs a database to say no.
    """

    def __init__(self, *, environ: Mapping[str, str] | None = None) -> None:
        values = os.environ if environ is None else environ
        self.spectators_per_room = _ceiling(
            values, "ROOM_SPECTATOR_LIMIT", DEFAULT_SPECTATORS_PER_ROOM
        )
        self.sockets = _ceiling(values, "SOCKET_LIMIT", DEFAULT_SOCKETS)
        self.joins_per_socket = _ceiling(
            values, "ROOM_JOIN_LIMIT", DEFAULT_JOINS_PER_SOCKET
        )
        self.takeovers_per_seat = _ceiling(
            values, "ROOM_TAKEOVER_LIMIT", DEFAULT_TAKEOVERS_PER_SEAT
        )
        self._joins = RateLimiter(self.joins_per_socket, JOIN_WINDOW_SECONDS)
        self._takeovers = RateLimiter(self.takeovers_per_seat, JOIN_WINDOW_SECONDS)
        self._open_sockets: set[str] = set()

    @property
    def open_sockets(self) -> int:
        return len(self._open_sockets)

    def note_socket_opened(self, sid: str) -> None:
        self._open_sockets.add(sid)

    def note_socket_closed(self, sid: str) -> None:
        self._open_sockets.discard(sid)

    def has_socket_capacity(self) -> bool:
        """Whether the sockets now open are within the ceiling.

        Held as a set of sids rather than a count, because a count is only
        ever as right as the last event that moved it: one missed close, or
        one close counted twice, and it drifts for the life of the process -
        upwards, into refusing everybody. A set cannot drift, and it makes
        both notifications idempotent.
        """
        return len(self._open_sockets) <= self.sockets

    def admits_a_spectator(self, room: Room) -> bool:
        watching = sum(1 for player in room.players.values() if player.is_spectator)
        return watching < self.spectators_per_room

    def admits_a_join(self, sid: str) -> bool:
        """Whether this socket may take a seat again so soon.

        Charged only where a join actually seats somebody. A client confirming
        the seat it already holds - which is what its heartbeat does - never
        reaches here, so ordinary liveness checks cannot exhaust it.
        """
        return self._joins.check(sid)

    def admits_a_takeover(self, player_id: str) -> bool:
        """Whether this seat may be rebound to another socket again so soon.

        Reconnecting is an ordinary thing to do once; doing it over and over
        is how one account makes a room re-broadcast itself without ever
        taking a second seat.
        """
        return self._takeovers.check(player_id)
