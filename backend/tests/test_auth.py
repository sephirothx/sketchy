import uuid
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.jwt import create_token, decode_token, get_or_create_jwt_secret
from app.auth.password import hash_password, verify_password
from app.db.models import Base
from app.main import api, user_repo, lifespan


def test_password_hashing():
    pw = "supersecret123"
    pw_hash = hash_password(pw)
    assert pw_hash != pw
    assert verify_password(pw, pw_hash) is True
    assert verify_password("wrongpassword", pw_hash) is False


@pytest.mark.asyncio
async def test_jwt_secret_persistence_and_tokens():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        secret1 = await get_or_create_jwt_secret(session_factory)
        secret2 = await get_or_create_jwt_secret(session_factory)
        assert secret1 == secret2
        assert len(secret1) == 64

        token = create_token("user-123", secret1)
        user_id = decode_token(token, secret1)
        assert user_id == "user-123"

        invalid = decode_token(token, "wrongsecret")
        assert invalid is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_auth_rest_flow():
    unique_name = f"Alice_{uuid.uuid4().hex[:6]}"
    async with lifespan(api):
        transport = httpx.ASGITransport(app=api)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. First visit auto-provisions a guest user
            me_resp = await client.get("/api/auth/me")
            assert me_resp.status_code == 200
            guest_data = me_resp.json()
            assert guest_data["isAnonymous"] is True
            assert guest_data["username"] is None
            assert "sketchy_session" in client.cookies

            # 2. Register / claim the anonymous account
            reg_resp = await client.post(
                "/api/auth/register",
                json={"username": unique_name, "password": "password123"},
            )
            assert reg_resp.status_code == 200
            claimed_data = reg_resp.json()
            assert claimed_data["id"] == guest_data["id"]
            assert claimed_data["username"] == unique_name
            assert claimed_data["isAnonymous"] is False

            # 3. Duplicate registration is rejected
            dup_resp = await client.post(
                "/api/auth/register",
                json={"username": unique_name.lower(), "password": "password456"},
            )
            assert dup_resp.status_code == 409

            # 4. Log out (issues new guest account)
            logout_resp = await client.post("/api/auth/logout")
            assert logout_resp.status_code == 200
            logout_data = logout_resp.json()
            assert logout_data["ok"] is True
            assert logout_data["user"]["isAnonymous"] is True
            assert logout_data["user"]["id"] != guest_data["id"]

            # 5. Log back in as Alice
            login_resp = await client.post(
                "/api/auth/login",
                json={"username": unique_name, "password": "password123"},
            )
            assert login_resp.status_code == 200
            logged_in = login_resp.json()
            assert logged_in["id"] == guest_data["id"]
            assert logged_in["username"] == unique_name


@pytest.mark.asyncio
async def test_registered_user_nickname_and_guest_collision_rejection():
    from app.handlers import register_all_handlers
    from app.rooms import RoomManager
    from unittest.mock import AsyncMock
    import socketio

    unique_user = f"Bob_{uuid.uuid4().hex[:6]}"
    async with lifespan(api):
        # 1. Register a user Bob
        registered = await user_repo.register(
            username=unique_user,
            password_hash=hash_password("password123"),
            display_name=unique_user,
        )

        room_mgr = RoomManager()
        sio = socketio.AsyncServer(async_mode="asgi")
        register_all_handlers(sio, room_mgr, user_repo=user_repo)
        sio.emit = AsyncMock()
        sio.enter_room = AsyncMock()

        # 2. Registered user tries to create room passing a different nickname "CustomNick"
        sio.get_session = AsyncMock(return_value={"user_id": registered.id})
        sio.save_session = AsyncMock()
        create_res = await sio.handlers["/"]["create_room"](
            "sid-bob",
            {"nickname": "CustomNick", "name": "BobRoom"},
        )
        assert create_res["ok"] is True
        room = room_mgr.get_room(create_res["roomId"])
        # Server must enforce registered username!
        assert room.players[create_res["playerId"]].nickname == unique_user

        # 3. Guest user tries to join/create a room using Bob's registered username
        sio.get_session = AsyncMock(return_value=None)
        guest_create_res = await sio.handlers["/"]["create_room"](
            "sid-guest",
            {"nickname": unique_user, "name": "GuestRoom"},
        )
        assert guest_create_res["ok"] is False
        assert "already taken by a registered account" in guest_create_res["error"]

        # 4. Guest user uses a unique name not taken by any registered user
        guest_ok_res = await sio.handlers["/"]["create_room"](
            "sid-guest2",
            {"nickname": f"Guest_{uuid.uuid4().hex[:4]}", "name": "GuestRoom2"},
        )
        assert guest_ok_res["ok"] is True
