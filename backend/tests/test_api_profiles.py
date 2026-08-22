"""The public profile endpoints: stats, history pages, and who may see detail."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.profiles import create_profile_router, profile_limiter
from app.auth.middleware import SessionAuthMiddleware
from app.auth.sessions import COOKIE_NAME, create_session
from app.db.models import Base, generate_uuid
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    TurnGuessInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)

pytestmark = pytest.mark.asyncio

START = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    profile_limiter.reset()

    users = SqlAlchemyUserRepository(session_factory)
    history = SqlAlchemyGameHistoryRepository(session_factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=session_factory)
    app.include_router(create_profile_router(users, history))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, users, history, session_factory
    await engine.dispose()


async def sign_in_as(http, session_factory, user_id: str) -> None:
    issued = await create_session(
        session_factory, user_id=user_id, device_label="Test browser"
    )
    http.cookies.set(COOKIE_NAME, issued.token)


async def record_game(history, users, *, winner, loser, index: int = 0) -> str:
    turn_id = str(generate_uuid())
    return await history.save_game(
        GameRecordInput(
            room_name=f"Studio {index}",
            scoring_mode="default",
            hint_mode="checkpoints",
            drawing_seconds=90,
            total_rounds=1,
            player_count=2,
            started_at=START + timedelta(hours=index),
            finished_at=START + timedelta(hours=index, minutes=10),
        ),
        [
            GameParticipantInput(user_id=winner, final_score=300, final_rank=1),
            GameParticipantInput(user_id=loser, final_score=100, final_rank=2),
        ],
        [
            TurnRecordInput(
                id=turn_id,
                round_number=1,
                turn_number=1,
                drawer_user_id=winner,
                prompt="jackpot",
                duration_seconds=42.5,
            )
        ],
        [
            TurnGuessInput(
                turn_id=turn_id,
                user_id=loser,
                points_awarded=100,
                guess_time_seconds=12.0,
            )
        ],
    )


async def test_stats_carry_the_account_they_describe(env):
    http, users, history, _ = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    await record_game(history, users, winner=ann.id, loser=bob.id)

    response = await http.get(f"/api/users/{ann.id}/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["displayName"] == "Ann"
    assert body["user"]["isAnonymous"] is True
    assert body["stats"]["gamesPlayed"] == 1
    assert body["stats"]["gamesWon"] == 1
    assert body["stats"]["winRate"] == 1.0
    assert body["stats"]["drawingsMade"] == 1
    assert body["stats"]["promptsGuessed"] == 0


async def test_stats_for_an_unknown_player_are_a_404_not_a_row_of_zeroes(env):
    http, *_ = env
    response = await http.get("/api/users/nobody/stats")
    assert response.status_code == 404


async def test_stats_are_readable_without_a_session(env):
    """Viewing another player's profile cannot require being that player."""
    http, users, history, _ = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    await record_game(history, users, winner=ann.id, loser=bob.id)

    assert (await http.get(f"/api/users/{ann.id}/stats")).status_code == 200
    assert (await http.get(f"/api/users/{ann.id}/games")).status_code == 200


async def test_history_pages_report_whether_more_remain(env):
    http, users, history, _ = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    for index in range(3):
        await record_game(history, users, winner=ann.id, loser=bob.id, index=index)

    first = (await http.get(f"/api/users/{ann.id}/games?limit=2")).json()
    assert len(first["games"]) == 2
    assert first["hasMore"] is True

    second = (await http.get(f"/api/users/{ann.id}/games?limit=2&offset=2")).json()
    assert len(second["games"]) == 1
    assert second["hasMore"] is False

    # Newest first, and each row carries the standings.
    assert first["games"][0]["roomName"] == "Studio 2"
    assert [p["finalRank"] for p in first["games"][0]["participants"]] == [1, 2]


async def test_timestamps_are_serialized_with_an_offset(env):
    """SQLite hands back naive datetimes, and an ISO string with no offset is
    read by the browser as local time - shifting every game by the caller's."""
    http, users, history, _ = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    await record_game(history, users, winner=ann.id, loser=bob.id)

    profile = (await http.get(f"/api/users/{ann.id}/stats")).json()
    game = (await http.get(f"/api/users/{ann.id}/games")).json()["games"][0]

    for label, value in (
        ("createdAt", profile["user"]["createdAt"]),
        ("lastLoginAt", profile["user"]["lastLoginAt"]),
        ("startedAt", game["startedAt"]),
        ("finishedAt", game["finishedAt"]),
    ):
        assert datetime.fromisoformat(value).tzinfo is not None, label

    assert datetime.fromisoformat(game["startedAt"]) == START


async def test_history_page_size_is_bounded(env):
    http, users, _, _ = env
    ann = await users.create_anonymous(display_name="Ann")
    assert (await http.get(f"/api/users/{ann.id}/games?limit=500")).status_code == 422
    assert (await http.get(f"/api/users/{ann.id}/games?offset=-1")).status_code == 422


async def test_participants_see_the_turn_by_turn_detail(env):
    http, users, history, session_factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id)
    await sign_in_as(http, session_factory, bob.id)

    body = (await http.get(f"/api/games/{game_id}")).json()

    assert body["roomName"] == "Studio 0"
    assert len(body["turns"]) == 1
    assert body["turns"][0]["prompt"] == "jackpot"
    assert body["turns"][0]["drawerDisplayName"] == "Ann"
    assert body["turns"][0]["guesses"][0]["displayName"] == "Bob"
    assert body["turns"][0]["guesses"][0]["pointsAwarded"] == 100


async def test_a_stranger_cannot_read_the_words_of_a_game_they_did_not_play(env):
    http, users, history, session_factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    outsider = await users.create_anonymous(display_name="Nosy")
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id)

    assert (await http.get(f"/api/games/{game_id}")).status_code == 404

    await sign_in_as(http, session_factory, outsider.id)
    assert (await http.get(f"/api/games/{game_id}")).status_code == 404
