"""Reacting, sharing and reporting from Solo, and the drawer's ways out (#1434, #1469).

A Solo player may do with a drawing they were served what a Gallery visitor
may - react, report - and what a player who sat in the game may - share it,
under its drawer's name - once they have settled it. None of it names the
drawer to them. The drawer keeps the last word: an opt-out for every drawing,
a take-out for one, and the Gallery withdrawal as before.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.errors import install_refusal_handler
from app.api.gallery import create_gallery_router, gallery_limiter
from app.api.inbox import create_inbox_router
from app.api.moderation import create_moderation_router
from app.api.profiles import create_profile_router, profile_limiter
from app.api.solo import create_solo_router, drawing_limiter, run_limiter, serve_limiter
from app.api.user_settings import create_user_settings_router
from app.auth.middleware import SessionAuthMiddleware
from app.db.models import PlayerReport, SoloGalleryShare
from app.repositories.solo import SoloRepository
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
    release_held_solo_shares,
)
from app.solo_rules import daily_release_at
from tests.dbfixtures import create_test_db
from tests.solo_fixtures import player, record_turn, seed_concept
from tests.test_api_profiles import sign_in_as


@pytest_asyncio.fixture
async def env():
    factory, engine = await create_test_db()
    for limiter in (run_limiter, serve_limiter, drawing_limiter, gallery_limiter, profile_limiter):
        limiter.reset()
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_solo_router(factory, game_history_repo=history))
    app.include_router(create_gallery_router(history))
    app.include_router(create_profile_router(users, history))
    app.include_router(create_user_settings_router(factory))
    app.include_router(create_inbox_router(factory))
    app.include_router(create_moderation_router(factory, game_history_repo=history))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http, users, history, SoloRepository(factory), factory
    await engine.dispose()


async def _served(http, users, history, factory, *, settle=True):
    """A drawer's public drawing, served to a stranger and settled."""
    drawer = await player(users, factory, "Drawer")
    guesser = await player(users, factory, "Guesser")
    concept = await seed_concept(factory, {"en": "lighthouse"})
    turn = await record_turn(
        history, drawer=drawer.id, guessers=[guesser.id], version_id=concept.versions["en"]
    )
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    run = (await http.post("/api/solo/runs", json={"length": 5})).json()
    [serve] = (await http.post(f"/api/solo/runs/{run['runId']}/serves")).json()["serves"]
    if settle:
        await http.post(
            f"/api/solo/serves/{serve['serveId']}/result", json={"outcome": "solved", "seconds": 4}
        )
    return drawer, stranger, turn, serve


async def test_a_reaction_from_solo_counts_like_a_gallery_one_and_names_nobody(env):
    http, users, history, solo, factory = env
    drawer, stranger, turn, serve = await _served(http, users, history, factory)
    answer = await http.put(f"/api/solo/serves/{serve['serveId']}/reaction", json={"emoji": "wow"})
    assert answer.status_code == 200
    assert answer.json() == {"myReaction": "wow", "reactionCounts": {"wow": 1}}
    assert (await users.get_stats(drawer.id)).reactions_received == 1
    cleared = await http.delete(f"/api/solo/serves/{serve['serveId']}/reaction")
    assert cleared.json() == {"myReaction": None, "reactionCounts": {}}
    assert (await users.get_stats(drawer.id)).reactions_received == 0


async def test_nothing_is_written_from_solo_before_the_drawing_is_settled_or_by_anybody_else(env):
    http, users, history, solo, factory = env
    drawer, stranger, turn, serve = await _served(http, users, history, factory, settle=False)
    base = f"/api/solo/serves/{serve['serveId']}"
    assert (await http.put(f"{base}/reaction", json={"emoji": "wow"})).status_code == 404
    assert (await http.put(f"{base}/share")).status_code == 404
    assert (await http.post(f"{base}/report", json={})).status_code == 404
    # The turn id is no way in on this door either.
    assert (await http.put(f"/api/solo/serves/{turn.turn_id}/share")).status_code == 404
    await http.post(f"{base}/result", json={"outcome": "given_up", "seconds": 9})
    other = await player(users, factory, "Other")
    await sign_in_as(http, factory, other.id)
    assert (await http.put(f"{base}/reaction", json={"emoji": "wow"})).status_code == 404
    assert (await http.put(f"{base}/share")).status_code == 404


async def test_a_share_from_solo_enters_the_gallery_under_the_drawer_credited_to_the_sharer(env):
    http, users, history, solo, factory = env
    drawer, stranger, turn, serve = await _served(http, users, history, factory)
    shared = await http.put(f"/api/solo/serves/{serve['serveId']}/share")
    assert shared.status_code == 200
    assert shared.json() == {
        "inGallery": True, "sharedByMe": True, "heldUntil": None, "shareWithdrawn": False,
    }
    [entry] = (await http.get("/api/gallery")).json()["entries"]
    assert entry["turnId"] == turn.turn_id and entry["drawerDisplayName"] == "Drawer"
    assert entry["sharedBy"]["displayName"] == stranger.display_name and entry["sharedByMe"] is True
    # The drawer is told, by the sharer's name (R-SHARE-09).
    await sign_in_as(http, factory, drawer.id)
    [told] = (await http.get("/api/inbox")).json()["entries"]
    assert told["kind"] == "drawing_shared"
    assert told["drawing"]["sharedBy"]["displayName"] == stranger.display_name
    # The drawer's withdrawal takes it out, Solo's share with the rest.
    withdrawn = await http.delete(f"/api/games/{turn.game_id}/turns/{turn.turn_id}/share")
    assert withdrawn.status_code == 200
    assert (await http.get("/api/gallery")).json()["entries"] == []
    await sign_in_as(http, factory, stranger.id)
    again = await http.put(f"/api/solo/serves/{serve['serveId']}/share")
    assert again.status_code == 404


async def test_a_solo_sharer_takes_their_share_back_from_solo_or_the_gallery(env):
    http, users, history, solo, factory = env
    _, stranger, turn, serve = await _served(http, users, history, factory)
    await http.put(f"/api/solo/serves/{serve['serveId']}/share")
    taken = await http.delete(f"/api/solo/serves/{serve['serveId']}/share")
    assert taken.json()["inGallery"] is False and taken.json()["sharedByMe"] is False
    await http.put(f"/api/solo/serves/{serve['serveId']}/share")
    from_gallery = await http.delete(f"/api/gallery/{turn.turn_id}/share")
    assert from_gallery.status_code == 200 and from_gallery.json()["inGallery"] is False


async def test_a_daily_drawing_s_share_waits_until_the_day_has_ended_everywhere(env):
    http, users, history, solo, factory = env
    drawer = await player(users, factory, "Drawer")
    seats = [await player(users, factory, f"Guesser{i}") for i in range(2)]
    for index in range(5):
        concept = await seed_concept(factory, {"zxx": f"Name{index}"})
        await record_turn(
            history, drawer=drawer.id, guessers=[seat.id for seat in seats],
            version_id=concept.versions["zxx"],
        )
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    today = datetime.now(timezone.utc).date()
    run = (await http.post(f"/api/solo/daily/{today.isoformat()}")).json()
    first = run["serves"][0]
    await http.post(f"/api/solo/serves/{first['serveId']}/result", json={"outcome": "solved", "seconds": 2})
    held = (await http.put(f"/api/solo/serves/{first['serveId']}/share")).json()
    assert held["inGallery"] is False and held["sharedByMe"] is True
    assert datetime.fromisoformat(held["heldUntil"]) >= daily_release_at(today)
    assert (await http.get("/api/gallery")).json()["entries"] == []

    early = await release_held_solo_shares(factory, now=datetime.now(timezone.utc))
    assert int(early) == 0
    later = datetime.fromisoformat(held["heldUntil"]) + timedelta(minutes=1)
    released = await release_held_solo_shares(factory, now=later)
    assert int(released) == 1 and released.oldest_overdue_seconds == 0.0
    [entry] = (await http.get("/api/gallery")).json()["entries"]
    assert entry["sharedBy"]["displayName"] == stranger.display_name
    async with factory() as session:
        [share] = (await session.scalars(select(SoloGalleryShare))).all()
    assert share.release_at is None


async def test_the_drawer_s_opt_out_and_take_out_close_solo_from_the_next_request(env):
    http, users, history, solo, factory = env
    drawer = await player(users, factory, "Drawer")
    guesser = await player(users, factory, "Guesser")
    concept = await seed_concept(factory, {"en": "lighthouse"})
    turns = [
        await record_turn(history, drawer=drawer.id, guessers=[guesser.id], version_id=concept.versions["en"])
        for _ in range(2)
    ]
    stranger = await player(users, factory, "Stranger")
    assert len(await solo.servable_turn_ids(stranger.id)) == 2

    # Only the drawer may take one out; anybody else gets the door's 404.
    await sign_in_as(http, factory, guesser.id)
    path = f"/api/games/{turns[0].game_id}/turns/{turns[0].turn_id}/solo"
    assert (await http.delete(path)).status_code == 404
    await sign_in_as(http, factory, drawer.id)
    out = await http.delete(path)
    assert out.status_code == 200 and out.json()["soloWithdrawn"] is True
    assert [str(turn) for turn in await solo.servable_turn_ids(stranger.id)] == [turns[1].turn_id]
    back = await http.put(path)
    assert back.json()["soloWithdrawn"] is False
    assert len(await solo.servable_turn_ids(stranger.id)) == 2

    opted = await http.patch("/api/users/me/settings", json={"soloOptOut": True})
    assert opted.status_code == 200 and opted.json()["soloOptOut"] is True
    assert await solo.servable_turn_ids(stranger.id) == []


async def test_a_report_from_solo_is_accepted_and_a_second_says_nothing_of_the_drawer(env):
    http, users, history, solo, factory = env
    drawer, stranger, turn, serve = await _served(http, users, history, factory)
    report = await http.post(f"/api/solo/serves/{serve['serveId']}/report", json={"details": "rude"})
    assert report.status_code == 201 and report.json()["id"]
    # Another drawing by the same drawer: a 409 here would tell the reporter
    # the two anonymous drawings share a drawer.
    guesser = await player(users, factory, "Guesser2")
    concept = await seed_concept(factory, {"en": "harbour"})
    await record_turn(history, drawer=drawer.id, guessers=[guesser.id], version_id=concept.versions["en"])
    run = (await http.post("/api/solo/runs", json={"length": 5})).json()
    [second] = (await http.post(f"/api/solo/runs/{run['runId']}/serves")).json()["serves"]
    await http.post(f"/api/solo/serves/{second['serveId']}/result", json={"outcome": "solved", "seconds": 3})
    again = await http.post(f"/api/solo/serves/{second['serveId']}/report", json={})
    assert again.status_code == 201
    assert set(again.json()) == {"id", "status", "createdAt"}
    async with factory() as session:
        reports = (await session.scalars(select(PlayerReport))).all()
        assert len(reports) == 1 and reports[0].turn_id == UUID(turn.turn_id)
        assert await session.scalar(select(func.count()).select_from(PlayerReport)) == 1


async def test_the_reaction_write_s_solo_door_asks_for_a_settled_serve_itself(env):
    # The route resolves the serve first; the write must not trust that it did.
    http, users, history, solo, factory = env
    drawer, stranger, turn, serve = await _served(http, users, history, factory, settle=False)
    other = await player(users, factory, "Other")
    for who in (stranger, other):
        refused = await history.set_drawing_reaction(
            None, turn.turn_id, requesting_user_id=who.id, emoji="wow", from_solo=True
        )
        assert refused is None
    await http.post(
        f"/api/solo/serves/{serve['serveId']}/result", json={"outcome": "solved", "seconds": 1}
    )
    allowed = await history.set_drawing_reaction(
        None, turn.turn_id, requesting_user_id=stranger.id, emoji="wow", from_solo=True
    )
    assert allowed is not None and allowed.reaction_counts == {"wow": 1}
