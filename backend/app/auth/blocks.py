"""Low-latency lookup cache for directional player blocks."""
from __future__ import annotations

from collections import OrderedDict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import UserBlock


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
        async with self._session_factory() as session:
            blocker_ids = frozenset(
                str(value)
                for value in (
                    await session.scalars(
                        select(UserBlock.blocker_user_id).where(
                            UserBlock.blocked_user_id == db_user_id
                        )
                    )
                ).all()
            )
        self._blockers_by_sender[blocked_user_id] = blocker_ids
        self._blockers_by_sender.move_to_end(blocked_user_id)
        while len(self._blockers_by_sender) > self._max_cached_senders:
            self._blockers_by_sender.popitem(last=False)
        return blocker_ids

    def invalidate(self, blocked_user_id: str) -> None:
        self._blockers_by_sender.pop(blocked_user_id, None)

    def clear(self) -> None:
        self._blockers_by_sender.clear()

    def cached_senders(self) -> int:
        return len(self._blockers_by_sender)
