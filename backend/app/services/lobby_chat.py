"""The last few lines said in the lobby, and the number each one was given.

Lobby chat rides the lobby channel but is not a feed the way presence and the
room list are. Those two describe a *state* - who is online, which rooms are
open - that the tick rebuilds from a source of truth, diffs, and numbers with
a revision a client resyncs on. A chat line is an event: there is nothing to
rebuild it from, a one-second tick is latency a conversation feels, and a
missing line is not a fault to correct - a blocked line is deliberately never
delivered to the blocker. So a line is emitted the moment it is said, and this
module keeps only what a new arrival is shown.

`seq` numbers lines within one process so a client can put the backlog it was
handed and the lines that beat it into one order without a duplicate. It is
not a revision: a client never asks for a resync because of a gap in it, and
it starts again from nothing with the process, which is fine because every
socket starts again with the process too.

The lines themselves do not start again from nothing. Every accepted line is
also retained for thirty days (`message_retention.py`), so a restart re-seeds
the ring from the most recent retained rows before the first socket arrives:
somebody landing on the lobby after a deploy sees the same conversation they
would have seen a minute before it. That read is bounded and best-effort - a
database that does not answer leaves the ring empty and the process starting,
because chat is not the thing a deploy waits on.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.bans import active_ban_filter
from app.db.models import RoomMessage, UserBan

LOBBY_CHAT_BACKLOG = 50
RESTORE_TIMEOUT_SECONDS = 10

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LobbyChatLine:
    seq: int
    user_id: str
    display_name: str
    name_color: str | None
    is_anonymous: bool
    text: str
    sent_at: datetime
    retained_message_id: str | None = None

    def payload(self) -> dict:
        """The wire shape, `LobbyChatMessage` in the wire protocol.

        Carries an account id for the reason `LobbyPlayer` does: there is no
        seat to resolve for somebody idling in the lobby, and a report needs a
        stable target. `retainedMessageId` is present only when retention took
        the row, exactly as room chat says it (R-MOD-08a).
        """
        payload = {
            "seq": self.seq,
            "userId": self.user_id,
            "displayName": self.display_name,
            "nameColor": self.name_color,
            "isAnonymous": self.is_anonymous,
            "text": self.text,
            "sentAt": self.sent_at.isoformat(),
        }
        if self.retained_message_id is not None:
            payload["retainedMessageId"] = self.retained_message_id
        return payload


class LobbyChatLog:
    """A bounded ring of the most recent lobby lines, oldest first."""

    def __init__(self, *, backlog: int = LOBBY_CHAT_BACKLOG) -> None:
        self._lines: deque[LobbyChatLine] = deque(maxlen=backlog)
        self._seq = 0

    @property
    def last_seq(self) -> int:
        """The number the most recent line was given; zero before any."""
        return self._seq

    def append(
        self,
        *,
        user_id: str,
        display_name: str,
        name_color: str | None,
        is_anonymous: bool,
        text: str,
        sent_at: datetime,
        retained_message_id: str | None = None,
    ) -> LobbyChatLine:
        """Number one accepted line and keep it.

        Called only once a line has passed every refusal, so a refused line
        never spends a number or shows up in anybody's backlog.
        """
        if sent_at.tzinfo is None:
            raise ValueError("sent_at must be timezone-aware")
        self._seq += 1
        line = LobbyChatLine(
            seq=self._seq,
            user_id=user_id,
            display_name=display_name,
            name_color=name_color,
            is_anonymous=is_anonymous,
            text=text,
            sent_at=sent_at,
            retained_message_id=retained_message_id,
        )
        self._lines.append(line)
        return line

    def restore(self, rows: Iterable[RoomMessage]) -> int:
        """Seed an empty ring from retained rows, oldest first.

        Only ever an empty one: a line said since the process started is
        newer than anything the database holds, and numbering the restored
        lines behind it would show them out of order. Returns how many were
        taken.
        """
        if self._lines or self._seq:
            raise RuntimeError("the lobby backlog can only be restored before use")
        count = 0
        for row in rows:
            if row.sender_user_id is None:
                continue
            self.append(
                user_id=str(row.sender_user_id),
                display_name=row.sender_display_name_snapshot,
                name_color=row.sender_name_color_snapshot,
                is_anonymous=row.sender_is_anonymous_snapshot,
                text=row.text,
                sent_at=row.created_at,
                retained_message_id=str(row.id),
            )
            count += 1
        return count

    def backlog_for(self, *, hidden_authors: Iterable[str] = ()) -> list[LobbyChatLine]:
        """What one arriving watcher is shown, minus the authors they blocked."""
        hidden = frozenset(hidden_authors)
        return [line for line in self._lines if line.user_id not in hidden]

    def authors(self) -> set[str]:
        """Who wrote what is held, for the block lookups an arrival needs."""
        return {line.user_id for line in self._lines}

    def drop_author(self, user_id: str) -> None:
        """Forget every line by one account.

        A deletion or a suspension ends the account; its name and its words
        must not keep being handed to every new arrival for the next fifty
        lines. The numbers already given stay spent.
        """
        kept = [line for line in self._lines if line.user_id != user_id]
        self._lines.clear()
        self._lines.extend(kept)


async def recent_lobby_lines(
    session: AsyncSession, *, limit: int = LOBBY_CHAT_BACKLOG, now: datetime | None = None
) -> list[RoomMessage]:
    """The most recent retained lobby lines, oldest first.

    Minus anything expired and anything said by an account that is suspended
    now - the ban sweep dropped those from the live ring, and a restart must
    not hand them back to the next fifty arrivals. A deleted account's rows
    are already gone (`auth/account_data.py`).
    """
    checked_at = now or datetime.now(timezone.utc)
    suspended = select(UserBan.user_id).where(*active_ban_filter(checked_at))
    rows = (
        await session.scalars(
            select(RoomMessage)
            .where(
                RoomMessage.audience == "lobby",
                RoomMessage.expires_at > checked_at,
                RoomMessage.sender_user_id.is_not(None),
                RoomMessage.sender_user_id.not_in(suspended),
            )
            .order_by(RoomMessage.created_at.desc(), RoomMessage.id.desc())
            .limit(limit)
        )
    ).all()
    return list(reversed(rows))


async def restore_lobby_backlog(
    log: LobbyChatLog,
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    bound_seconds: float = RESTORE_TIMEOUT_SECONDS,
) -> int:
    """Re-seed the ring from the database at startup; never raise.

    Bounded, because this runs before the process serves anybody and a
    database that has stopped answering must not turn a deploy into an
    outage over the chat backlog. An empty ring is the same thing a first
    ever start has.
    """
    if session_factory is None:
        return 0
    try:
        async with session_factory() as session:
            rows = await asyncio.wait_for(
                recent_lobby_lines(session), timeout=bound_seconds
            )
        return log.restore(rows)
    except Exception:
        logger.warning(
            "Could not restore the lobby chat backlog; starting with none",
            exc_info=True,
        )
        return 0
