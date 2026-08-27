"""Ceilings on room creation, so one client cannot spend the whole server.

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

from app.auth.rate_limit import PersistentRateLimiter
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
