"""The Gallery's routes (#524): the page for anyone signed in, the bytes
through the third door, and every refusal."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from sqlalchemy import select

from app.api.errors import install_refusal_handler
from app.api.gallery import create_gallery_router, gallery_limiter
from app.api.moderation import create_moderation_router
from app.api.profiles import create_profile_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.sessions import COOKIE_NAME, create_session, device_label_from_user_agent
from app.db.models import (
    AuditEvent,
    GalleryShelfReview,
    PlayerReport,
    PlayerReportDrawingEvidence,
    TurnDrawing,
    User,
)
from app.domain_values import UserRole
from app.services import config_store
from app.services.gallery_shelf import SHELF_REVIEW_KEY, GalleryShelfCache, shelf_reader
from tests.staffauth import mark_staff_ready
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
    shelf = GalleryShelfCache(shelf_reader(history, session_factory))
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=session_factory)
    app.include_router(create_profile_router(users, history))
    app.include_router(create_gallery_router(history, shelf=shelf))
    app.include_router(
        create_moderation_router(
            session_factory,
            game_history_repo=history,
            on_gallery_decision=shelf.invalidate,
        )
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, users, history, session_factory
    await engine.dispose()


async def _moderator(users, factory, name: str):
    account = await _registered(users, name)
    async with factory() as session:
        async with session.begin():
            row = await session.get(User, UUID(account.id))
            row.role = UserRole.MODERATOR.value
    return account


async def _as_moderator(http, factory, user_id: str) -> None:
    """A fresh session, used once, then stepped up (R-AUTH-21).

    The stamp is on sessions, not on the account, and a session's first
    request from a device it was not issued to drops its step-up - so the
    session is introduced to the client with one harmless read before it is
    stamped, the way a real moderator's session has been used before they
    confirm their authenticator.
    """
    issued = await create_session(
        factory,
        user_id=user_id,
        # The label the middleware derives from this client's user agent:
        # a session used from a browser it was not issued to drops its
        # step-up, so the session is issued to the one that will use it.
        device_label=device_label_from_user_agent(http.headers.get("user-agent")),
    )
    http.cookies.set(COOKIE_NAME, issued.token)
    await mark_staff_ready(factory, user_id)


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


# ---- moderation (R-GAL-08..10)


async def test_hiding_takes_a_drawing_out_of_every_gallery_door_and_nowhere_else(env):
    """Hidden: gone from the page, the shelf, the bytes and the reaction door in
    one act; still in the players' own history. Released puts it back."""
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    cid = await _registered(users, "Cid")
    mod = await _moderator(users, factory, "Mod")
    game = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", finished_at=NOW - timedelta(hours=1))

    await sign_in_as(http, factory, mod.id)
    refused = await http.patch(f"/api/moderation/gallery/{game.turn_id}", json={"decision": "hidden", "note": "not for the lobby"})
    assert refused.status_code == 403, "step-up first"
    await _as_moderator(http, factory, mod.id)
    decided = await http.patch(f"/api/moderation/gallery/{game.turn_id}", json={"decision": "hidden", "note": "not for the lobby"})
    assert decided.status_code == 200, decided.text
    assert decided.json() == {"turnId": game.turn_id, "decision": "hidden", "hidden": True}
    assert (await http.patch(f"/api/moderation/gallery/{game.turn_id}", json={"decision": "hidden", "note": ""})).status_code == 422
    assert (await http.patch("/api/moderation/gallery/not-an-id", json={"decision": "hidden", "note": "x"})).status_code == 404
    # The reviewer still sees the bytes, hidden or not.
    assert (await http.get(f"/api/moderation/gallery/{game.turn_id}/drawing")).status_code == 200

    await sign_in_as(http, factory, cid.id)
    assert (await http.get("/api/gallery?sort=new")).json()["entries"] == []
    assert (await http.get("/api/gallery/week")).json()["entries"] == []
    assert (await http.get(f"/api/gallery/{game.turn_id}/drawing")).status_code == 404
    assert (await http.put(f"/api/gallery/{game.turn_id}/reaction", json={"emoji": "wow"})).status_code == 404
    assert (await http.get(f"/api/moderation/gallery/{game.turn_id}/drawing")).status_code == 403
    # A participant keeps their history (R-GAL-09).
    await sign_in_as(http, factory, bob.id)
    assert (await http.put(f"/api/games/{game.game_id}/turns/{game.turn_id}/reaction", json={"emoji": "wow"})).status_code == 200

    await _as_moderator(http, factory, mod.id)
    released = await http.patch(f"/api/moderation/gallery/{game.turn_id}", json={"decision": "released", "note": "fine after all"})
    assert released.json()["hidden"] is False
    await sign_in_as(http, factory, cid.id)
    assert [e["turnId"] for e in (await http.get("/api/gallery?sort=new")).json()["entries"]] == [game.turn_id]
    assert [e["turnId"] for e in (await http.get("/api/gallery/week")).json()["entries"]] == [game.turn_id]


async def test_the_switch_holds_the_shelf_and_only_the_shelf(env):
    """With `gallery.shelf_review` set, the shelf shows released drawings only,
    the queue lists the undecided Top-week candidates, and the page goes on
    publishing (R-GAL-10). A hidden drawing stays hidden whatever the switch says."""
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    cid = await _registered(users, "Cid")
    mod = await _moderator(users, factory, "Mod")
    first = await record_game(history, drawer=ann.id, reactor=bob.id, reactions="default", visibility="public", finished_at=NOW - timedelta(hours=2))
    second = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", finished_at=NOW - timedelta(hours=1))

    await _as_moderator(http, factory, mod.id)
    queue = (await http.get("/api/moderation/gallery")).json()
    assert queue == {"review": False, "waiting": 0, "candidates": []}

    async with factory() as session:
        async with session.begin():
            await config_store.put(session, SHELF_REVIEW_KEY, "1")
    queue = (await http.get("/api/moderation/gallery")).json()
    assert queue["review"] is True and queue["waiting"] == 2
    assert [c["turnId"] for c in queue["candidates"]] == [first.turn_id, second.turn_id]
    assert "gameId" not in queue["candidates"][0]

    await sign_in_as(http, factory, cid.id)
    assert (await http.get("/api/gallery/week")).json()["entries"] == [], "nothing released yet"
    assert len((await http.get("/api/gallery?sort=top&window=week")).json()["entries"]) == 2, "the page publishes"

    await _as_moderator(http, factory, mod.id)
    assert (await http.patch(f"/api/moderation/gallery/{second.turn_id}", json={"decision": "released", "note": "ok"})).status_code == 200
    assert (await http.patch(f"/api/moderation/gallery/{first.turn_id}", json={"decision": "hidden", "note": "no"})).status_code == 200
    queue = (await http.get("/api/moderation/gallery")).json()
    assert queue["waiting"] == 0 and queue["candidates"] == []

    await sign_in_as(http, factory, cid.id)
    assert [e["turnId"] for e in (await http.get("/api/gallery/week")).json()["entries"]] == [second.turn_id]
    assert [e["turnId"] for e in (await http.get("/api/gallery?sort=new")).json()["entries"]] == [second.turn_id]

    async with factory() as session:
        async with session.begin():
            await config_store.drop(session, SHELF_REVIEW_KEY)
    await _as_moderator(http, factory, mod.id)
    assert (await http.get("/api/moderation/gallery")).json()["waiting"] == 0
    # The cache is not told about the switch here (the admin route does that):
    # the shelf still says what it said, until its minute is up.
    await sign_in_as(http, factory, cid.id)
    assert [e["turnId"] for e in (await http.get("/api/gallery/week")).json()["entries"]] == [second.turn_id]


async def test_a_report_from_the_gallery_names_the_turn_and_carries_the_drawing(env):
    """The reporter names the turn; the server names the drawer and copies the
    stored drawing in as evidence (R-GAL-08). Self, duplicate, hidden, private
    and unknown are refused the way the rest of reporting refuses."""
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    cid = await _registered(users, "Cid")
    mod = await _moderator(users, factory, "Mod")
    game = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", finished_at=NOW)
    private = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="private", finished_at=NOW)
    path = f"/api/gallery/{game.turn_id}/report"

    assert (await http.post(path, json={"details": "x"})).status_code == 401
    await sign_in_as(http, factory, ann.id)
    assert (await http.post(path, json={"details": "mine"})).status_code == 422, "self"
    # A guest is a signed-in player (R-MOD-01): their report is taken too.
    guest = await users.create_anonymous(display_name="Guest")
    await sign_in_as(http, factory, guest.id)
    assert (await http.post(path, json={"details": "seen it"})).status_code == 201
    await sign_in_as(http, factory, cid.id)
    assert (await http.post(f"/api/gallery/{private.turn_id}/report", json={"details": "x"})).status_code == 404
    assert (await http.post("/api/gallery/not-an-id/report", json={"details": "x"})).status_code == 404
    assert (await http.post(path, json={"details": "x", "reason": "spam"})).status_code == 422

    filed = await http.post(path, json={"details": "  Not something for a lobby.  "})
    assert filed.status_code == 201, filed.text
    assert (await http.post(path, json={"details": "again"})).status_code == 409
    async with factory() as session:
        report = await session.scalar(select(PlayerReport).where(PlayerReport.id == UUID(filed.json()["id"])))
        assert report.reported_user_id == UUID(ann.id)
        assert report.reporter_user_id == UUID(cid.id)
        assert str(report.turn_id) == game.turn_id.replace("-", "") or report.turn_id == UUID(game.turn_id)
        assert report.reason == "offensive_drawing" and report.details == "Not something for a lobby."
        evidence = await session.get(PlayerReportDrawingEvidence, report.id)
        assert evidence is not None and evidence.prompt_snapshot == "lighthouse"

    # Hidden since: no longer reportable from the Gallery.
    await _as_moderator(http, factory, mod.id)
    hidden = await http.patch(f"/api/moderation/gallery/{game.turn_id}", json={"decision": "hidden", "note": "reported"})
    assert hidden.status_code == 200
    await sign_in_as(http, factory, bob.id)
    assert (await http.post(path, json={"details": "x"})).status_code == 404


async def test_a_decision_and_its_audit_record_commit_together(env, monkeypatch):
    """The hide, the review row and the ledger entry are one transaction: if
    the audit cannot be written, nothing was decided."""
    import app.api.moderation as moderation_module

    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    mod = await _moderator(users, factory, "Mod")
    game = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", finished_at=NOW)
    await _as_moderator(http, factory, mod.id)

    class Refuses:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("the ledger is unavailable")

    monkeypatch.setattr(moderation_module, "AuditEvent", Refuses)
    # The test transport re-raises what the route raised; a deployment
    # answers 500. Either way the transaction rolled back.
    with pytest.raises(RuntimeError):
        await http.patch(f"/api/moderation/gallery/{game.turn_id}", json={"decision": "hidden", "note": "x"})
    async with factory() as session:
        drawing = await session.get(TurnDrawing, UUID(game.turn_id))
        assert drawing.gallery_hidden_at is None
        assert await session.get(GalleryShelfReview, UUID(game.turn_id)) is None
    monkeypatch.undo()

    decided = await http.patch(f"/api/moderation/gallery/{game.turn_id}", json={"decision": "hidden", "note": "x"})
    assert decided.status_code == 200
    async with factory() as session:
        assert (await session.get(TurnDrawing, UUID(game.turn_id))).gallery_hidden_at is not None
        events = (await session.scalars(select(AuditEvent).where(AuditEvent.target_id == game.turn_id))).all()
        assert [e.event_type for e in events] == ["gallery.review_hidden"]


async def test_an_invalidation_during_a_refresh_is_not_lost():
    """A read that started before a hide holds the shelf as it was; the
    cache reads again rather than installing it as current."""
    from app.services.gallery_shelf import GalleryShelfCache

    reads = 0
    gate = asyncio.Event()
    entry = lambda turn_id: SimpleNamespace(turn_id=turn_id, reaction_counts={})  # noqa: E731
    results = [(entry("before"),), (entry("after"),)]

    async def read():
        nonlocal reads
        reads += 1
        if reads == 1:
            await gate.wait()
        return results[min(reads, len(results)) - 1]

    cache = GalleryShelfCache(read, ttl_seconds=60)
    first = asyncio.create_task(cache.get())
    await asyncio.sleep(0)
    cache.invalidate()
    gate.set()
    snapshot = await first
    assert [e.turn_id for e in snapshot.entries] == ["after"] and reads == 2
    assert [e.turn_id for e in (await cache.get()).entries] == ["after"] and reads == 2
