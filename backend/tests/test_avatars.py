"""Uploaded pictures (#573): limits, serving, moderation, export, deletion."""
from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pathlib import Path

from app.api.avatars import create_avatar_router
from app.auth.avatar_doodles import DOODLES
from app.api.moderation import create_moderation_router
from app.auth.avatars import AVATAR_REUPLOAD_BLOCK, MAX_AVATAR_BYTES, avatar_key_for
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import AuditEvent, Base, UploadedAvatarAsset, User
from app.domain_values import UserRole
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.avatars import AvatarBlocked, remove_avatar, set_avatar
from tests.png_fixture import png_bytes
from tests.webp_fixture import webp_bytes

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
    assert key == avatar_key_for(picture, "image/png")
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


async def test_two_accounts_may_wear_the_same_picture(env):
    """Content addresses are shared by construction: the same bytes are the
    same key for everyone, so a second upload of them must not collide."""
    new_client, factory = env
    first, second = new_client(), new_client()
    await register(first, "Twin1")
    await register(second, "Twin2")
    picture = png_bytes(seed=9)
    one = await first.post("/api/users/me/avatar", json=encoded(picture))
    two = await second.post("/api/users/me/avatar", json=encoded(picture))
    assert one.status_code == 200 and two.status_code == 200, two.text
    assert one.json()["avatarKey"] == two.json()["avatarKey"]
    async with factory() as session:
        rows = (await session.scalars(select(UploadedAvatarAsset))).all()
    assert len(rows) == 2
    # One taking theirs down leaves the other's served.
    assert (await first.delete("/api/users/me/avatar")).status_code == 200
    assert (await second.get(two.json()["avatarUrl"])).status_code == 200


def test_the_room_report_command_takes_every_report_reason():
    """The socket payload spells its reasons out as a Literal; this is what
    keeps it from silently missing one the REST body and the dialog offer."""
    from typing import get_args

    from app.domain_values import ReportReason
    from app.handlers.payloads import ReportPlayerPayload

    literal = ReportPlayerPayload.model_fields["reason"].annotation
    assert set(get_args(literal)) == {reason.value for reason in ReportReason}
    parsed = ReportPlayerPayload.model_validate(
        {"targetPlayerId": "seat-1", "reason": "inappropriate_avatar", "details": "Look."}
    )
    assert parsed.reason == "inappropriate_avatar"


async def test_a_registered_player_wears_a_doodle_in_the_deployment_s_ink(env):
    """R-AVA-06: a doodle is a name, drawn from the sprite the frontend
    ships, so nothing is uploaded or stored but the name."""
    new_client, factory = env
    http = new_client()
    account = await register(http, "Doodler")
    chosen = await http.put("/api/users/me/avatar/doodle", json={"name": "fox"})
    assert chosen.status_code == 200, chosen.text
    assert chosen.json() == {"avatarKey": "doodle:fox", "avatarUrl": "/avatars/doodles.svg#fox"}
    assert (await http.get("/api/auth/me")).json()["avatarUrl"] == "/avatars/doodles.svg#fox"
    new_client.changed.assert_awaited_with(account["id"], "doodle:fox")
    async with factory() as session:
        kinds = set((await session.scalars(select(AuditEvent.event_type))).all())
        assert "avatar.doodle_chosen" in kinds

    # Not a name we have: refused, and a guest cannot wear one at all.
    assert (await http.put("/api/users/me/avatar/doodle", json={"name": "dragon"})).status_code == 400
    guest = new_client()
    await guest.post("/api/auth/display-name", json={"displayName": "Passing"})
    assert (await guest.put("/api/users/me/avatar/doodle", json={"name": "fox"})).status_code == 403


async def test_a_new_account_starts_with_a_doodle(env):
    """Claiming an account gives it a random doodle (R-AVA-06), so a
    registered player looks claimed from their first seat; a guest keeps
    the initial that marks them (R-ACCT-05)."""
    new_client, _ = env
    http = new_client()
    guest = (await http.post("/api/auth/display-name", json={"displayName": "Newcomer"})).json()
    assert guest["avatarUrl"] is None
    registered = await register(http, "Newcomer")
    assert registered["avatarUrl"].startswith("/avatars/doodles.svg#")
    assert registered["avatarUrl"].split("#")[1] in DOODLES


async def test_a_doodle_replaces_an_upload_and_an_upload_replaces_a_doodle(env):
    new_client, factory = env
    http = new_client()
    await register(http, "Fickle")
    uploaded = (await http.post("/api/users/me/avatar", json=encoded(png_bytes(seed=4)))).json()
    assert (await http.put("/api/users/me/avatar/doodle", json={"name": "owl"})).status_code == 200
    # One picture per account: the uploaded bytes went with the choice.
    assert (await http.get(uploaded["avatarUrl"])).status_code == 404
    async with factory() as session:
        assert (await session.scalars(select(UploadedAvatarAsset))).all() == []
    again = await http.post("/api/users/me/avatar", json=encoded(png_bytes(seed=4)))
    assert again.status_code == 200
    assert (await http.get("/api/auth/me")).json()["avatarUrl"] == again.json()["avatarUrl"]
    # Removing clears either kind.
    assert (await http.put("/api/users/me/avatar/doodle", json={"name": "owl"})).status_code == 200
    assert (await http.delete("/api/users/me/avatar")).status_code == 200
    assert (await http.get("/api/auth/me")).json()["avatarUrl"] is None


async def test_a_moderator_s_block_does_not_keep_a_player_from_a_doodle(env):
    new_client, factory = env
    http = new_client()
    account = await register(http, "Blocked")
    await remove_avatar(factory, user_id=account["id"], actor_id=None, by_moderator=True)
    with pytest.raises(AvatarBlocked):
        await set_avatar(factory, user_id=account["id"], payload=png_bytes())
    assert (await http.put("/api/users/me/avatar/doodle", json={"name": "cat"})).status_code == 200


def test_the_doodle_list_is_the_same_on_the_server_the_client_and_the_sprite():
    """Three places name the doodles; adding one to fewer than all three
    would either refuse a drawing the client offers or offer a name the
    sprite cannot draw."""
    root = Path(__file__).resolve().parent.parent.parent
    sprite = (root / "frontend" / "public" / "avatars" / "doodles.svg").read_text("utf-8")
    symbols = re.findall(r'<symbol id="([a-z]+)"', sprite)
    assert list(symbols) == list(DOODLES)
    client = (root / "frontend" / "src" / "lib" / "avatarDoodles.ts").read_text("utf-8")
    listed = re.search(r"DOODLES = \[(.*?)\] as const", client, re.S)
    assert listed is not None
    assert re.findall(r'"([a-z]+)"', listed.group(1)) == list(DOODLES)


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


@pytest.mark.parametrize("layout", ["VP8L", "VP8 ", "VP8X"])
async def test_a_webp_of_any_layout_is_taken_and_served_as_webp(env, layout):
    """What a browser encodes from a canvas: lossless, lossy, or extended
    (alpha) - each keeps its size somewhere else in the header."""
    new_client, _ = env
    http = new_client()
    await register(http, f"Web{layout.strip()}")
    picture = webp_bytes(seed=5, layout=layout)
    uploaded = await http.post("/api/users/me/avatar", json=encoded(picture))
    assert uploaded.status_code == 200, uploaded.text
    key = uploaded.json()["avatarKey"]
    assert key == avatar_key_for(picture, "image/webp")
    assert key.endswith(".webp")
    fetched = await new_client().get(f"/api/avatars/{key}")
    assert fetched.status_code == 200
    assert fetched.content == picture
    assert fetched.headers["content-type"] == "image/webp"
    assert fetched.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "payload, message",
    [
        (b"not a picture at all", "not a WebP or PNG"),
        (png_bytes(200, 256), "256 by 256"),
        (png_bytes(256, 300), "256 by 256"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, "not a WebP or PNG"),
        (webp_bytes(256, 128, layout="VP8L"), "256 by 256"),
        (webp_bytes(300, 256, layout="VP8 "), "256 by 256"),
        (webp_bytes(256, 257, layout="VP8X"), "256 by 256"),
        # A RIFF that is not WebP, and a WebP whose first chunk is unknown.
        (b"RIFF\x10\x00\x00\x00WAVEfmt " + b"\x00" * 24, "not a WebP or PNG"),
        (b"RIFF\x10\x00\x00\x00WEBPXXXX" + b"\x00" * 24, "not a WebP or PNG"),
        # A lossless header without its signature byte, a lossy one without
        # its start code: neither is a frame a browser would draw.
        (b"RIFF\x20\x00\x00\x00WEBPVP8L\x10\x00\x00\x00\x00" + b"\x00" * 40, "not a WebP or PNG"),
        (b"RIFF\x20\x00\x00\x00WEBPVP8 \x10\x00\x00\x00" + b"\x00" * 40, "not a WebP or PNG"),
    ],
)
async def test_only_a_square_picture_of_the_right_size_is_taken(env, payload, message):
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
