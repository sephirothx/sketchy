"""The share routes and the drawer's inbox entry (#1430, #1436): one 404 for every refusal,
the push after a committed share, and the drawer's catch-up read."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.errors import install_refusal_handler
from app.api.gallery import create_gallery_router, gallery_limiter
from app.api.profiles import create_profile_router
from app.api.inbox import create_inbox_router
from app.auth.middleware import SessionAuthMiddleware
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from tests.dbfixtures import create_test_db
from tests.test_api_profiles import _registered, sign_in_as
from tests.test_drawing_reactions import record_game


NOW = datetime.now(timezone.utc)


@pytest_asyncio.fixture
async def env():
    session_factory, engine = await create_test_db()
    gallery_limiter.reset()
    users = SqlAlchemyUserRepository(session_factory)
    history = SqlAlchemyGameHistoryRepository(session_factory)
    pushed: list[str] = []
    changed: list[bool] = []
    refreshed: list[tuple[str, ...]] = []

    async def on_inbox_changed(user_id: str) -> None:
        pushed.append(user_id)

    async def on_shares_changed(turn_ids: tuple[str, ...]) -> None:
        refreshed.append(turn_ids)

    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=session_factory)
    app.include_router(
        create_profile_router(
            users,
            history,
            on_inbox_changed=on_inbox_changed,
            on_gallery_changed=lambda: changed.append(True),
            on_shares_changed=on_shares_changed,
        )
    )
    app.include_router(
        create_gallery_router(
            history, on_inbox_changed=on_inbox_changed, on_shares_changed=on_shares_changed
        )
    )
    app.include_router(create_inbox_router(session_factory))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        http.refreshed = refreshed
        yield http, users, history, session_factory, pushed, changed
    await engine.dispose()


async def test_a_participant_shares_from_history_and_the_drawer_is_told(env):
    http, users, history, factory, pushed, changed = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
    )
    await sign_in_as(http, factory, bob.id)
    shared = await http.put(f"/api/games/{game.game_id}/turns/{game.turn_id}/share")
    assert shared.status_code == 200
    assert shared.json() == {
        "turnId": game.turn_id,
        "shares": [game.reactor_seat],
        "shareWithdrawn": False,
    }
    assert pushed == [ann.id] and changed == [True]

    await sign_in_as(http, factory, ann.id)
    inbox = (await http.get("/api/inbox")).json()
    assert inbox["unreadCount"] == 1
    [entry] = inbox["entries"]
    assert entry["kind"] == "drawing_shared" and not entry["read"]
    assert entry["drawing"] == {
        "turnId": game.turn_id,
        "prompt": "lighthouse",
        "inGallery": True,
        "sharedBy": {"displayName": "Reactor", "nameColor": None, "isAnonymous": False},
    }
    assert "gameId" not in str(entry)

    assert (await http.post("/api/inbox/read", json={"ids": [entry["id"]]})).json() == {
        "unreadCount": 0
    }


async def test_every_share_refusal_is_the_same_404(env):
    http, users, history, factory, pushed, _ = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    cid = await _registered(users, "Cid")
    private = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="private")
    blank = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
        stroke_count=0,
    )
    public = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
    )

    async def status(method: str, path: str) -> int:
        return (await http.request(method, path)).status_code

    assert await status("PUT", f"/api/games/{public.game_id}/turns/{public.turn_id}/share") == 404
    await sign_in_as(http, factory, bob.id)
    assert await status("PUT", f"/api/games/{private.game_id}/turns/{private.turn_id}/share") == 404
    assert await status("PUT", f"/api/games/{blank.game_id}/turns/{blank.turn_id}/share") == 404
    assert await status("PUT", f"/api/games/{public.game_id}/turns/not-a-turn/share") == 404
    assert await status("PUT", f"/api/games/{private.game_id}/turns/{public.turn_id}/share") == 404
    await sign_in_as(http, factory, cid.id)
    assert await status("PUT", f"/api/games/{public.game_id}/turns/{public.turn_id}/share") == 404
    assert await status("DELETE", f"/api/gallery/{public.turn_id}/share") == 404
    assert pushed == []


async def test_the_drawer_takes_a_drawing_out_from_the_gallery(env):
    http, users, history, factory, pushed, _ = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by="reactor",
        finished_at=NOW - timedelta(hours=1),
    )
    await sign_in_as(http, factory, ann.id)
    [entry] = (await http.get("/api/gallery")).json()["entries"]
    assert entry["drawnByMe"] and not entry["sharedByMe"]
    assert entry["sharedBy"] == {"displayName": "Reactor", "nameColor": None, "isAnonymous": False}
    assert entry["sharedAt"] is not None

    taken = await http.delete(f"/api/gallery/{game.turn_id}/share")
    assert taken.json() == {"turnId": game.turn_id, "inGallery": False}
    assert (await http.get("/api/gallery")).json()["entries"] == []
    assert (await http.get(f"/api/gallery/{game.turn_id}")).status_code == 404

    await sign_in_as(http, factory, bob.id)
    assert (
        await http.put(f"/api/games/{game.game_id}/turns/{game.turn_id}/share")
    ).status_code == 404, "withdrawn holds against everyone else"
    detail = (await http.get(f"/api/games/{game.game_id}")).json()
    assert detail["turns"][0]["shares"] == [] and detail["turns"][0]["shareWithdrawn"]


async def test_one_entry_per_drawing_however_many_share_it(env):
    """The second and the tenth share say nothing the first did not; taking a
    share back leaves the entry, which names nobody once no share is left."""
    http, users, history, factory, pushed, _ = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
    )
    for _ in range(2):
        await history.set_drawing_share(
            game.game_id, game.turn_id, requesting_user_id=bob.id, shared=True
        )
        await history.set_drawing_share(
            game.game_id, game.turn_id, requesting_user_id=bob.id, shared=False
        )
    await sign_in_as(http, factory, ann.id)
    [entry] = (await http.get("/api/inbox")).json()["entries"]
    assert entry["drawing"]["sharedBy"] is None and not entry["drawing"]["inGallery"]


async def test_pinning_somebody_elses_drawing_pushes_their_notice(env):
    http, users, history, factory, pushed, changed = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
    )
    await sign_in_as(http, factory, bob.id)
    assert (await http.put("/api/me/pins", json={"turnIds": [game.turn_id]})).status_code == 200
    assert pushed == [ann.id] and changed


async def test_the_inbox_routes_need_a_session(env):
    http, *_ = env
    assert (await http.get("/api/inbox")).status_code == 401
    assert (await http.post("/api/inbox/read", json={"all": True})).status_code == 401


async def test_every_share_write_reaches_an_open_recap_of_the_drawing(env):
    """History, a pin and the Gallery's door each write without the room;
    each names the drawings it touched so a recap showing one is brought up
    to date (R-SHARE-07)."""
    http, users, history, factory, _, _ = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
    )
    await sign_in_as(http, factory, bob.id)
    await http.put(f"/api/games/{game.game_id}/turns/{game.turn_id}/share")
    await http.put("/api/me/pins", json={"turnIds": [game.turn_id]})
    await sign_in_as(http, factory, ann.id)
    await http.delete(f"/api/gallery/{game.turn_id}/share")
    assert http.refreshed == [(game.turn_id,)] * 3

    cid = await _registered(users, "Cid")
    await sign_in_as(http, factory, cid.id)
    refused = await http.put(f"/api/games/{game.game_id}/turns/{game.turn_id}/share")
    assert refused.status_code == 404
    assert len(http.refreshed) == 3, "a refused write changed nothing to refresh"
