"""Who you have been playing with, offered as people you could befriend.

The endpoint exists because the lobby can only offer a friendship to whoever
is standing there right now, and the person somebody actually wants is usually
the one they finished a game with yesterday (R-FRIEND-10). What it must never
become is a directory: every assertion below is about what it does *not*
return.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.friends import RECENT_PLAYERS_WINDOW, create_recent_players_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import generate_uuid
from app.repositories.interfaces import GameParticipantInput, GameRecordInput
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)

from tests.dbfixtures import create_test_db

PASSWORD = "a-good-password"
NOW = datetime.now(timezone.utc)


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "recent-players-secret")
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(users, factory))
    app.include_router(create_recent_players_router(factory, history))
    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    try:
        yield new_client, history
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def register(client: AsyncClient, username: str) -> dict:
    assert (await client.get("/api/auth/me")).status_code == 200
    assert (
        await client.post("/api/auth/display-name", json={"displayName": username})
    ).status_code == 200
    response = await client.post(
        "/api/auth/register", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()


async def name_a_guest(client: AsyncClient, name: str) -> dict:
    assert (await client.get("/api/auth/me")).status_code == 200
    response = await client.post(
        "/api/auth/display-name", json={"displayName": name}
    )
    assert response.status_code == 200
    return response.json()


async def play_together(
    history,
    seats: list[tuple[str | None, str, bool]],
    *,
    finished_at: datetime,
    outcome_finished: bool = True,
) -> str:
    """One recorded game. `seats` is (user_id, display name, is_anonymous)."""
    return await history.save_game(
        GameRecordInput(
            room_name="Studio",
            scoring_mode="default",
            scoring_version=1,
            score_ledger_version=1,
            rule_snapshot_version=1,
            hint_mode="checkpoints",
            drawing_seconds=90,
            total_rounds=1,
            player_count=len(seats),
            started_at=finished_at - timedelta(minutes=10),
            finished_at=finished_at,
            outcome="finished" if outcome_finished else "abandoned",
        ),
        [
            GameParticipantInput(
                user_id=user_id,
                # Zero, and no score events: the ledger has to reconcile
                # to the final scores, and this suite is about who played
                # rather than how it went.
                final_score=0,
                final_rank=index + 1 if outcome_finished else None,
                seat_id=str(generate_uuid()),
                display_name=name,
                is_anonymous=anonymous,
            )
            for index, (user_id, name, anonymous) in enumerate(seats)
        ],
        [],
        [],
    )


async def recent(client: AsyncClient) -> list[dict]:
    response = await client.get("/api/users/me/recent-players")
    assert response.status_code == 200
    return response.json()["players"]


async def test_somebody_you_played_with_is_offered_even_though_they_are_gone(env):
    """The gap this closes: the lobby only ever knew who was online."""
    new_client, history = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")
    await play_together(
        history,
        [(ada["id"], "Ada", False), (bob["id"], "Bob", False)],
        finished_at=NOW - timedelta(hours=2),
    )

    found = await recent(ada_http)
    assert [person["userId"] for person in found] == [bob["id"]]
    assert found[0]["displayName"] == "Bob"
    # Mutual, because the game is one fact about both of them.
    assert [person["userId"] for person in await recent(bob_http)] == [ada["id"]]


async def test_you_are_not_among_the_people_you_played_with(env):
    new_client, history = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")
    await play_together(
        history,
        [(ada["id"], "Ada", False), (bob["id"], "Bob", False)],
        finished_at=NOW - timedelta(hours=1),
    )
    assert ada["id"] not in [person["userId"] for person in await recent(ada_http)]


async def test_a_guest_seat_is_not_somebody_to_befriend(env):
    """A friendship with one would outlive the account (R-FRIEND-03)."""
    new_client, history = env
    ada_http, guest_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    guest = await name_a_guest(guest_http, "Wanderer")
    await play_together(
        history,
        [(ada["id"], "Ada", False), (guest["id"], "Wanderer", True)],
        finished_at=NOW - timedelta(hours=1),
    )
    assert await recent(ada_http) == []


async def test_a_game_older_than_the_window_has_stopped_counting(env):
    """"Recently" is a window, so a returning player gets nothing rather than
    a year-old list of people who have forgotten them."""
    new_client, history = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")
    await play_together(
        history,
        [(ada["id"], "Ada", False), (bob["id"], "Bob", False)],
        finished_at=NOW - RECENT_PLAYERS_WINDOW - timedelta(days=1),
    )
    assert await recent(ada_http) == []


async def test_an_abandoned_game_is_not_a_claim_that_anybody_played(env):
    new_client, history = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")
    await play_together(
        history,
        [(ada["id"], "Ada", False), (bob["id"], "Bob", False)],
        finished_at=NOW - timedelta(hours=1),
        outcome_finished=False,
    )
    assert await recent(ada_http) == []


async def test_the_newest_game_decides_the_order_and_each_person_appears_once(env):
    new_client, history = env
    ada_http = new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(new_client(), "Bob")
    cleo = await register(new_client(), "Cleo")
    # Ada plays Bob twice and Cleo once; Bob's second game is the most recent
    # of all, so Bob leads and appears exactly once.
    await play_together(
        history,
        [(ada["id"], "Ada", False), (bob["id"], "Bob", False)],
        finished_at=NOW - timedelta(days=3),
    )
    await play_together(
        history,
        [(ada["id"], "Ada", False), (cleo["id"], "Cleo", False)],
        finished_at=NOW - timedelta(days=2),
    )
    await play_together(
        history,
        [(ada["id"], "Ada", False), (bob["id"], "Bob", False)],
        finished_at=NOW - timedelta(hours=1),
    )
    assert [person["userId"] for person in await recent(ada_http)] == [
        bob["id"],
        cleo["id"],
    ]


async def test_a_guest_is_told_why_rather_than_shown_an_empty_list(env):
    """The same refusal the friends endpoints give, from the same gate."""
    new_client, _ = env
    guest_http = new_client()
    await name_a_guest(guest_http, "Wanderer")
    response = await guest_http.get("/api/users/me/recent-players")
    assert response.status_code == 403
    assert "account" in response.json()["detail"].lower()


async def test_it_says_nothing_about_friendships_or_refusals(env):
    """An absence is readable, and a decline must not be (R-FRIEND-04).

    Bob declines Ada. Bob still appears on Ada's list, and pressing Add on him
    will quietly do nothing - which is what a decline is meant to feel like.
    Filtering him out would answer the question the endpoint refuses to.
    """
    new_client, history = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")
    await play_together(
        history,
        [(ada["id"], "Ada", False), (bob["id"], "Bob", False)],
        finished_at=NOW - timedelta(hours=1),
    )
    from app.services.friends import FriendService

    friends = FriendService(history._session_factory)
    from uuid import UUID

    await friends.request(UUID(ada["id"]), UUID(bob["id"]))
    await friends.remove(UUID(bob["id"]), UUID(ada["id"]))

    assert [person["userId"] for person in await recent(ada_http)] == [bob["id"]]
