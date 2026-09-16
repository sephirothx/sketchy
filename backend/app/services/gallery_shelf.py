"""The lobby's **This week** shelf (#524, R-GAL-07): Top-week's first six, computed at most once a minute."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import hashlib
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.interfaces import GalleryEntry, GameHistoryRepository
from app.services import config_store

# The operator switch (R-GAL-10): set, the shelf shows only released
# drawings and the moderation queue lists the undecided candidates. The page
# publishes after the fact either way. Read per shelf recompute, never cached
# beyond the shelf's own minute, for the reason the publication switch is not.
SHELF_REVIEW_KEY = "gallery.shelf_review"
SHELF_REVIEW_EVENT = "gallery.shelf_review_changed"

SHELF_SIZE = 6
SHELF_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class ShelfSnapshot:
    """What the lobby shows, and a version that names exactly this list:
    the turn ids and their counts, so a validator changes when they do."""

    entries: tuple[GalleryEntry, ...]
    version: str


def _version_of(entries: tuple[GalleryEntry, ...]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(entry.turn_id.encode())
        digest.update(repr(sorted(entry.reaction_counts.items())).encode())
    return digest.hexdigest()[:24]


async def read_shelf_review(session_factory: async_sessionmaker[AsyncSession]) -> bool:
    """Whether the lobby's shelf waits for a moderator's release."""
    return await config_store.read_one(session_factory, SHELF_REVIEW_KEY) == "1"


def shelf_reader(
    repo: GameHistoryRepository,
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], Awaitable[tuple[GalleryEntry, ...]]]:
    """The read behind the cache: Top-week's first six, released ones only
    while the switch is set. A hidden drawing is out either way (R-GAL-01)."""

    async def read() -> tuple[GalleryEntry, ...]:
        review = await read_shelf_review(session_factory)
        page = await repo.list_gallery(
            sort="top",
            window="week",
            limit=SHELF_SIZE,
            shelf_filter="released" if review else None,
        )
        return page.entries

    return read


class GalleryShelfCache:
    """One process-wide snapshot of the shelf, recomputed at most once a
    minute and shared by every lobby that opens (R-GAL-07, #462).

    The viewer's own facts - their pick, whether a drawing is theirs - are
    deliberately not here: the snapshot is the same for everyone, and the
    route adds those per request from a query over at most six turns. A
    moderation decision on the shelf calls `invalidate`, so a hide never
    waits a minute to take effect.
    """

    def __init__(
        self,
        read: Callable[[], Awaitable[tuple[GalleryEntry, ...]]],
        *,
        ttl_seconds: float = SHELF_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._read = read
        self._ttl = ttl_seconds
        self._clock = clock
        self._snapshot: ShelfSnapshot | None = None
        self._read_at = float("-inf")
        self._lock = asyncio.Lock()
        # Bumped by every invalidation. A read that started before the bump
        # was taken from the shelf as it was, and must not be installed as
        # if it were current (#524 review): the hide would wait a minute.
        self._generation = 0

    def _fresh(self) -> bool:
        return self._snapshot is not None and self._clock() - self._read_at < self._ttl

    async def get(self) -> ShelfSnapshot:
        if self._fresh():
            return self._snapshot
        async with self._lock:
            # Whoever waited on the lock finds the snapshot the first arrival
            # wrote: one read per minute, however many lobbies open at once.
            if self._fresh():
                return self._snapshot
            while True:
                generation = self._generation
                entries = await self._read()
                if generation == self._generation:
                    break
                # Invalidated while the read was out: read again, so the
                # caller gets the shelf after the decision, not before it.
            self._snapshot = ShelfSnapshot(entries=entries, version=_version_of(entries))
            self._read_at = self._clock()
            return self._snapshot

    def invalidate(self) -> None:
        self._generation += 1
        self._read_at = float("-inf")
