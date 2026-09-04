"""Uploaded pictures (#573): limits, serving, moderation, export, deletion."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.avatars import create_avatar_router
from app.api.moderation import create_moderation_router
from app.auth.avatars import AVATAR_REUPLOAD_BLOCK, MAX_AVATAR_BYTES, avatar_key_for
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import AuditEvent, Base, UploadedAvatarAsset, User
from app.domain_values import UserRole
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.avatars import AvatarBlocked, remove_avatar, set_avatar
from tests.png_fixture import png_bytes

PASSWORD = "a-good-password"
pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "avatar-test-secret")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    users = SqlAlchemyUserRepository(factory)
    changed = AsyncMock()
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(users, factory))
    app.include_router(create_avatar_router(users, factory, on_avatar_changed=changed))
    app.include_router(create_moderation_router(factory, on_avatar_changed=changed))
    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    new_client.changed = changed
    try:
        yield new_client, factory
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def register(client: AsyncClient, username: str) -> dict:
    assert (await client.get("/api/auth/me")).status_code == 200
    response = await client.post(
        "/api/auth/register", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()


def encoded(payload: bytes) -> dict:
    return {"image": base64.b64encode(payload).decode("ascii")}


async def test_a_registered_player_uploads_a_picture_and_everyone_can_fetch_it(env):
    new_client, factory = env
    http = new_client()
    account = await register(http, "Painter")
    picture = png_bytes(seed=1)

    uploaded = await http.post("/api/users/me/avatar", json=encoded(picture))
    assert uploaded.status_code == 200
    key = uploaded.json()["avatarKey"]
    assert key == avatar_key_for(picture)
    assert uploaded.json()["avatarUrl"] == f"/api/avatars/{key}"
    # The account now carries it, and so does everything built from the account.
    assert (await http.get("/api/auth/me")).json()["avatarUrl"] == f"/api/avatars/{key}"
    new_client.changed.assert_awaited_with(account["id"], key)

    # Anybody can fetch it - a picture is shown to every player - and it is
    # served as an image and nothing else, cacheable for ever.
    fetched = await new_client().get(f"/api/avatars/{key}")
    assert fetched.status_code == 200
    assert fetched.content == picture
    assert fetched.headers["content-type"] == "image/png"
    assert fetched.headers["x-content-type-options"] == "nosniff"
    assert "immutable" in fetched.headers["cache-control"]

    async with factory() as session:
        kinds = set((await session.scalars(select(AuditEvent.event_type))).all())
    assert "avatar.uploaded" in kinds


async def test_a_new_picture_replaces_the_old_one_and_its_url(env):
    new_client, factory = env
    http = new_client()
    await register(http, "Restless")
    first = (await http.post("/api/users/me/avatar", json=encoded(png_bytes(seed=1)))).json()
    second = (await http.post("/api/users/me/avatar", json=encoded(png_bytes(seed=2)))).json()
    assert first["avatarKey"] != second["avatarKey"]
    assert (await http.get(first["avatarUrl"])).status_code == 404
    assert (await http.get(second["avatarUrl"])).status_code == 200
    async with factory() as session:
        rows = (await session.scalars(select(UploadedAvatarAsset))).all()
    assert len(rows) == 1


async def test_removing_the_picture_returns_the_account_to_its_initial(env):
    new_client, _ = env
    http = new_client()
    account = await register(http, "Plain")
    key = (await http.post("/api/users/me/avatar", json=encoded(png_bytes()))).json()["avatarKey"]
    assert (await http.delete("/api/users/me/avatar")).status_code == 200
    assert (await http.get("/api/auth/me")).json()["avatarUrl"] is None
    assert (await http.get(f"/api/avatars/{key}")).status_code == 404
    new_client.changed.assert_awaited_with(account["id"], None)


async def test_a_guest_has_no_picture_to_set(env):
    """R-ACCT-05: a name in the player list is a claimed account or an unclaimed guest."""
    new_client, _ = env
    http = new_client()
    await http.post("/api/auth/display-name", json={"displayName": "Passerby"})
    refused = await http.post("/api/users/me/avatar", json=encoded(png_bytes()))
    assert refused.status_code == 403
    assert (await http.delete("/api/users/me/avatar")).status_code == 403


@pytest.mark.parametrize(
    "payload, message",
    [
        (b"not a picture at all", "not a PNG"),
        (png_bytes(200, 256), "256 by 256"),
        (png_bytes(256, 300), "256 by 256"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, "not a PNG"),
    ],
)
async def test_only_a_square_png_of_the_right_size_is_taken(env, payload, message):
    new_client, _ = env
    http = new_client()
    await register(http, "Fussy")
    refused = await http.post("/api/users/me/avatar", json=encoded(payload))
    assert refused.status_code == 400
    assert message in refused.json()["detail"]


async def test_an_oversized_picture_is_refused_by_the_body_cap_and_the_rule(env):
    new_client, factory = env
    http = new_client()
    account = await register(http, "Heavy")
    # Past the byte cap but a valid header: the rule refuses it on size alone.
    heavy = png_bytes() + b"\x00" * MAX_AVATAR_BYTES
    with pytest.raises(ValueError, match="too large"):
        await set_avatar(factory, user_id=account["id"], payload=heavy)


async def test_a_moderator_removes_a_reported_picture_and_blocks_reuploads(env):
    new_client, factory = env
    target_http, reporter_http, moderator_http = new_client(), new_client(), new_client()
    target = await register(target_http, "Offender")
    reporter = await register(reporter_http, "Witness")
    moderator = await register(moderator_http, "Mod")
    async with factory() as session:
        async with session.begin():
            row = await session.get(User, UUID(moderator["id"]))
            row.role = UserRole.MODERATOR.value
    key = (
        await target_http.post("/api/users/me/avatar", json=encoded(png_bytes(seed=3)))
    ).json()["avatarKey"]

    report = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": target["id"],
            "reason": "inappropriate_avatar",
            "details": "The picture is not something anybody should see.",
        },
    )
    assert report.status_code == 201
    report_id = report.json()["id"]

    # The queue shows the picture, so the case can be judged from it.
    listed = await moderator_http.get("/api/moderation/reports")
    assert listed.status_code == 200
    case = next(item for item in listed.json()["reports"] if item["id"] == report_id)
    assert case["reportedPlayer"]["avatarUrl"] == f"/api/avatars/{key}"

    # Only a moderator can act on it, and it acts through the report.
    assert (
        await reporter_http.post(f"/api/moderation/reports/{report_id}/remove-avatar")
    ).status_code == 403
    removed = await moderator_http.post(f"/api/moderation/reports/{report_id}/remove-avatar")
    assert removed.status_code == 200
    assert removed.json() == {"ok": True, "removed": True}
    assert (await target_http.get("/api/auth/me")).json()["avatarUrl"] is None
    assert (await target_http.get(f"/api/avatars/{key}")).status_code == 404
    new_client.changed.assert_awaited_with(target["id"], None)

    # Putting it straight back is refused for a week, with the date.
    again = await target_http.post("/api/users/me/avatar", json=encoded(png_bytes(seed=3)))
    assert again.status_code == 403
    assert "moderator removed" in again.json()["detail"]
    assert reporter["id"] != target["id"]

    async with factory() as session:
        row = await session.get(User, UUID(target["id"]))
        blocked_until = row.avatar_upload_blocked_until
        if blocked_until.tzinfo is None:
            blocked_until = blocked_until.replace(tzinfo=timezone.utc)
        assert blocked_until - datetime.now(timezone.utc) > AVATAR_REUPLOAD_BLOCK - timedelta(minutes=1)
        events = (await session.scalars(select(AuditEvent).where(AuditEvent.event_type == "avatar.removed"))).all()
    assert any(event.details.get("by_moderator") and event.details.get("report_id") == report_id for event in events)

    # A week later the block has lifted.
    later = datetime.now(timezone.utc) + AVATAR_REUPLOAD_BLOCK + timedelta(seconds=1)
    assert await set_avatar(factory, user_id=target["id"], payload=png_bytes(seed=4), now=later)


async def test_the_block_is_the_moderators_alone(env):
    """Taking your own picture down is not a punishment."""
    new_client, factory = env
    http = new_client()
    account = await register(http, "Tidy")
    await set_avatar(factory, user_id=account["id"], payload=png_bytes())
    await remove_avatar(factory, user_id=account["id"], actor_id=account["id"])
    assert await set_avatar(factory, user_id=account["id"], payload=png_bytes(seed=9))


async def test_a_blocked_upload_says_when(env):
    new_client, factory = env
    http = new_client()
    account = await register(http, "Waiting")
    await remove_avatar(factory, user_id=account["id"], actor_id=None, by_moderator=True)
    with pytest.raises(AvatarBlocked) as refused:
        await set_avatar(factory, user_id=account["id"], payload=png_bytes())
    assert refused.value.until > datetime.now(timezone.utc)


async def test_a_report_about_nobody_cannot_take_a_picture_down(env):
    new_client, factory = env
    moderator_http = new_client()
    moderator = await register(moderator_http, "Mod")
    async with factory() as session:
        async with session.begin():
            row = await session.get(User, UUID(moderator["id"]))
            row.role = UserRole.MODERATOR.value
    missing = await moderator_http.post(
        "/api/moderation/reports/019c1000-0000-7000-8000-00000000dead/remove-avatar"
    )
    assert missing.status_code == 404


async def test_a_key_that_is_not_a_content_address_is_not_looked_up(env):
    new_client, _ = env
    http = new_client()
    assert (await http.get("/api/avatars/../etc/passwd")).status_code in (404, 422)
    assert (await http.get("/api/avatars/initial")).status_code == 404
    assert (await http.get("/api/avatars/" + "0" * 64 + ".png")).status_code == 404
