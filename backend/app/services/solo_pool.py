"""Solo's pool (#1434): which recorded drawings it may serve, written and rebuilt.

`solo_pool` is a projection of game facts. A turn is in it when its game was
public, its prompt curated, somebody in the game named it, and its drawing
was kept with at least `MIN_POOL_STROKES` actions. The finished-game write
adds a game's rows in its own transaction (`write_pool_rows`), and
`python -m app.services.solo_pool` rebuilds the whole table from the facts,
a batch of games at a time.

Only what a finished game cannot change is stored. A moderator's hide, the
drawer's opt-out or take-out, a prompt's takedown or rating are asked when a
drawing is served (`app.repositories.solo`), so undoing any of them needs no
write here. Erasure is final: `erase_pool_rows` deletes the rows, and the
query below would not select an erased drawing again.
"""
from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    GameRecord,
    PromptVersion,
    SoloPoolEntry,
    TurnDrawing,
    TurnParticipantOutcome,
    TurnRecord,
)
from app.domain_values import (
    GameVisibility,
    PromptSourceKind,
    TurnDrawingStatus,
    TurnParticipantOutcome as Outcome,
)
from app.solo_rules import MIN_POOL_CORRECT_GUESSERS, MIN_POOL_STROKES, sample_key

REBUILD_BATCH_GAMES = 500


def _correct_counts():
    return (
        select(
            TurnParticipantOutcome.turn_id.label("turn_id"),
            func.count().label("correct"),
        )
        .where(TurnParticipantOutcome.outcome == Outcome.CORRECT.value)
        .group_by(TurnParticipantOutcome.turn_id)
        .subquery()
    )


def pool_query() -> Select:
    """Every turn that belongs in the pool, as the rows it would hold (less
    the sample key, which is derived from the turn id). The one definition
    the finished-game write, the rebuild and the integrity audit share."""
    correct = _correct_counts()
    return (
        select(
            TurnRecord.id.label("turn_id"),
            TurnRecord.game_id,
            PromptVersion.concept_id,
            TurnRecord.prompt_version_id,
            TurnRecord.drawer_user_id,
            TurnRecord.guesser_count,
            correct.c.correct.label("correct_count"),
            GameRecord.finished_at,
        )
        .join(GameRecord, GameRecord.id == TurnRecord.game_id)
        .join(TurnDrawing, TurnDrawing.turn_id == TurnRecord.id)
        .join(PromptVersion, PromptVersion.id == TurnRecord.prompt_version_id)
        .join(correct, correct.c.turn_id == TurnRecord.id)
        .where(
            GameRecord.visibility == GameVisibility.PUBLIC.value,
            TurnRecord.prompt_source_kind == PromptSourceKind.CURATED.value,
            TurnRecord.stroke_count >= MIN_POOL_STROKES,
            correct.c.correct >= MIN_POOL_CORRECT_GUESSERS,
            TurnDrawing.status == TurnDrawingStatus.READY.value,
            TurnDrawing.moderation_erased_at.is_(None),
        )
    )


def pool_row(row) -> dict:
    """A selected row as it is stored."""
    return {
        "turn_id": row.turn_id,
        "game_id": row.game_id,
        "concept_id": row.concept_id,
        "prompt_version_id": row.prompt_version_id,
        "drawer_user_id": row.drawer_user_id,
        # A guesser count below the correct count is a game written before
        # the count was recorded; the CHECK wants the pair consistent.
        "guesser_count": max(int(row.guesser_count), int(row.correct_count)),
        "correct_count": int(row.correct_count),
        "finished_at": row.finished_at,
        "sample_key": sample_key(row.turn_id),
    }


def _insert_ignoring_existing(session: AsyncSession, rows: list[dict]):
    dialect = session.get_bind().dialect.name
    build = postgresql_insert if dialect == "postgresql" else sqlite_insert
    return build(SoloPoolEntry).values(rows).on_conflict_do_nothing(
        index_elements=[SoloPoolEntry.turn_id]
    )


async def write_pool_rows(session: AsyncSession, game_ids: Iterable[UUID]) -> int:
    """Add the pool rows of `game_ids`, in the caller's transaction. Called
    by the finished-game write once its turns, drawings and outcomes are
    flushed, so a game is in the pool exactly when it is in history."""
    ids = list(game_ids)
    if not ids:
        return 0
    rows = [
        pool_row(row)
        for row in (await session.execute(pool_query().where(TurnRecord.game_id.in_(ids)))).all()
    ]
    if rows:
        await session.execute(_insert_ignoring_existing(session, rows))
    return len(rows)


async def erase_pool_rows(
    session: AsyncSession,
    *,
    turn_ids: Iterable[UUID] = (),
    drawer_user_ids: Iterable[UUID] = (),
) -> None:
    """Take erased drawings out of the pool, in the eraser's transaction:
    one drawing (`erase_drawing_for_moderation`) or every drawing of an
    account and its aliases (`anonymize_account`)."""
    turns = list(turn_ids)
    drawers = list(drawer_user_ids)
    if turns:
        await session.execute(delete(SoloPoolEntry).where(SoloPoolEntry.turn_id.in_(turns)))
    if drawers:
        await session.execute(
            delete(SoloPoolEntry).where(SoloPoolEntry.drawer_user_id.in_(drawers))
        )


async def _rebuild_batch(session: AsyncSession, after: UUID | None) -> tuple[int, UUID | None]:
    statement = select(GameRecord.id).order_by(GameRecord.id).limit(REBUILD_BATCH_GAMES)
    if after is not None:
        statement = statement.where(GameRecord.id > after)
    game_ids = list((await session.scalars(statement)).all())
    if not game_ids:
        return 0, None
    await session.execute(delete(SoloPoolEntry).where(SoloPoolEntry.game_id.in_(game_ids)))
    written = await write_pool_rows(session, game_ids)
    return written, game_ids[-1]


async def rebuild_solo_pool(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Replace every game's pool rows with what its facts say, one
    transaction per batch of games: the pool is never empty while it is
    rebuilt, and an interrupted rebuild is simply run again."""
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
        rows = await rebuild_solo_pool(factory)
        print(f"Rebuilt the Solo pool: {rows} drawings.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild the drawings Solo may serve from the recorded games."
    )
    parser.parse_args()
    asyncio.run(_run_cli())


if __name__ == "__main__":
    main()
