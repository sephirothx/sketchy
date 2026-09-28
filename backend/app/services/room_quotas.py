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

And one keyed by **address** (#1232), now that there is one worth keying on:
uvicorn rewrites the ASGI client from the forwarded header only for the proxy
`FORWARDED_ALLOW_IPS` names, and `auth/rate_limit.address_key` groups an IPv6
caller by its /64. An account costs nothing to make and a socket needs no
account at all, so the per-account ceilings alone let one laptop hold every
socket and, through 67 guests, every room.

Sockets are admitted a layer lower than rooms: `TransportLedger` counts every
Engine.IO transport from the handshake - pending or connected, polling or
WebSocket, an upgrade counted once - so a transport that never sends a
Socket.IO CONNECT is still one of its address's, and a refusal costs the
server an HTTP answer rather than a socket.
"""
from __future__ import annotations

import logging
import os
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

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
# Rooms one address may hold open (#1232): two households' worth of the
# per-account ceiling, so a family or a flat sharing one line is not refused,
# and one client minting guests cannot hold more than this many of the 200.
DEFAULT_PER_ADDRESS_ROOMS = 6
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
# Transports one address may hold (#1232). A room seats 16 players and 8
# spectators, and a school, an office or a party behind one NAT can fill one:
# 32 is that room with spare, and about 5% of the process ceiling, so taking
# the server takes about nineteen addresses rather than one laptop (600
# cookieless sockets from one address in 0.2 s, measured).
DEFAULT_SOCKETS_PER_ADDRESS = 32
# Sockets one account may hold at once: a player's tabs, with room to spare.
DEFAULT_SOCKETS_PER_ACCOUNT = 8
# Transports admitted past the process ceiling only to be told it is full
# (`server_full`, #998) and then closed. Bounded, so the notice path is not
# itself a way past the ceiling.
TURNED_AWAY_ALLOWANCE = 32
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


@dataclass(eq=False)
class TransportTicket:
    """One transport's claim on its address's allowance, from handshake to close."""

    address: str
    #: Admitted past the process ceiling: it may connect only to be told so.
    over_capacity: bool
    sid: str | None = None


class TransportLedger:
    """Every Engine.IO transport the process holds, by address (#1232).

    Admission happens at the handshake, before Engine.IO allocates a socket:
    counting at the Socket.IO CONNECT, as the ceiling used to, saw none of the
    transports that never sent one - four handshakes against a ceiling of two
    were four sockets with the count still at zero. Each ticket is taken once
    and given back once: `release` finds it by identity and does nothing the
    second time, and `reconcile` returns any a missed close left behind.
    """

    def __init__(self, capacity: "RoomCapacityService") -> None:
        self._capacity = capacity
        self._bound: dict[str, TransportTicket] = {}
        self._pending: set[TransportTicket] = set()
        self._by_address: Counter[str] = Counter()

    @property
    def open(self) -> int:
        """Transports held now, pending and connected."""
        return len(self._bound) + len(self._pending)

    def held_by(self, address: str) -> int:
        return self._by_address.get(address, 0)

    def admit(self, address: str) -> tuple[TransportTicket | None, str | None]:
        """A ticket for one more transport from `address`, or why not.

        Refused past the address's allowance, and past the process ceiling
        plus the allowance kept for telling arrivals the server is full.
        Between the two, a transport is admitted marked over capacity.
        """
        if self._by_address[address] >= self._capacity.sockets_per_address:
            return None, "address"
        held = self.open
        if held >= self._capacity.sockets + TURNED_AWAY_ALLOWANCE:
            return None, "server"
        ticket = TransportTicket(address=address, over_capacity=held >= self._capacity.sockets)
        self._pending.add(ticket)
        self._by_address[address] += 1
        return ticket, None

    def bind(self, ticket: TransportTicket, sid: str) -> None:
        """The handshake produced socket `sid`: the ticket is now its."""
        if ticket not in self._pending:
            return
        self._pending.discard(ticket)
        ticket.sid = sid
        self._bound[sid] = ticket

    def release(self, ticket: TransportTicket) -> None:
        """Give the ticket back. Once: a second call finds nothing to return."""
        if ticket.sid is not None and self._bound.get(ticket.sid) is ticket:
            del self._bound[ticket.sid]
        elif ticket in self._pending:
            self._pending.discard(ticket)
        else:
            return
        remaining = self._by_address[ticket.address] - 1
        if remaining > 0:
            self._by_address[ticket.address] = remaining
        else:
            del self._by_address[ticket.address]

    def release_sid(self, sid: str) -> None:
        ticket = self._bound.get(sid)
        if ticket is not None:
            self.release(ticket)

    def over_capacity(self, sid: str) -> bool | None:
        """Whether `sid` was admitted past the ceiling; None if it is not held."""
        ticket = self._bound.get(sid)
        return None if ticket is None else ticket.over_capacity

    def reconcile(self, live: Iterable[str]) -> int:
        """Give back the tickets of sockets that are gone, however they went."""
        alive = set(live)
        stranded = [ticket for sid, ticket in self._bound.items() if sid not in alive]
        for ticket in stranded:
            self.release(ticket)
        return len(stranded)


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
        self.per_address_rooms = _ceiling(
            values, "ROOM_PER_ADDRESS_LIMIT", DEFAULT_PER_ADDRESS_ROOMS
        )
        self.prompt_characters = _ceiling(
            values, "ROOM_PROMPT_CHARACTER_LIMIT", DEFAULT_PROMPT_CHARACTERS
        )
        self._creations_per_hour = _ceiling(
            values, "ROOM_CREATE_LIMIT", DEFAULT_CREATIONS_PER_HOUR
        )
        self._creations = (
            PersistentRateLimiter(
                session_factory,
                scope="room_create",
                limit=self._creations_per_hour,
                window_seconds=3600,
            )
            if session_factory is not None
            else None
        )

    @property
    def creations_per_hour(self) -> int:
        """The account-keyed room-creation ceiling.

        Answered from the field rather than the limiter because the limiter is
        absent without a database - the live-room ceilings are answered from
        memory, and only the creation *rate* needs a persistent bucket. A
        panel must still be able to read and set the number in that
        configuration rather than being shown a zero.
        """
        return self._creations_per_hour

    @creations_per_hour.setter
    def creations_per_hour(self, value: int) -> None:
        self._creations_per_hour = value
        if self._creations is not None:
            self._creations.limit = value

    def check_capacity(self, user_id: str, address: str | None = None) -> None:
        """Refuse a room the process, this account, or this address has no
        room for.

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
        # A guest costs nothing to make, so the account ceiling alone is one
        # client holding three rooms per name it mints (#1232).
        if address is not None and self._rooms.rooms_created_from(address) >= self.per_address_rooms:
            raise RoomQuotaExceeded(
                "Too many rooms are already open from your network. "
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
        self.sockets_per_address = _ceiling(
            values, "SOCKET_PER_ADDRESS_LIMIT", DEFAULT_SOCKETS_PER_ADDRESS
        )
        self.sockets_per_account = _ceiling(
            values, "SOCKET_PER_ACCOUNT_LIMIT", DEFAULT_SOCKETS_PER_ACCOUNT
        )
        self.transports = TransportLedger(self)
        self._account_sockets: dict[str, set[str]] = {}
        self._socket_accounts: dict[str, str] = {}
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
    def joins_per_socket_limit(self) -> int:
        return self._joins.limit

    @joins_per_socket_limit.setter
    def joins_per_socket_limit(self, value: int) -> None:
        self.joins_per_socket = value
        self._joins.limit = value

    @property
    def takeovers_per_seat_limit(self) -> int:
        return self._takeovers.limit

    @takeovers_per_seat_limit.setter
    def takeovers_per_seat_limit(self, value: int) -> None:
        self.takeovers_per_seat = value
        self._takeovers.limit = value

    @property
    def open_sockets(self) -> int:
        return len(self._open_sockets)

    def note_socket_opened(self, sid: str) -> None:
        self._open_sockets.add(sid)

    def note_socket_closed(self, sid: str) -> None:
        self._open_sockets.discard(sid)
        user_id = self._socket_accounts.pop(sid, None)
        if user_id is not None:
            held = self._account_sockets.get(user_id)
            if held is not None:
                held.discard(sid)
                if not held:
                    del self._account_sockets[user_id]

    def has_socket_capacity(self, eio_sid: str | None = None) -> bool:
        """Whether this socket is within the process ceiling.

        Decided at the Engine.IO handshake when there was one to decide it
        (#1232): the transport ledger says whether this socket's transport was
        admitted past the ceiling, to be told so. A socket the ledger never
        saw - a server without the bounded transport, as in unit tests - is
        measured against the Socket.IO sockets open now instead.

        Held as sets rather than counts, because a count is only ever as
        right as the last event that moved it: one missed close, or one close
        counted twice, and it drifts for the life of the process - upwards,
        into refusing everybody. A set cannot drift, and it makes every
        notification idempotent.
        """
        if eio_sid is not None:
            over = self.transports.over_capacity(eio_sid)
            if over is not None:
                return not over
        return len(self._open_sockets) <= self.sockets

    def admit_account_socket(self, sid: str, user_id: str | None) -> bool:
        """Count `sid` against its account's allowance, or refuse it.

        A cookieless socket has no account to count against; the address
        ceiling at the handshake is what bounds those.
        """
        if not user_id:
            return True
        held = self._account_sockets.setdefault(user_id, set())
        if sid not in held and len(held) >= self.sockets_per_account:
            if not held:
                del self._account_sockets[user_id]
            return False
        held.add(sid)
        self._socket_accounts[sid] = user_id
        return True

    def account_sockets(self, user_id: str) -> int:
        return len(self._account_sockets.get(user_id, ()))

    def admits_a_spectator(self, room: Room) -> bool:
        watching = sum(1 for player in room.players.values() if player.is_spectator)
        return watching < self.spectators_per_room

    def admits_a_join(self, sid: str) -> bool:
        """Whether this socket may take a seat again so soon.

        Charged on the attempt and given back by `refund_join` when the seat
        does not happen, so that only a join which actually seated somebody
        costs anything. A client confirming the seat it already holds - which
        is what its heartbeat does - never reaches here at all, so ordinary
        liveness checks cannot exhaust it.
        """
        return self._joins.check(sid)

    def refund_join(self, sid: str) -> None:
        """Give back an attempt that seated nobody.

        A full room is the ordinary case: without this, a client retrying one
        is eventually told it is going too quickly, which is untrue and hides
        the `room_full` code the invite screen hangs its offer to spectate on.
        """
        self._joins.refund(sid)

    def admits_a_takeover(self, player_id: str) -> bool:
        """Whether this seat may be rebound to another socket again so soon.

        Reconnecting is an ordinary thing to do once; doing it over and over
        is how one account makes a room re-broadcast itself without ever
        taking a second seat.
        """
        return self._takeovers.check(player_id)

    def refund_takeover(self, player_id: str) -> None:
        """Give back a takeover that rebound nobody (#1009).

        Charged before the seat is rebound, so a rebind refused or failed
        before that point - an account being ended, seating raising - used
        to cost the seat an attempt and, once the ceiling was reached, to
        change the reason it was given. A rebind that did supersede the old
        socket is kept: the broadcast it cost the room has happened.
        """
        self._takeovers.refund(player_id)
