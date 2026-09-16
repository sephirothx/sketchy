"""The Gallery's ranking projections (#524): the Hot score, and their rebuild."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import math
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import GameRecord, TurnDrawing, TurnDrawingReaction

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


def hot_score(reaction_count: int, finished_at: datetime) -> float:
    """`log10(max(n, 1)) + finished_at / 45 000 s`: kept on the row rather than
    computed in the query, because the score of one row never changes except
    when its count does - the decay is the newer rows' larger second term."""
    seconds = finished_at.replace(tzinfo=finished_at.tzinfo or timezone.utc).timestamp()
    return math.log10(max(reaction_count, 1)) + seconds / HOT_DECAY_SECONDS


def _count_by_turn():
    return (
        select(func.count())
        .select_from(TurnDrawingReaction)
        .where(TurnDrawingReaction.turn_id == TurnDrawing.turn_id)
        .scalar_subquery()
    )


async def rebuild_gallery_ranking_in_session(session: AsyncSession) -> int:
    """Replace every drawing's count and score with what the reaction rows
    say, in the caller's transaction. Returns how many rows were written.

    Streamed and written in bounded batches keyed by turn id, so a history of
    any size rebuilds without binding it whole; a reaction landing meanwhile
    sets its own row after this read and wins, since the row's write is the
    later one.
    """
    written = 0
    last: UUID | None = None
    while True:
        statement = (
            select(TurnDrawing.turn_id, GameRecord.finished_at, _count_by_turn())
            .join(GameRecord, GameRecord.id == TurnDrawing.game_id)
            .order_by(TurnDrawing.turn_id)
            .limit(REBUILD_BATCH_ROWS)
        )
        if last is not None:
            statement = statement.where(TurnDrawing.turn_id > last)
        rows = (await session.execute(statement)).all()
        if not rows:
            return written
        for turn_id, finished_at, count in rows:
            await session.execute(
                update(TurnDrawing)
                .where(TurnDrawing.turn_id == turn_id)
                .values(
                    reaction_count=int(count),
                    hot_score=hot_score(int(count), finished_at),
                )
            )
            written += 1
        last = rows[-1][0]


async def rebuild_gallery_ranking(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Maintenance entry point: the whole rebuild in one transaction, batched
    only in how it reads; a rebuild is a repair, run rarely and never on a
    player's request."""
    async with session_factory() as session:
        async with session.begin():
            return await rebuild_gallery_ranking_in_session(session)


async def _run_cli() -> None:
    from app.db import init_db, maintenance_engine

    engine, factory = maintenance_engine()
    try:
        await init_db(engine)
        rows = await rebuild_gallery_ranking(factory)
        print(f"Rebuilt the reaction count and Hot score of {rows} drawings.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild the Gallery's reaction counts and Hot scores from the reaction rows."
    )
    parser.parse_args()
    asyncio.run(_run_cli())


if __name__ == "__main__":
    main()
