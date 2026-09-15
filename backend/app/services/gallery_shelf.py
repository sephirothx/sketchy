"""The lobby's **This week** shelf (#524, R-GAL-07): Top-week's first six, computed at most once a minute."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import hashlib
import time

from app.repositories.interfaces import GalleryEntry

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

    async def get(self) -> ShelfSnapshot:
        if self._snapshot is not None and self._clock() - self._read_at < self._ttl:
            return self._snapshot
        async with self._lock:
            # Whoever waited on the lock finds the snapshot the first arrival
            # wrote: one read per minute, however many lobbies open at once.
            if self._snapshot is not None and self._clock() - self._read_at < self._ttl:
                return self._snapshot
            entries = await self._read()
            self._snapshot = ShelfSnapshot(entries=entries, version=_version_of(entries))
            self._read_at = self._clock()
            return self._snapshot

    def invalidate(self) -> None:
        self._read_at = float("-inf")
