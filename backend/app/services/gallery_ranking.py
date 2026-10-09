"""The Gallery's projections (#524, #1430): counts, first share, Hot score, rebuild.

The reaction count, the share count, the first share and the Hot score are kept
on each drawing row so the Gallery orders by a column; the rebuild reproduces
them from the rows."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import math
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import TurnDrawing, TurnDrawingReaction, TurnDrawingShare

# Reddit's constant: a decade of reactions is worth 45 000 seconds, twelve and
# a half hours. With at most sixteen seats in a room, the room's own verdict
# buys a drawing a little over a day; the Gallery's outsiders can buy more.
HOT_DECAY_SECONDS = 45_000
# How far back Hot looks (R-GAL-04). Nothing older can be hot: a drawing two
# weeks old would need ten to the power of 27 reactions to catch a fresh one.
HOT_HORIZON = timedelta(days=14)
# Top's windows, by name on the wire. `None` is all time.
TOP_WINDOWS: dict[str, timedelta | None] = {
    "all": None,
    "month": timedelta(days=30),
    "week": timedelta(days=7),
}
REBUILD_BATCH_ROWS = 1000
# The community catalogue's paging rules, for the same reason (R-GAL-04).
MAX_GALLERY_PAGE = 24
MAX_GALLERY_OFFSET = 480


def hot_score(reaction_count: int, shared_at: datetime | None) -> float:
    """`log10(max(n, 1)) + shared_at / 45 000 s`: kept on the row rather than
    computed in the query, because the score of one row never changes except
    when its count or its first share does - the decay is the newer rows'
    larger second term. Measured from the first share, not the game's finish
    (#1430): a drawing shared from history a month later enters the Gallery
    that day, and is new there. Zero while nobody has shared it - no order
    reads an unshared row, and a constant keeps the rebuild exact."""
    if shared_at is None:
        return 0.0
    seconds = shared_at.replace(tzinfo=shared_at.tzinfo or timezone.utc).timestamp()
    return math.log10(max(reaction_count, 1)) + seconds / HOT_DECAY_SECONDS


def aware(moment: datetime | str | None) -> datetime | None:
    """A timestamp read raw - an aggregate, on SQLite a string or a naive
    value - as the aware moment every write compares it with."""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    if moment is not None and moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def drawing_hot_score(drawing: TurnDrawing) -> float:
    """A loaded row's Hot score from its own projections: measured from when it
    entered the Gallery, and zero while nobody shares it."""
    return hot_score(
        drawing.reaction_count,
        drawing.gallery_shared_at if drawing.gallery_share_count > 0 else None,
    )


def _earlier(kept: datetime | None, found: datetime | None) -> datetime | None:
    kept, found = aware(kept), aware(found)
    if kept is None:
        return found
    if found is None:
        return kept
    return min(kept, found)


async def refresh_share_projection(session: AsyncSession, drawing: TurnDrawing) -> None:
    """Set a drawing row's share count, first share and Hot score from its
    share rows, in the caller's transaction and under the row lock the caller
    holds (R-GAL-05): the count is the rows', never an increment. The first
    share is kept once set - taking the last share back and sharing again is
    not a new entry (R-SHARE-05) - and is moved only earlier, which is what a
    finished game's live share written after a later one does."""
    await session.flush()
    count, first = (
        await session.execute(
            select(func.count(), func.min(TurnDrawingShare.created_at)).where(
                TurnDrawingShare.turn_id == drawing.turn_id
            )
        )
    ).one()
    drawing.gallery_share_count = int(count)
    drawing.gallery_shared_at = _earlier(drawing.gallery_shared_at, first)
    drawing.hot_score = drawing_hot_score(drawing)


def _count_by_turn():
    return (
        select(func.count())
        .select_from(TurnDrawingReaction)
        .where(TurnDrawingReaction.turn_id == TurnDrawing.turn_id)
        .scalar_subquery()
    )


def _first_share_by_turn():
    return (
        select(func.min(TurnDrawingShare.created_at))
        .where(TurnDrawingShare.turn_id == TurnDrawing.turn_id)
        .scalar_subquery()
    )


def _shares_by_turn():
    return (
        select(func.count())
        .select_from(TurnDrawingShare)
        .where(TurnDrawingShare.turn_id == TurnDrawing.turn_id)
        .scalar_subquery()
    )


async def _rebuild_batch(session: AsyncSession, after: UUID | None) -> tuple[int, UUID | None]:
    """One batch of rows, locked before they are counted: a reaction or a
    share landing meanwhile waits for the batch and then sets the row itself,
    so what is written here is never staler than the rows it was read from."""
    locked = (
        select(TurnDrawing.turn_id)
        .order_by(TurnDrawing.turn_id)
        .limit(REBUILD_BATCH_ROWS)
        .with_for_update()
    )
    if after is not None:
        locked = locked.where(TurnDrawing.turn_id > after)
    turn_ids = list((await session.scalars(locked)).all())
    if not turn_ids:
        return 0, None
    rows = (
        await session.execute(
            select(
                TurnDrawing.turn_id,
                TurnDrawing.gallery_shared_at,
                _first_share_by_turn(),
                _shares_by_turn(),
                _count_by_turn(),
            ).where(TurnDrawing.turn_id.in_(turn_ids))
        )
    ).all()
    for turn_id, kept, first, shares, count in rows:
        shared_at = _earlier(kept, first)
        await session.execute(
            update(TurnDrawing)
            .where(TurnDrawing.turn_id == turn_id)
            .values(
                reaction_count=int(count),
                gallery_share_count=int(shares),
                gallery_shared_at=shared_at,
                hot_score=hot_score(int(count), shared_at if shares else None),
            )
        )
    return len(rows), turn_ids[-1]


async def rebuild_gallery_ranking_in_session(session: AsyncSession) -> int:
    """Replace every drawing's count, first share and score with what the
    reaction and share rows say, in the caller's transaction. Returns how many rows were written."""
    written = 0
    last: UUID | None = None
    while True:
        count, last = await _rebuild_batch(session, last)
        if last is None:
            return written
        written += count


async def rebuild_gallery_ranking(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Maintenance entry point: one transaction per batch of rows, keyed by
    turn id, so a rebuild of any history holds each row's lock for one batch
    and a reaction never waits for the whole run; an interrupted rebuild
    leaves every finished batch correct and is simply run again."""
    written = 0
    last: UUID | None = None
    while True:
        async with session_factory() as session:
            async with session.begin():
                count, last = await _rebuild_batch(session, last)
        if last is None:
            return written
        written += count


async def _run_cli() -> None:
    from app.db import init_db, maintenance_engine

    engine, factory = maintenance_engine()
    try:
        await init_db(engine)
        rows = await rebuild_gallery_ranking(factory)
        print(f"Rebuilt the reaction count, first share and Hot score of {rows} drawings.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild the Gallery's reaction counts, first shares and Hot scores "
            "from the reaction and share rows."
        )
    )
    parser.parse_args()
    asyncio.run(_run_cli())


if __name__ == "__main__":
    main()
