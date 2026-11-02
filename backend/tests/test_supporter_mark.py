"""Who other players see a heart beside, and who is told what (#1474)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.friends import create_friends_router
from app.api.profiles import create_profile_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import SupportPurchase, User, UserBan, UserSettings, generate_uuid
from app.rooms import RoomManager
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from app.services.friends import FriendService
from app.services.supporter import active_supporter_ids, supporter_marks

from tests.dbfixtures import create_test_db

NOW = datetime.now(timezone.utc)


@pytest.fixture
async def db(monkeypatch):
    monkeypatch.setenv("SUPPORT_PROVIDER", "stub")
    factory, engine = await create_test_db()
    try:
        yield factory
    finally:
        await engine.dispose()


async def _account(factory, name: str, *, supporter: bool = True, show: bool = True) -> UUID:
    async with factory() as session:
        async with session.begin():
            user = User(
                id=generate_uuid(),
                username=name,
                display_name=name,
                password_hash="not-a-real-hash",
                state="registered",
            )
            session.add(user)
            await session.flush()
            session.add(UserSettings(user_id=user.id, show_supporter_mark=show))
            if supporter:
                session.add(
                    SupportPurchase(
                        user_id=user.id,
                        provider="stub",
                        provider_event_id=f"e-{name}",
                        provider_order_id=f"o-{name}",
                        kind="purchase",
                        period_start=NOW - timedelta(days=1),
                        period_end=NOW + timedelta(days=1),
                        amount_minor=1900,
                        currency="EUR",
                    )
                )
        return user.id


async def _marks(factory, *ids) -> set[str]:
    async with factory() as session:
        return await supporter_marks(session, ids)


async def test_only_a_supporter_who_shows_it_has_a_mark(db):
    shown = await _account(db, "Shown")
    hidden = await _account(db, "Hidden", show=False)
    plain = await _account(db, "Plain", supporter=False)
    assert await _marks(db, shown, hidden, plain) == {str(shown)}


async def test_a_suspended_supporter_shows_no_mark_until_it_lifts(db):
    user_id = await _account(db, "Suspended")
    async with db() as session:
        async with session.begin():
            session.add(UserBan(user_id=user_id, reason="spam", expires_at=None))
    assert await _marks(db, user_id) == set()


async def test_a_moderator_sees_the_pass_a_player_hid(db):
    hidden = await _account(db, "Hidden", show=False)
    plain = await _account(db, "Plain", supporter=False)
    async with db() as session:
        assert await active_supporter_ids(session, {hidden, plain}) == {hidden}


async def test_with_no_provider_nobody_has_a_mark(db, monkeypatch):
    user_id = await _account(db, "Shown")
    monkeypatch.delenv("SUPPORT_PROVIDER")
    assert await _marks(db, user_id) == set()


async def test_a_seat_reads_the_mark_in_the_one_statement_it_already_sends(db):
    shown = await _account(db, "Shown")
    hidden = await _account(db, "Hidden", show=False)
    users = SqlAlchemyUserRepository(db)
    assert (await users.get_seat_account(str(shown)))[0].supporter_mark is True
    assert (await users.get_seat_account(str(hidden)))[0].supporter_mark is False


async def _site(factory, monkeypatch) -> tuple[AsyncClient, FastAPI]:
    monkeypatch.setenv("IP_HASH_SECRET", "supporter-mark-test-secret")
    users = SqlAlchemyUserRepository(factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(users, factory))
    app.include_router(create_profile_router(users, SqlAlchemyGameHistoryRepository(factory)))
    app.include_router(create_friends_router(factory, FriendService(factory)))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), app


async def test_a_profile_carries_the_mark_and_only_as_a_boolean(db, monkeypatch):
    shown = await _account(db, "Shown")
    hidden = await _account(db, "Hidden", show=False)
    http, _ = await _site(db, monkeypatch)
    async with http:
        body = (await http.get(f"/api/users/{shown}/stats")).json()["user"]
        assert body["supporterMark"] is True
        secret = (await http.get(f"/api/users/{hidden}/stats")).json()["user"]
        assert secret["supporterMark"] is False
        plain = await _account(db, "Plain", supporter=False)
        assert secret.keys() == (await http.get(f"/api/users/{plain}/stats")).json()["user"].keys()


def test_the_recap_says_what_the_mark_is_now_not_what_the_game_froze():
    """A game ends, then its supporter hides the mark or is refunded: a late
    joiner's recap must not bring the heart back (R-SUP-10)."""
    manager = RoomManager()
    room = manager.create_room(name="Recap", is_public=False)
    stays = manager.add_player(room, "Ada", user_id="ada", is_anonymous=False, supporter_mark=True)
    gone_id = "seat-that-left"
    room.last_game_scores = [
        {"playerId": stays.id, "score": 10, "supporterMark": True},
        {"playerId": gone_id, "score": 5, "supporterMark": True},
    ]
    marks = [entry["supporterMark"] for entry in room.last_game_payload()["scores"]]
    assert marks == [True, False]
    stays.supporter_mark = False
    marks = [entry["supporterMark"] for entry in room.last_game_payload()["scores"]]
    assert marks == [False, False]
    assert room.last_game_scores[0]["supporterMark"] is True
