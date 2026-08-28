"""Low-latency lookup cache for directional player blocks."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import UserBlock


logger = logging.getLogger(__name__)

# A chat line is not worth waiting on a database for. Long enough that an
# ordinary cold read succeeds, short enough that a stalled one is not felt as
# the room going quiet.
LOOKUP_TIMEOUT_SECONDS = 2


class BlockService:
    """Resolve who muted a sender without a database query per chat line.

    Live rooms intentionally run in one server process. The REST block router
    shares this instance and invalidates the affected sender after every
    change; the bounded LRU lazily repopulates from durable rows after restart.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        max_cached_senders: int = 1024,
    ) -> None:
        self._session_factory = session_factory
        self._max_cached_senders = max(1, max_cached_senders)
        self._blockers_by_sender: OrderedDict[str, frozenset[str]] = OrderedDict()

    async def blockers_of(self, blocked_user_id: str | None) -> frozenset[str]:
        """Who has muted this sender, without ever holding a message up.

        A hit is the ordinary case - the cache is warmed when the sender takes
        a seat and invalidated on every change - and a miss is a bounded read.
        A read that does not come back in time answers "nobody", and the line
        goes out unfiltered: blocking is a presentation filter, not a security
        boundary, and the sender is in the room either way, in the player list
        and on the scoreboard. Silence would be the worse failure, and one the
        sender could not see.
        """

        if not blocked_user_id:
            return frozenset()
        cached = self._blockers_by_sender.get(blocked_user_id)
        if cached is not None:
            self._blockers_by_sender.move_to_end(blocked_user_id)
            return cached
        try:
            db_user_id = UUID(blocked_user_id)
        except (ValueError, TypeError, AttributeError):
            return frozenset()
        try:
            blocker_ids = await asyncio.wait_for(
                self._read_blockers(db_user_id), timeout=LOOKUP_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.error(
                "Timed out reading blocks after %ss; delivering unfiltered",
                LOOKUP_TIMEOUT_SECONDS,
            )
            return frozenset()
        except Exception:
            logger.exception("Failed to read blocks; delivering unfiltered")
            return frozenset()
        # Only a real answer is remembered. Caching the empty set a timeout
        # returned would turn one slow read into a block that stays broken.
        self._blockers_by_sender[blocked_user_id] = blocker_ids
        self._blockers_by_sender.move_to_end(blocked_user_id)
        while len(self._blockers_by_sender) > self._max_cached_senders:
            self._blockers_by_sender.popitem(last=False)
        return blocker_ids

    async def _read_blockers(self, db_user_id: UUID) -> frozenset[str]:
        async with self._session_factory() as session:
            return frozenset(
                str(value)
                for value in (
                    await session.scalars(
                        select(UserBlock.blocker_user_id).where(
                            UserBlock.blocked_user_id == db_user_id
                        )
                    )
                ).all()
            )

    async def warm(self, blocked_user_id: str | None) -> None:
        """Read a sender's blockers ahead of their first message.

        Called from the entry path, which is already bounded and already
        refuses when the database will not answer - so the chat path is left
        with a cache hit, and the cost of a cold read is paid where waiting is
        expected rather than mid-conversation.
        """

        await self.blockers_of(blocked_user_id)

    def invalidate(self, blocked_user_id: str) -> None:
        self._blockers_by_sender.pop(blocked_user_id, None)

    def clear(self) -> None:
        self._blockers_by_sender.clear()

    def cached_senders(self) -> int:
        return len(self._blockers_by_sender)
