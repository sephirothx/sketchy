"""Database-backed room-code allocation and retirement."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import secrets
import string

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import RoomCodeReservation


ROOM_CODE_ALPHABET = string.ascii_uppercase + string.digits
ROOM_CODE_LENGTH = 6
EPHEMERAL_CODE_RETENTION = timedelta(days=30)
MAX_ALLOCATION_ATTEMPTS = 64


def generate_room_code() -> str:
    """Generate an invite capability; UUID locality is inappropriate here."""

    return "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LENGTH))


class RoomCodeAllocationError(RuntimeError):
    pass


class RoomCodeService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        code_factory: Callable[[], str] = generate_room_code,
    ) -> None:
        self._session_factory = session_factory
        self._code_factory = code_factory

    async def allocate(self, *, kind: str = "ephemeral") -> str:
        if kind not in {"ephemeral", "persistent"}:
            raise ValueError("unsupported room code kind")
        purged = False
        for _ in range(MAX_ALLOCATION_ATTEMPTS):
            code = self._code_factory().strip().upper()
            if (
                len(code) != ROOM_CODE_LENGTH
                or any(character not in ROOM_CODE_ALPHABET for character in code)
            ):
                raise ValueError("room code factory returned an invalid code")
            try:
                async with self._session_factory() as session:
                    async with session.begin():
                        session.add(RoomCodeReservation(code=code, kind=kind))
                return code
            except IntegrityError:
                # The primary key is the cross-request/process collision guard.
                # An expired retirement only matters when its code is drawn
                # again, so the purge happens on that collision rather than in
                # every room creation.
                if not purged:
                    await self.purge_expired()
                    purged = True
                continue
        raise RoomCodeAllocationError("Could not allocate a unique room code")

    async def release_unpublished(self, code: str) -> None:
        """Release an allocation that was never returned to a player."""

        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    delete(RoomCodeReservation).where(
                        RoomCodeReservation.code == code.strip().upper(),
                        RoomCodeReservation.retired_until.is_(None),
                    )
                )

    async def retire_ephemeral(self, code: str) -> None:
        retired_until = datetime.now(timezone.utc) + EPHEMERAL_CODE_RETENTION
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(RoomCodeReservation)
                    .where(
                        RoomCodeReservation.code == code.strip().upper(),
                        RoomCodeReservation.kind == "ephemeral",
                        RoomCodeReservation.retired_until.is_(None),
                    )
                    .values(retired_until=retired_until)
                )

    async def retire_orphaned_ephemeral(self) -> int:
        """Retire live-only codes left active by a restart or process crash."""

        retired_until = datetime.now(timezone.utc) + EPHEMERAL_CODE_RETENTION
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    update(RoomCodeReservation)
                    .where(
                        RoomCodeReservation.kind == "ephemeral",
                        RoomCodeReservation.retired_until.is_(None),
                    )
                    .values(retired_until=retired_until)
                )
        return result.rowcount or 0

    async def is_retired(self, code: str) -> bool:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            retired_until = await session.scalar(
                select(RoomCodeReservation.retired_until).where(
                    RoomCodeReservation.code == code.strip().upper(),
                    RoomCodeReservation.kind == "ephemeral",
                )
            )
        return retired_until is not None and retired_until > now

    async def purge_expired(self) -> int:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    delete(RoomCodeReservation).where(
                        RoomCodeReservation.kind == "ephemeral",
                        RoomCodeReservation.retired_until.is_not(None),
                        RoomCodeReservation.retired_until <= now,
                    )
                )
        return result.rowcount or 0
