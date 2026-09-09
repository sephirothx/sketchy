"""Incremental, merge-scoped and full rebuild paths for bounded-cost profile statistics."""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.domain_values import AccountState, GameOutcome
from app.db.models import (
    GameParticipant,
    GameRecord,
    IdentityAlias,
    TurnDrawingReaction,
    TurnParticipantOutcome,
    TurnRecord,
    User,
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
    reactions_received: int = 0


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
    reaction_drawer_ids: list[UUID | None] = (),
) -> None:
    """Atomically add one newly persisted game's facts to its daily rows.

    `reaction_drawer_ids` names, once per reaction, the drawer whose drawing
    it was left on; like `drawings_made` it counts for every outcome, because
    the drawing was made and reacted to whether or not the game reached its
    end.

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
    canonical_reacted_drawers = [
        aliases.get(user_id, user_id)
        for user_id in reaction_drawer_ids
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
            "reactions_received": canonical_reacted_drawers.count(user_id),
        }
        # Ascending account id: two games sharing accounts in opposite seat
        # order then take the projection rows in the same order, and cannot
        # deadlock on them (#609).
        for user_id, standings in sorted(grouped.items(), key=lambda item: item[0].int)
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
                "reactions_received": UserStatsDaily.reactions_received
                + excluded.reactions_received,
                "updated_at": func.now(),
            },
        )
    )


async def adjust_reactions_received(
    session: AsyncSession,
    *,
    user_id: UUID,
    finished_at: datetime,
    delta: int,
) -> None:
    """Move one drawer's received-reactions count after their game was written.

    A reaction given from the recap or from history lands on a game whose
    projection rows already exist, so it is a delta rather than a row. The
    day is the game's, not today's, so a rebuild - which only knows the game -
    reproduces the same totals. A decrement is guarded rather than trusted:
    the projection is disposable and may have been rebuilt or erased since the
    reaction it is undoing was counted, and the non-negative CHECK would
    otherwise turn a stale row into a failed write.
    """
    if delta == 0:
        return
    aliases = await _alias_map(session, {user_id})
    canonical_id = aliases.get(user_id, user_id)
    stat_date = _utc_date(finished_at)
    if delta > 0:
        statement = _projection_insert(session).values(
            [
                {
                    "user_id": canonical_id,
                    "stat_date": stat_date,
                    "reactions_received": delta,
                }
            ]
        )
        excluded = statement.excluded
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "stat_date"],
                set_={
                    "reactions_received": UserStatsDaily.reactions_received
                    + excluded.reactions_received,
                    "updated_at": func.now(),
                },
            )
        )
        return
    await session.execute(
        update(UserStatsDaily)
        .where(
            UserStatsDaily.user_id == canonical_id,
            UserStatsDaily.stat_date == stat_date,
            UserStatsDaily.reactions_received >= -delta,
        )
        .values(
            reactions_received=UserStatsDaily.reactions_received + delta,
            updated_at=func.now(),
        )
    )


# How many canonical accounts one rebuild transaction covers. The working
# set of a rebuild is proportional to this times the accounts' history, not
# to the deployment's, and the bind lists it sends are the batch's identity
# ids rather than every game those identities ever played (#609).
REBUILD_BATCH_ACCOUNTS = 100
# Deadlock and serialization failures are the two outcomes PostgreSQL asks a
# caller to retry; each batch below is a whole idempotent transaction, so
# retrying one is safe.
_TRANSIENT_SQLSTATES = frozenset({"40001", "40P01"})
REBUILD_RETRIES = 3


def _is_transient(error: BaseException) -> bool:
    origin = getattr(error, "orig", None)
    return getattr(origin, "sqlstate", None) in _TRANSIENT_SQLSTATES


# How many days one merge may rebuild by naming them. A guest carries the
# handful of days its browser played on, so the predicate below is a short
# list; a guest that played on more days than this is not the case the
# scoping exists for, and rebuilding the account whole - what every merge did
# before #709 - stays correct rather than sending an OR of a hundred ranges
# no planner will thank us for.
MERGE_REBUILD_DAY_LIMIT = 92


def _finished_on(days: set[date], games=GameRecord):
    """`games.finished_at` falls on one of these UTC days.

    A half-open range per day rather than a cast to a date: the cast that
    yields the *UTC* day differs by dialect - PostgreSQL's `::date` reads the
    session's time zone, SQLite has no timestamp type to cast - while a
    comparison against two aware datetimes means the same thing on both, and
    stays a predicate over a stored column rather than an expression the
    planner has no statistics for.
    """
    return or_(
        *(
            and_(
                games.finished_at >= start,
                games.finished_at < start + timedelta(days=1),
            )
            for start in (
                datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
                for day in sorted(days)
            )
        )
    )


# Rows per fetch when a rebuild streams facts: the reads below are keyed by
# a batch of accounts but an account may have played for years, and the
# totals need one pass, not the rows.
REBUILD_FETCH_ROWS = 1_000


async def _stream(session: AsyncSession, statement):
    result = await session.stream(
        statement, execution_options={"yield_per": REBUILD_FETCH_ROWS}
    )
    async for row in result:
        yield row


async def _identity_sets(
    session: AsyncSession, account_ids: list[UUID]
) -> dict[UUID, set[UUID]]:
    """Each canonical account with every identity that resolves to it."""
    sets = {account_id: {account_id} for account_id in account_ids}
    for source_id, target_id in (
        await session.execute(
            select(IdentityAlias.source_user_id, IdentityAlias.target_user_id).where(
                IdentityAlias.target_user_id.in_(account_ids)
            )
        )
    ).all():
        sets[target_id].add(source_id)
    return sets


async def _rebuild_accounts(
    session: AsyncSession,
    account_ids: list[UUID],
    *,
    days: set[date] | None = None,
) -> int:
    """Replace the rows of one bounded batch of canonical accounts, locked.

    `days` narrows both the facts read and the rows replaced to those UTC
    days, which is what a merge needs (`fold_identity_into_account`): every
    other day's row already holds the same total it would be rewritten with.
    Whole days, never a single identity's share of one, because a day's row
    counts games rather than seats and a shared game must be counted once.

    The identities' `users` rows are locked `FOR UPDATE` in ascending id
    order first - the same order the finished-game write locks them in - so
    a game that commits while this runs either commits before the facts are
    read here, or waits and increments the rows this writes. Without the
    lock a game could commit between the read and the delete below and its
    increment would be replaced by the older total.

    Every query is keyed by the batch's identity ids; the games those
    identities played are a subquery, never a bind list, so an account with
    more games than the driver can bind still rebuilds in one statement.
    """
    if not account_ids:
        return 0
    identity_sets = await _identity_sets(session, account_ids)
    canonical_of = {
        identity: canonical
        for canonical, identities in identity_sets.items()
        for identity in identities
    }
    identity_ids = sorted(canonical_of, key=lambda value: value.int)
    await session.execute(
        select(User.id)
        .where(User.id.in_(identity_ids))
        .order_by(User.id)
        .with_for_update()
    )

    on_days = _finished_on(days) if days is not None else None
    totals: dict[tuple[UUID, date], _DailyTotals] = defaultdict(_DailyTotals)
    game_users: dict[UUID, set[UUID]] = defaultdict(set)
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
        .where(GameParticipant.user_id.in_(identity_ids))
    )
    if on_days is not None:
        participant_statement = participant_statement.where(on_days)
    async for source_id, game_id, rank, score, finished_at, outcome in _stream(
        session, participant_statement
    ):
        canonical_id = canonical_of[source_id]
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
        batch_games = select(GameParticipant.game_id).where(
            GameParticipant.user_id.in_(identity_ids)
        )
        if days is not None:
            # The turn read below walks the games this subquery names, so a
            # scoped rebuild narrows it here as well as on the outer
            # statement: the list to walk is then the day's games rather
            # than the account's. Its own alias of `game_records`, because
            # the enclosing statement names that table too and a subquery
            # sharing it is one SQLAlchemy may correlate to the outer row
            # instead of joining here.
            scoped = aliased(GameRecord)
            batch_games = batch_games.join(
                scoped, scoped.id == GameParticipant.game_id
            ).where(_finished_on(days, scoped))
        turn_statement = (
            select(TurnRecord.game_id, TurnRecord.drawer_user_id, GameRecord.finished_at)
            .join(GameRecord, GameRecord.id == TurnRecord.game_id)
            .where(TurnRecord.game_id.in_(batch_games))
        )
        if on_days is not None:
            turn_statement = turn_statement.where(on_days)
        async for game_id, drawer_id, finished_at in _stream(session, turn_statement):
            day = _utc_date(finished_at)
            for canonical_id in game_users[game_id]:
                totals[(canonical_id, day)].turns_played += 1
            canonical_drawer = canonical_of.get(drawer_id)
            if canonical_drawer is not None and canonical_drawer in game_users[game_id]:
                totals[(canonical_drawer, day)].drawings_made += 1

        guess_statement = (
            select(GameParticipant.user_id, TurnRecord.game_id, GameRecord.finished_at)
            .select_from(TurnParticipantOutcome)
            .join(TurnRecord, TurnRecord.id == TurnParticipantOutcome.turn_id)
            .join(GameRecord, GameRecord.id == TurnRecord.game_id)
            .join(
                GameParticipant,
                GameParticipant.id == TurnParticipantOutcome.participant_id,
            )
            .where(
                TurnParticipantOutcome.outcome == "correct",
                GameParticipant.user_id.in_(identity_ids),
            )
        )
        if on_days is not None:
            guess_statement = guess_statement.where(on_days)
        async for guesser_id, game_id, finished_at in _stream(session, guess_statement):
            canonical_guesser = canonical_of[guesser_id]
            if canonical_guesser in game_users[game_id]:
                totals[(canonical_guesser, _utc_date(finished_at))].prompts_guessed += 1

        reaction_statement = (
            select(TurnRecord.drawer_user_id, TurnRecord.game_id, GameRecord.finished_at)
            .select_from(TurnDrawingReaction)
            .join(TurnRecord, TurnRecord.id == TurnDrawingReaction.turn_id)
            .join(GameRecord, GameRecord.id == TurnRecord.game_id)
            .where(TurnRecord.drawer_user_id.in_(identity_ids))
        )
        if on_days is not None:
            reaction_statement = reaction_statement.where(on_days)
        async for drawer_id, game_id, finished_at in _stream(
            session, reaction_statement
        ):
            canonical_drawer = canonical_of[drawer_id]
            if canonical_drawer in game_users[game_id]:
                totals[(canonical_drawer, _utc_date(finished_at))].reactions_received += 1

    # Deleted by day as well when scoped, so a day whose facts are all gone
    # loses its stale row: the rows written below are only the days that
    # still have facts.
    replaced = delete(UserStatsDaily).where(UserStatsDaily.user_id.in_(identity_ids))
    if days is not None:
        replaced = replaced.where(UserStatsDaily.stat_date.in_(sorted(days)))
    await session.execute(replaced)
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
            reactions_received=daily.reactions_received,
        )
        for (canonical_id, stat_date), daily in sorted(
            totals.items(), key=lambda item: (item[0][0].int, item[0][1])
        )
    )
    await session.flush()
    return len(totals)


async def _canonical_account(session: AsyncSession, user_id: UUID) -> UUID:
    target = await session.scalar(
        select(IdentityAlias.target_user_id).where(
            IdentityAlias.source_user_id == user_id
        )
    )
    return target or user_id


async def _days_with_facts(session: AsyncSession, user_id: UUID) -> set[date]:
    """Every UTC day one identity has a finished game or a projection row on.

    The days come back as timestamps to be reduced here rather than as a
    `GROUP BY` over a date expression, because that expression is the one
    thing about a day that PostgreSQL and SQLite do not spell the same way,
    and the rows are one identity's games - a guest's - not an account's.
    """
    days = {
        _utc_date(finished_at)
        async for (finished_at,) in _stream(
            session,
            select(GameRecord.finished_at)
            .join(GameParticipant, GameParticipant.game_id == GameRecord.id)
            .where(GameParticipant.user_id == user_id)
            .distinct(),
        )
    }
    days.update(
        (
            await session.scalars(
                select(UserStatsDaily.stat_date).where(
                    UserStatsDaily.user_id == user_id
                )
            )
        ).all()
    )
    return days


async def _account_batches(session: AsyncSession, batch_size: int):
    """Canonical accounts in ascending id order, `batch_size` at a time, by keyset."""
    last: UUID | None = None
    while True:
        statement = (
            select(User.id)
            .where(User.state != AccountState.MERGED.value)
            .order_by(User.id)
            .limit(batch_size)
        )
        if last is not None:
            statement = statement.where(User.id > last)
        batch = list((await session.scalars(statement)).all())
        if not batch:
            return
        yield batch
        last = batch[-1]


async def rebuild_user_stats_in_session(
    session: AsyncSession,
    *,
    user_id: UUID | None = None,
    batch_size: int = REBUILD_BATCH_ACCOUNTS,
) -> int:
    """Replace one canonical account's rows, or every account's, in the caller's transaction.

    Every day of every identity that resolves to the account, which is what
    an operator repairing drift asks for. A merge wants a narrower thing and
    has `fold_identity_into_account` for it.
    """
    if user_id is not None:
        return await _rebuild_accounts(session, [await _canonical_account(session, user_id)])
    rows = 0
    async for batch in _account_batches(session, batch_size):
        rows += await _rebuild_accounts(session, batch)
    return rows


async def fold_identity_into_account(
    session: AsyncSession,
    *,
    source_user_id: UUID,
    target_user_id: UUID,
) -> int:
    """Fold a merged identity's days into its account, in the caller's transaction.

    Called by a guest merge with the source and target `users` rows already
    locked, so the rebuild joins the merge's own transaction and the merged
    identity's games are counted exactly once with it.

    A merge cannot change a day the guest has nothing on: the account's row
    for every other day already counts exactly the games it will count
    afterwards. So only the guest's days are read and replaced, and the work
    is bounded by the guest's history rather than by the account's. That
    distinction is the whole point of doing it here - this runs inside the
    sign-in request, on the web role's seconds rather than the maintenance
    role's minutes (#709), and a rebuild of a long-lived account's entire
    finished-game history does not belong on a player's login.

    The guest's own rows are part of the scope: `stat_date` is taken from
    them as well as from its games, so a projection row left on a day whose
    facts are gone is replaced rather than orphaned under a merged id.
    """
    days = await _days_with_facts(session, source_user_id)
    if not days:
        return 0
    account = await _canonical_account(session, target_user_id)
    return await _rebuild_accounts(
        session,
        [account],
        days=days if len(days) <= MERGE_REBUILD_DAY_LIMIT else None,
    )


async def rebuild_user_stats_projection(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID | None = None,
    batch_size: int = REBUILD_BATCH_ACCOUNTS,
) -> int:
    """Maintenance entry point: one account in one transaction, or every account in bounded ones.

    A full rebuild is a sequence of independent batch transactions, each
    holding only its accounts' rows and each complete in itself, so an
    interrupted rebuild leaves every finished batch correct and is simply run
    again. A batch that loses to a deadlock or serialization failure is
    retried whole.
    """
    if user_id is not None:
        async with session_factory() as session:
            async with session.begin():
                return await rebuild_user_stats_in_session(session, user_id=user_id)
    rows = 0
    async with session_factory() as cursor_session:
        async for batch in _account_batches(cursor_session, batch_size):
            for attempt in range(REBUILD_RETRIES):
                try:
                    async with session_factory() as session:
                        async with session.begin():
                            rows += await _rebuild_accounts(session, batch)
                    break
                except DBAPIError as error:
                    if not _is_transient(error) or attempt == REBUILD_RETRIES - 1:
                        raise
    return rows


async def _run_cli(user_id: UUID | None) -> None:
    from app.db import init_db, maintenance_engine

    engine, factory = maintenance_engine()
    try:
        await init_db(engine)
        rows = await rebuild_user_stats_projection(factory, user_id=user_id)
        print(f"Rebuilt {rows} daily user-stat projection rows.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild profile statistics from immutable game history."
    )
    parser.add_argument("--user", type=UUID, help="Rebuild one canonical account")
    args = parser.parse_args()
    asyncio.run(_run_cli(args.user))


if __name__ == "__main__":
    main()
