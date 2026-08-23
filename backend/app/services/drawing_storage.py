"""Operator check that every stored drawing is still readable.

A stored drawing is only as good as the decoder that can read it back, and
both of those - the checksum recorded beside the bytes, and the registry entry
naming the format - are silent until something asks. This walks the stored
rows in bounded batches and asks.

It is also how a second stored format proves itself: after one is introduced,
a clean run is the evidence that every row written under either format still
decodes.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.canvas_storage import (
    CorruptStoredDrawingError,
    UnsupportedStoredDrawingError,
    stored_drawing_wire_payload,
)
from app.db import async_engine, async_session_factory, init_db
from app.db.models import TurnDrawing
from app.domain_values import TurnDrawingStatus


DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True)
class DrawingVerification:
    checked: int
    corrupt: list[str]
    unreadable: list[str]

    @property
    def ok(self) -> bool:
        return not self.corrupt and not self.unreadable


async def verify_stored_drawings(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> DrawingVerification:
    """Decode a bounded batch of stored drawings and report what failed."""

    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    corrupt: list[str] = []
    unreadable: list[str] = []
    checked = 0
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(TurnDrawing)
                .where(
                    TurnDrawing.status == TurnDrawingStatus.READY.value,
                    TurnDrawing.payload.is_not(None),
                )
                .order_by(TurnDrawing.created_at)
                .limit(batch_size)
            )
        ).all()
        for row in rows:
            checked += 1
            try:
                stored_drawing_wire_payload(
                    row.payload, checksum=row.checksum_sha256 or None
                )
            except CorruptStoredDrawingError:
                corrupt.append(str(row.turn_id))
            except UnsupportedStoredDrawingError:
                unreadable.append(str(row.turn_id))
    return DrawingVerification(
        checked=checked, corrupt=corrupt, unreadable=unreadable
    )


async def _run(args) -> DrawingVerification:
    try:
        await init_db()
        return await verify_stored_drawings(
            async_session_factory, batch_size=args.batch_size
        )
    finally:
        await async_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Decode a bounded batch of stored drawings and report failures."
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()
    result = asyncio.run(_run(args))
    print(f"Checked {result.checked} stored drawings.")
    if result.corrupt:
        print(f"Failed checksum ({len(result.corrupt)}): {', '.join(result.corrupt)}")
    if result.unreadable:
        print(
            f"No decoder ({len(result.unreadable)}): {', '.join(result.unreadable)}"
        )
    if result.ok:
        print("Every drawing decoded.")
    else:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
