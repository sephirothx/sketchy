"""The Gallery (#524): the predicate, the three orders, the projections that
serve them, and the rebuild that reproduces them."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from uuid import UUID

from sqlalchemy import select, update

from app.db.models import TurnDrawing, TurnDrawingReaction
from app.domain_values import TurnDrawingStatus
from app.services.gallery_ranking import (
    HOT_DECAY_SECONDS,
    MAX_GALLERY_OFFSET,
    hot_score,
    rebuild_gallery_ranking,
)
import pytest_asyncio

from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from tests.dbfixtures import create_test_db
from tests.test_drawing_reactions import record_game, registered


@pytest_asyncio.fixture
async def repos():
    factory, engine = await create_test_db()
    try:
        yield (
            SqlAlchemyUserRepository(factory),
            SqlAlchemyGameHistoryRepository(factory),
            factory,
        )
    finally:
        await engine.dispose()


NOW = datetime.now(timezone.utc)


def _ids(page) -> list[str]:
    return [entry.turn_id for entry in page.entries]


async def _count_and_score(factory, turn_id: str) -> tuple[int, float]:
    async with factory() as session:
        row = await session.get(TurnDrawing, UUID(turn_id))
        return row.reaction_count, row.hot_score


async def test_the_score_is_reddits_and_the_projections_follow_every_write(repos):
    """`log10(max(n, 1)) + finished_at / 45 000 s`: set with the game, moved
    by every reaction write under the row's lock, zeroed by erasure."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    cid = await registered(users, "Cid")
    finished = NOW - timedelta(hours=1)
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, reactions="default",
        visibility="public", finished_at=finished,
    )
    base = finished.timestamp() / HOT_DECAY_SECONDS
    assert hot_score(0, finished) == base
    assert hot_score(1, finished) == base
    assert math.isclose(hot_score(10, finished), base + 1)

    count, score = await _count_and_score(factory, game.turn_id)
    assert count == 1 and math.isclose(score, hot_score(1, finished))

    await history.set_drawing_reaction(
        None, game.turn_id, requesting_user_id=cid.id, emoji="wow", from_gallery=True
    )
    count, score = await _count_and_score(factory, game.turn_id)
    assert count == 2 and math.isclose(score, hot_score(2, finished))
    assert score > hot_score(1, finished)

    await history.set_drawing_reaction(
        game.game_id, game.turn_id, requesting_user_id=bob.id, emoji=None
    )
    count, score = await _count_and_score(factory, game.turn_id)
    assert count == 1 and math.isclose(score, hot_score(1, finished))

    # A rebuild reproduces exactly what the writes left, from the rows.
    async with factory() as session:
        await session.execute(
            update(TurnDrawing).values(reaction_count=7, hot_score=0.0)
        )
        await session.commit()
    assert await rebuild_gallery_ranking(factory) >= 1
    assert await _count_and_score(factory, game.turn_id) == (1, hot_score(1, finished))


async def test_the_gallery_shows_every_kept_public_drawing_and_nothing_else(repos):
    """Public and ready is the whole predicate (R-GAL-01): a private game, a
    drawing never kept and an erased one are out, a drawing with no reactions
    is in, and the viewer's own facts ride along without an account id."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    cid = await registered(users, "Cid")
    shown = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", finished_at=NOW - timedelta(hours=3))
    await record_game(history, drawer=ann.id, reactor=bob.id, visibility="private", finished_at=NOW - timedelta(hours=2))
    await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", drawing=False, finished_at=NOW - timedelta(hours=1))
    erased = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", reactions="default", finished_at=NOW - timedelta(minutes=30))
    async with factory() as session:
        await session.execute(
            update(TurnDrawing)
            .where(TurnDrawing.turn_id == UUID(erased.turn_id))
            .values(
                status=TurnDrawingStatus.DELETED.value, payload=None,
                checksum_sha256=None, byte_size=None, format_magic=None,
                format_version=None, deleted_at=NOW,
            )
        )
        await session.commit()

    for sort in ("hot", "new", "top"):
        page = await history.list_gallery(sort=sort, requesting_user_id=cid.id)
        assert _ids(page) == [shown.turn_id], sort
    [entry] = (await history.list_gallery(requesting_user_id=cid.id)).entries
    assert entry.reaction_counts == {} and entry.my_reaction is None
    assert entry.drawn_by_me is False and entry.prompt == "lighthouse"
    assert entry.drawer_display_name == "Drawer"

    await history.set_drawing_reaction(
        None, shown.turn_id, requesting_user_id=cid.id, emoji="fire", from_gallery=True
    )
    [entry] = (await history.list_gallery(requesting_user_id=cid.id)).entries
    assert entry.reaction_counts == {"fire": 1} and entry.my_reaction == "fire"
    [entry] = (await history.list_gallery(requesting_user_id=ann.id)).entries
    assert entry.my_reaction is None and entry.drawn_by_me is True
    [entry] = (await history.list_gallery()).entries
    assert entry.my_reaction is None and entry.drawn_by_me is False

    # The bytes and the validator answer through the same predicate.
    assert (await history.get_gallery_drawing(shown.turn_id)) is not None
    assert (await history.get_gallery_drawing_checksum(shown.turn_id)) is not None
    assert (await history.get_gallery_drawing(erased.turn_id)) is None
    assert (await history.get_gallery_drawing_checksum(erased.turn_id)) is None
    assert (await history.get_gallery_drawing("not-an-id")) is None


async def test_the_three_orders_and_their_tie_breaks(repos):
    """New is the latest finish first; Top is the most reactions first, then
    the earlier finish; Hot is the score, which a reaction lifts by a decade
    per tenfold and time by a day per 45 000 s (R-GAL-04)."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    reactors = [await registered(users, f"R{i}") for i in range(3)]
    # Three public games: old with two reactions, middle with none, fresh with one.
    old = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", finished_at=NOW - timedelta(days=2))
    middle = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", finished_at=NOW - timedelta(days=1))
    fresh = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", finished_at=NOW - timedelta(hours=1))
    for who in reactors[:2]:
        await history.set_drawing_reaction(None, old.turn_id, requesting_user_id=who.id, emoji="heart", from_gallery=True)
    await history.set_drawing_reaction(None, fresh.turn_id, requesting_user_id=reactors[2].id, emoji="wow", from_gallery=True)

    assert _ids(await history.list_gallery(sort="new")) == [fresh.turn_id, middle.turn_id, old.turn_id]
    assert _ids(await history.list_gallery(sort="top")) == [old.turn_id, fresh.turn_id, middle.turn_id]
    # Two reactions on a two-day-old drawing lose to one on a fresh one: a
    # decade of reactions buys 12.5 hours, and the fresh one has 47 more.
    assert _ids(await history.list_gallery(sort="hot")) == [fresh.turn_id, middle.turn_id, old.turn_id]

    # A tie on the count is broken by the earlier finish, then the turn id.
    tied = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", finished_at=NOW - timedelta(days=1))
    assert _ids(await history.list_gallery(sort="top")) == [old.turn_id, fresh.turn_id, middle.turn_id, tied.turn_id]
    assert _ids(await history.list_gallery(sort="top")) == _ids(await history.list_gallery(sort="top"))


async def test_windows_and_the_hot_horizon(repos):
    """Top over a week or a month leaves older games out; Hot looks back
    fourteen days and no further; a bad sort or window is an empty page."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    cid = await registered(users, "Cid")
    ancient = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", finished_at=NOW - timedelta(days=40))
    last_month = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", finished_at=NOW - timedelta(days=20))
    last_week = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", finished_at=NOW - timedelta(days=3))
    for game in (ancient, last_month):
        await history.set_drawing_reaction(None, game.turn_id, requesting_user_id=cid.id, emoji="fire", from_gallery=True)

    assert _ids(await history.list_gallery(sort="top", window="all")) == [ancient.turn_id, last_month.turn_id, last_week.turn_id]
    assert _ids(await history.list_gallery(sort="top", window="month")) == [last_month.turn_id, last_week.turn_id]
    assert _ids(await history.list_gallery(sort="top", window="week")) == [last_week.turn_id]
    assert _ids(await history.list_gallery(sort="hot")) == [last_week.turn_id]
    assert _ids(await history.list_gallery(sort="new")) == [last_week.turn_id, last_month.turn_id, ancient.turn_id]
    assert (await history.list_gallery(sort="best")).entries == ()
    assert (await history.list_gallery(sort="top", window="year")).entries == ()


async def test_pages_are_a_cursor_that_stops_480_deep(repos):
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    games = [
        await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", finished_at=NOW - timedelta(minutes=i))
        for i in range(5)
    ]
    first = await history.list_gallery(sort="new", limit=2)
    assert _ids(first) == [games[0].turn_id, games[1].turn_id] and first.next_cursor
    second = await history.list_gallery(sort="new", limit=2, cursor=first.next_cursor)
    assert _ids(second) == [games[2].turn_id, games[3].turn_id] and second.next_cursor
    third = await history.list_gallery(sort="new", limit=2, cursor=second.next_cursor)
    assert _ids(third) == [games[4].turn_id] and third.next_cursor is None
    # A mangled cursor is page one; a page past the ceiling is empty.
    assert _ids(await history.list_gallery(sort="new", limit=2, cursor="???")) == _ids(first)
    deep = await history.list_gallery(sort="new", cursor=str(MAX_GALLERY_OFFSET))
    assert deep.entries == () and deep.next_cursor is None
    # The page size is clamped, never trusted.
    assert len(_ids(await history.list_gallery(sort="new", limit=999))) == 5


async def test_a_reaction_the_room_gave_counts_beside_an_outsiders(repos):
    """The listed counts are every row; the rebuild agrees with them."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    cid = await registered(users, "Cid")
    game = await record_game(history, drawer=ann.id, reactor=bob.id, reactions="default", visibility="public", finished_at=NOW - timedelta(hours=1))
    await history.set_drawing_reaction(None, game.turn_id, requesting_user_id=cid.id, emoji="heart", from_gallery=True)
    [entry] = (await history.list_gallery()).entries
    assert entry.reaction_counts == {"heart": 2}
    async with factory() as session:
        rows = (await session.scalars(select(TurnDrawingReaction))).all()
        assert sorted(row.participant_id is None for row in rows) == [False, True]
    await rebuild_gallery_ranking(factory)
    assert (await _count_and_score(factory, game.turn_id))[0] == 2
