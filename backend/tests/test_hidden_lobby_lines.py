"""A moderator hides a lobby line a report cites, and can show it again
(#1435, R-LCHAT-09)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.moderation import create_moderation_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import AuditEvent, RoomMessage, User, generate_uuid
from app.domain_values import UserRole
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from tests.dbfixtures import create_test_db
from tests.test_moderation_api import register, set_role


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "hidden-lines-test-secret")
    factory, engine = await create_test_db()
    told: list[tuple] = []

    async def on_lobby_line_changed(message_id, author, hidden, text):
        told.append((message_id, author, hidden, text))

    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    app.include_router(
        create_moderation_router(factory, on_lobby_line_changed=on_lobby_line_changed)
    )
    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    new_client.told = told
    try:
        yield new_client, factory
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


def _lobby_line(sender: str, text: str, *, at: datetime, expired: bool = False) -> RoomMessage:
    return RoomMessage(
        id=generate_uuid(),
        sender_user_id=UUID(sender),
        room_instance_id=None,
        sender_player_id=None,
        sender_display_name_snapshot="Someone",
        sender_is_anonymous_snapshot=False,
        is_spectator=False,
        message_kind="chat",
        near_miss_kind=None,
        audience="lobby",
        audience_user_ids=[],
        text=text,
        created_at=at - timedelta(days=40) if expired else at,
        expires_at=at - timedelta(days=10) if expired else at + timedelta(days=30),
    )


async def _reported_lobby_line(new_client, factory):
    """The target's line, reported, with the reporter's own line copied
    around it as context."""
    reporter_http, target_http, moderator_http = new_client(), new_client(), new_client()
    reporter = await register(reporter_http, "HideReporter")
    target = await register(target_http, "HideTarget")
    moderator = await register(moderator_http, "HideMod")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)
    now = datetime.now(timezone.utc)
    theirs = _lobby_line(target["id"], "Something nasty", at=now - timedelta(minutes=2))
    context = _lobby_line(reporter["id"], "Please stop", at=now - timedelta(minutes=1))
    async with factory() as session:
        async with session.begin():
            session.add_all([theirs, context])
    filed = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": target["id"],
            "reason": "harassment",
            "details": "In the lobby.",
            "messageIds": [str(theirs.id)],
        },
    )
    assert filed.status_code == 201, filed.text
    return moderator_http, reporter_http, target, theirs, context


async def test_a_moderator_hides_the_reported_players_line_and_can_show_it_again(env):
    new_client, factory = env
    moderator_http, _, target, theirs, context = await _reported_lobby_line(new_client, factory)
    path = f"/api/moderation/lobby-messages/{theirs.id}"

    assert (await moderator_http.patch(path, json={"hidden": True, "note": " "})).status_code == 422
    hidden = await moderator_http.patch(path, json={"hidden": True, "note": "Abusive"})
    assert hidden.status_code == 200, hidden.text
    assert hidden.json() == {"messageId": str(theirs.id), "hidden": True}
    assert new_client.told == [(str(theirs.id), target["id"], True, None)], "no words go out"

    queue = (await moderator_http.get("/api/moderation/reports")).json()
    [incident] = queue["incidents"]
    assert [(line["text"], line["hidden"]) for line in incident["evidence"]] == [
        ("Something nasty", True),
        ("Please stop", False),
    ]

    # Asked twice, it is one decision: nothing more said, nothing more ledgered.
    assert (await moderator_http.patch(path, json={"hidden": True, "note": "again"})).status_code == 200
    assert len(new_client.told) == 1

    shown = await moderator_http.patch(path, json={"hidden": False, "note": "A mistake"})
    assert shown.status_code == 200
    assert new_client.told[-1] == (str(theirs.id), target["id"], False, "Something nasty")
    async with factory() as session:
        assert (await session.get(RoomMessage, theirs.id)).hidden_at is None
        audit = (
            await session.scalars(
                select(AuditEvent.event_type).where(AuditEvent.target_type == "lobby_message")
                .order_by(AuditEvent.created_at)
            )
        ).all()
    assert audit == ["lobby_message.hidden", "lobby_message.unhidden"]

    # The context line is somebody else's words: this report cannot hide it.
    other = await moderator_http.patch(
        f"/api/moderation/lobby-messages/{context.id}", json={"hidden": True, "note": "x"}
    )
    assert other.status_code == 404


async def test_hiding_is_refused_to_players_without_a_step_up_and_for_ones_own_line(env):
    new_client, factory = env
    moderator_http, reporter_http, _, theirs, _ = await _reported_lobby_line(new_client, factory)
    path = f"/api/moderation/lobby-messages/{theirs.id}"
    body = {"hidden": True, "note": "x"}
    assert (await reporter_http.patch(path, json=body)).status_code == 403, "not staff"

    # A moderator with no step-up (R-AUTH-21).
    fresh_http = new_client()
    fresh = await register(fresh_http, "FreshMod")
    async with factory() as session:
        async with session.begin():
            (await session.get(User, UUID(fresh["id"]))).role = UserRole.MODERATOR.value
    assert (await fresh_http.patch(path, json=body)).status_code == 403

    # An expired line has nothing left to hide.
    now = datetime.now(timezone.utc)
    expired = _lobby_line(fresh["id"], "old", at=now, expired=True)
    async with factory() as session:
        async with session.begin():
            session.add(expired)
    assert (
        await moderator_http.patch(f"/api/moderation/lobby-messages/{expired.id}", json=body)
    ).status_code == 404

    # A moderator's own line, reported: another moderator's to decide.
    target_http = new_client()
    target_mod = await register(target_http, "ReportedMod")
    await set_role(factory, target_mod["id"], UserRole.MODERATOR)
    own = _lobby_line(target_mod["id"], "my own words", at=now - timedelta(minutes=1))
    async with factory() as session:
        async with session.begin():
            session.add(own)
    filed = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": target_mod["id"],
            "reason": "harassment",
            "details": "x",
            "messageIds": [str(own.id)],
        },
    )
    assert filed.status_code == 201, filed.text
    assert (
        await target_http.patch(f"/api/moderation/lobby-messages/{own.id}", json=body)
    ).status_code == 403
    assert new_client.told == []
