"""The Gallery's routes (#524): the page for anyone signed in, the bytes
through the third door, and every refusal."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.errors import install_refusal_handler
from app.api.gallery import create_gallery_router, gallery_limiter
from app.auth.middleware import SessionAuthMiddleware
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from tests.dbfixtures import create_test_db
from tests.test_api_profiles import _registered, sign_in_as
from tests.test_drawing_reactions import record_game


@pytest_asyncio.fixture
async def env():
    session_factory, engine = await create_test_db()
    gallery_limiter.reset()
    users = SqlAlchemyUserRepository(session_factory)
    history = SqlAlchemyGameHistoryRepository(session_factory)
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=session_factory)
    app.include_router(create_gallery_router(history))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, users, history, session_factory
    await engine.dispose()


NOW = datetime.now(timezone.utc)


async def test_the_gallery_is_for_any_session_and_no_session_gets_nothing(env):
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    cid = await _registered(users, "Cid")
    guest = await users.create_anonymous(display_name="Guest")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, reactions="default",
        visibility="public", finished_at=NOW - timedelta(hours=1),
    )
    await record_game(history, drawer=ann.id, reactor=bob.id, visibility="private", finished_at=NOW - timedelta(hours=2))

    refused = await http.get("/api/gallery")
    assert refused.status_code == 403
    assert refused.json()["errorCode"] == "account_required"
    assert refused.json()["params"] == {"action": "gallery"}
    assert (await http.get(f"/api/gallery/{game.turn_id}/drawing")).status_code == 404

    await sign_in_as(http, factory, guest.id)
    page = (await http.get("/api/gallery")).json()
    assert [entry["turnId"] for entry in page["entries"]] == [game.turn_id]
    assert page["nextCursor"] is None
    [entry] = page["entries"]
    assert set(entry) == {
        "turnId", "roundNumber", "turnNumber", "drawerDisplayName", "drawerNameColor",
        "drawerIsAnonymous", "prompt", "strokeCount", "finishedAt", "reactionCounts",
        "myReaction", "drawnByMe",
    }
    assert "gameId" not in entry and entry["reactionCounts"] == {"heart": 1}
    assert entry["myReaction"] is None and entry["drawnByMe"] is False
    bytes_answer = await http.get(f"/api/gallery/{game.turn_id}/drawing")
    assert bytes_answer.status_code == 200
    assert bytes_answer.headers["cache-control"] == "private, no-cache"
    validator = bytes_answer.headers["etag"]
    again = await http.get(f"/api/gallery/{game.turn_id}/drawing", headers={"If-None-Match": validator})
    assert again.status_code == 304 and again.content == b""

    await sign_in_as(http, factory, cid.id)
    await http.put(f"/api/gallery/{game.turn_id}/reaction", json={"emoji": "wow"})
    [entry] = (await http.get("/api/gallery?sort=top&window=week")).json()["entries"]
    assert entry["reactionCounts"] == {"heart": 1, "wow": 1} and entry["myReaction"] == "wow"
    await sign_in_as(http, factory, ann.id)
    [entry] = (await http.get("/api/gallery?sort=new")).json()["entries"]
    assert entry["drawnByMe"] is True and entry["myReaction"] is None

    for query in ("sort=best", "window=year", "sort=top&window=year"):
        answer = await http.get(f"/api/gallery?{query}")
        assert answer.status_code == 422, query
        assert answer.json()["errorCode"] == "unknown_sort"
    assert (await http.get("/api/gallery?limit=0")).status_code == 422
    assert (await http.get("/api/gallery?limit=25")).status_code == 422


async def test_the_third_door_closes_with_the_predicate(env):
    """Unknown turn, a private game, a drawing never kept: 404, and a
    remembered validator sees no further (R-HIST-24)."""
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    cid = await _registered(users, "Cid")
    private = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="private", finished_at=NOW)
    unkept = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", drawing=False, finished_at=NOW)
    await sign_in_as(http, factory, cid.id)
    for turn in (private.turn_id, unkept.turn_id, "not-an-id"):
        assert (await http.get(f"/api/gallery/{turn}/drawing")).status_code == 404
        assert (
            await http.get(f"/api/gallery/{turn}/drawing", headers={"If-None-Match": 'W/"x"'})
        ).status_code == 404


# ---- the lobby's shelf (R-GAL-07)


async def test_this_week_is_top_weeks_first_six_from_one_cached_snapshot(env):
    """Six at most, the most reacted this week first, computed once a minute
    for everyone, with the viewer's own facts added per request and a
    validator that answers 304 until the shelf or those facts move."""
    from app.services.gallery_shelf import GalleryShelfCache

    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    cid = await _registered(users, "Cid")
    games = [
        await record_game(
            history, drawer=ann.id, reactor=bob.id, visibility="public",
            finished_at=NOW - timedelta(hours=i + 1),
        )
        for i in range(8)
    ]
    await record_game(history, drawer=ann.id, reactor=bob.id, reactions="default", visibility="public", finished_at=NOW - timedelta(days=9))
    await history.set_drawing_reaction(None, games[3].turn_id, requesting_user_id=cid.id, emoji="fire", from_gallery=True)

    assert (await http.get("/api/gallery/week")).status_code == 403

    await sign_in_as(http, factory, bob.id)
    first = await http.get("/api/gallery/week")
    assert first.status_code == 200
    ids = [entry["turnId"] for entry in first.json()["entries"]]
    assert len(ids) == 6 and ids[0] == games[3].turn_id
    assert first.json()["entries"][0]["reactionCounts"] == {"fire": 1}
    assert first.headers["cache-control"] == "private, no-cache"
    validator = first.headers["etag"]
    again = await http.get("/api/gallery/week", headers={"If-None-Match": validator})
    assert again.status_code == 304 and again.content == b""

    # The snapshot is shared: a reaction landing now is not on the shelf
    # until the minute is up, but the viewer's own facts are theirs at once.
    await sign_in_as(http, factory, cid.id)
    mine = await http.get("/api/gallery/week")
    assert mine.json()["entries"][0]["myReaction"] == "fire"
    assert mine.headers["etag"] != validator
    await sign_in_as(http, factory, ann.id)
    theirs = await http.get("/api/gallery/week")
    assert theirs.json()["entries"][0]["drawnByMe"] is True
    assert theirs.json()["entries"][0]["myReaction"] is None

    # The cache itself: one read for many callers, then one more after the ttl.
    reads = 0

    async def read():
        nonlocal reads
        reads += 1
        return (await history.list_gallery(sort="top", window="week", limit=6)).entries

    now = [1000.0]
    cache = GalleryShelfCache(read, ttl_seconds=60, clock=lambda: now[0])
    snapshots = await asyncio.gather(*(cache.get() for _ in range(5)))
    assert reads == 1 and len({s.version for s in snapshots}) == 1
    now[0] += 59
    assert (await cache.get()).version == snapshots[0].version and reads == 1
    now[0] += 2
    await cache.get()
    assert reads == 2
    cache.invalidate()
    await cache.get()
    assert reads == 3
