"""Incremental and full rebuild paths for bounded-cost profile statistics."""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain_values import GameOutcome
from app.db.models import (
    GameParticipant,
    GameRecord,
    IdentityAlias,
    TurnGuess,
    TurnRecord,
    UserStatsDaily,
)


@dataclass
class _DailyTotals:
    games: set[UUID] = field(default_factory=set)
    wins: set[UUID] = field(default_factory=set)
    total_score: int = 0
    turns_played: int = 0
    prompts_guessed: int = 0
    drawings_made: int = 0


def _utc_date(value: datetime) -> date:
    if value.tzinfo is None:
        raise ValueError("Finished-game timestamps must include a timezone")
    return value.astimezone(timezone.utc).date()


async def _alias_map(
    session: AsyncSession, user_ids: set[UUID] | None = None
) -> dict[UUID, UUID]:
    statement = select(
        IdentityAlias.source_user_id, IdentityAlias.target_user_id
    )
    if user_ids is not None:
        statement = statement.where(IdentityAlias.source_user_id.in_(user_ids))
    return dict((await session.execute(statement)).all())


def _projection_insert(session: AsyncSession):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return postgresql_insert(UserStatsDaily)
    if dialect == "sqlite":
        return sqlite_insert(UserStatsDaily)
    raise RuntimeError(f"Unsupported user-stat projection dialect: {dialect}")


async def increment_user_stats_projection(
    session: AsyncSession,
    *,
    finished_at: datetime,
    participants: list[tuple[UUID | None, int, int]],
    turn_drawer_ids: list[UUID | None],
    guess_user_ids: list[UUID | None],
    counts_as_played: bool = True,
) -> None:
    """Atomically add one newly persisted game's facts to its daily rows.

    An abandoned game contributes the turns that were actually drawn and
    guessed, but not a game played, not a game won, and not a score. The turns
    happened; the game did not, and counting it would let a room that empties
    repeatedly inflate everyone's totals - and would distort the average score,
    which divides by games played.
    """
    user_ids = {
        user_id
        for user_id, _, _ in participants
        if user_id is not None
    }
    if not user_ids:
        return
    aliases = await _alias_map(session, user_ids)

    grouped: dict[UUID, list[tuple[int, int]]] = defaultdict(list)
    for user_id, final_score, final_rank in participants:
        if user_id is not None:
            grouped[aliases.get(user_id, user_id)].append(
                (final_score, final_rank)
            )

    canonical_drawers = [
        aliases.get(user_id, user_id)
        for user_id in turn_drawer_ids
        if user_id is not None
    ]
    canonical_guessers = [
        aliases.get(user_id, user_id)
        for user_id in guess_user_ids
        if user_id is not None
    ]
    stat_date = _utc_date(finished_at)
    rows = [
        {
            "user_id": user_id,
            "stat_date": stat_date,
            "games_played": 1 if counts_as_played else 0,
            "games_won": (
                int(any(rank == 1 for _, rank in standings))
                if counts_as_played
                else 0
            ),
            "total_score": (
                sum(score for score, _ in standings) if counts_as_played else 0
            ),
            # Preserve the established profile contract: this is the count of
            # turns in games the identity participated in, once per game even
            # when two later-merged identities occupied distinct seats.
            "turns_played": len(turn_drawer_ids),
            "prompts_guessed": canonical_guessers.count(user_id),
            "drawings_made": canonical_drawers.count(user_id),
        }
        for user_id, standings in grouped.items()
    ]
    statement = _projection_insert(session).values(rows)
    excluded = statement.excluded
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["user_id", "stat_date"],
            set_={
                "games_played": UserStatsDaily.games_played
                + excluded.games_played,
                "games_won": UserStatsDaily.games_won + excluded.games_won,
                "total_score": UserStatsDaily.total_score + excluded.total_score,
                "turns_played": UserStatsDaily.turns_played
                + excluded.turns_played,
                "prompts_guessed": UserStatsDaily.prompts_guessed
                + excluded.prompts_guessed,
                "drawings_made": UserStatsDaily.drawings_made
                + excluded.drawings_made,
                "updated_at": func.now(),
            },
        )
    )


async def rebuild_user_stats_in_session(
    session: AsyncSession, *, user_id: UUID | None = None
) -> int:
    """Replace all or one canonical account's rows from immutable history."""
    aliases = await _alias_map(session)
    target_id: UUID | None = None
    identity_ids: set[UUID] | None = None
    if user_id is not None:
        target_id = aliases.get(user_id, user_id)
        identity_ids = {
            target_id,
            *(source for source, target in aliases.items() if target == target_id),
        }

    participant_statement = (
        select(
            GameParticipant.user_id,
            GameParticipant.game_id,
            GameParticipant.final_rank,
            GameParticipant.final_score,
            GameRecord.finished_at,
            GameRecord.outcome,
        )
        .join(GameRecord, GameRecord.id == GameParticipant.game_id)
        .where(GameParticipant.user_id.is_not(None))
    )
    if identity_ids is not None:
        participant_statement = participant_statement.where(
            GameParticipant.user_id.in_(identity_ids)
        )

    totals: dict[tuple[UUID, date], _DailyTotals] = defaultdict(_DailyTotals)
    game_users: dict[UUID, set[UUID]] = defaultdict(set)
    for source_id, game_id, rank, score, finished_at, outcome in (
        await session.execute(participant_statement)
    ).all():
        canonical_id = aliases.get(source_id, source_id)
        if target_id is not None and canonical_id != target_id:
            continue
        day = _utc_date(finished_at)
        daily = totals[(canonical_id, day)]
        # A game that stopped is still a seat somebody sat in, so their turns
        # and guesses count. The game, the win and the score do not - the same
        # rule the incremental path applies, so a rebuild reproduces it rather
        # than quietly correcting it upward.
        if outcome == GameOutcome.FINISHED.value:
            daily.games.add(game_id)
            if rank == 1:
                daily.wins.add(game_id)
            daily.total_score += score
        game_users[game_id].add(canonical_id)

    if game_users:
        turn_statement = (
            select(
                TurnRecord.id,
                TurnRecord.game_id,
                TurnRecord.drawer_user_id,
                GameRecord.finished_at,
            )
            .join(GameRecord, GameRecord.id == TurnRecord.game_id)
            .where(TurnRecord.game_id.in_(game_users))
        )
        for _, game_id, drawer_id, finished_at in (
            await session.execute(turn_statement)
        ).all():
            day = _utc_date(finished_at)
            for canonical_id in game_users[game_id]:
                totals[(canonical_id, day)].turns_played += 1
            if drawer_id is not None:
                canonical_drawer = aliases.get(drawer_id, drawer_id)
                if canonical_drawer in game_users[game_id]:
                    totals[(canonical_drawer, day)].drawings_made += 1

        guess_statement = (
            select(TurnGuess.user_id, TurnRecord.game_id, GameRecord.finished_at)
            .join(TurnRecord, TurnRecord.id == TurnGuess.turn_id)
            .join(GameRecord, GameRecord.id == TurnRecord.game_id)
            .where(
                TurnGuess.user_id.is_not(None),
                TurnRecord.game_id.in_(game_users),
            )
        )
        for guesser_id, game_id, finished_at in (
            await session.execute(guess_statement)
        ).all():
            canonical_guesser = aliases.get(guesser_id, guesser_id)
            if canonical_guesser in game_users[game_id]:
                totals[
                    (canonical_guesser, _utc_date(finished_at))
                ].prompts_guessed += 1

    if identity_ids is None:
        await session.execute(delete(UserStatsDaily))
    else:
        await session.execute(
            delete(UserStatsDaily).where(UserStatsDaily.user_id.in_(identity_ids))
        )
    session.add_all(
        UserStatsDaily(
            user_id=canonical_id,
            stat_date=stat_date,
            games_played=len(daily.games),
            games_won=len(daily.wins),
            total_score=daily.total_score,
            turns_played=daily.turns_played,
            prompts_guessed=daily.prompts_guessed,
            drawings_made=daily.drawings_made,
        )
        for (canonical_id, stat_date), daily in sorted(
            totals.items(), key=lambda item: (item[0][0].int, item[0][1])
        )
    )
    await session.flush()
    return len(totals)


async def rebuild_user_stats_projection(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID | None = None,
) -> int:
    """Transactional maintenance entry point for a full or targeted rebuild."""
    async with session_factory() as session:
        async with session.begin():
            return await rebuild_user_stats_in_session(session, user_id=user_id)


async def _run_cli(user_id: UUID | None) -> None:
    from app.db import async_engine, async_session_factory, init_db

    try:
        await init_db()
        rows = await rebuild_user_stats_projection(
            async_session_factory, user_id=user_id
        )
        print(f"Rebuilt {rows} daily user-stat projection rows.")
    finally:
        await async_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild profile statistics from immutable game history."
    )
    parser.add_argument("--user", type=UUID, help="Rebuild one canonical account")
    args = parser.parse_args()
    asyncio.run(_run_cli(args.user))


if __name__ == "__main__":
    main()
