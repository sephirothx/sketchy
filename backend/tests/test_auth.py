import asyncio
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.jwt import JWT_COOKIE_NAME, create_token, decode_token, get_or_create_secret
from app.auth.middleware import (
    AuthMiddleware,
    clear_auth_cookie,
    cookie_should_be_secure,
    set_auth_cookie,
)
from app.auth.password import hash_password, verify_password
from app.auth.schemas import LoginRequest, RegisterRequest, suggest_username
from app.auth.nickname import guest_nickname_is_available
from app.db.models import Base
from app.handlers.connection import extract_jwt_cookie
from app.main import user_payload
from app.repositories.interfaces import AccountAlreadyClaimedError, UsernameTakenError
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from fastapi import FastAPI, HTTPException, Request, Response


def test_password_hashing():
    pw = "supersecret123"
    pw_hash = hash_password(pw)
    assert pw_hash != pw
    assert verify_password(pw, pw_hash) is True
    assert verify_password("wrongpassword", pw_hash) is False


def test_suggest_username_sanitizes_nicknames():
    assert suggest_username("Stefano") == "Stefano"
    assert suggest_username("Cool Cat") == "Cool_Cat"
    assert suggest_username("ab") == ""
    assert suggest_username("!!!") == ""


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
    from app.auth import jwt as jwt_mod
    previous = jwt_mod._cached_jwt_secret
    jwt_mod._cached_jwt_secret = None
    try:
        secret1 = await get_or_create_secret(session_factory)
        secret2 = await get_or_create_secret(session_factory)
        assert secret1 == secret2
        assert len(secret1) == 64

        token = create_token("user-123", secret1)
        assert decode_token(token, secret1) == "user-123"
        assert decode_token(token, "wrongsecret") is None
        expired = create_token("user-123", secret1, expires_delta=timedelta(seconds=-1))
        assert decode_token(expired, secret1) is None
    finally:
        jwt_mod._cached_jwt_secret = previous
        await engine.dispose()


@pytest.mark.asyncio
async def test_auth_rest_flow_and_timestamps():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    repo = SqlAlchemyUserRepository(factory)
    from app.auth import jwt as jwt_mod
    previous = jwt_mod._cached_jwt_secret
    jwt_mod._cached_jwt_secret = None
    secret = await get_or_create_secret(factory)

    app = FastAPI()
    app.add_middleware(AuthMiddleware, user_repo=repo, jwt_secret_getter=lambda: secret)

    @app.get("/api/auth/me")
    async def me(request: Request):
        user = getattr(request.state, "user", None)
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        refreshed = await repo.record_login(user.id)
        return user_payload(refreshed or user)

    @app.get("/api/auth/nickname-available")
    async def nickname_available(request: Request, nickname: str = ""):
        current = getattr(request.state, "user", None)
        if current is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        available = await guest_nickname_is_available(repo, nickname, current.id)
        return {"available": available}

    @app.post("/api/auth/register")
    async def register(req: RegisterRequest, request: Request, response: Response):
        current = getattr(request.state, "user", None)
        if current is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if not current.is_anonymous:
            raise HTTPException(status_code=400, detail="Account is already registered")
        try:
            user = await repo.claim_account(current.id, req.username, hash_password(req.password))
        except UsernameTakenError:
            raise HTTPException(status_code=409, detail="Username is already taken")
        except AccountAlreadyClaimedError:
            raise HTTPException(status_code=400, detail="Account is already registered")
        set_auth_cookie(response, create_token(user.id, secret), secure=cookie_should_be_secure(request))
        return user_payload(user)

    @app.post("/api/auth/login")
    async def login(req: LoginRequest, request: Request, response: Response):
        creds = await repo.get_credentials_by_username(req.username)
        if not creds or not verify_password(req.password, creds.password_hash):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        user = await repo.record_login(creds.user.id) or creds.user
        set_auth_cookie(response, create_token(user.id, secret), secure=cookie_should_be_secure(request))
        return user_payload(user)

    @app.post("/api/auth/logout")
    async def logout(response: Response):
        clear_auth_cookie(response)
        return {"ok": True}

    unique_name = f"Alice_{uuid.uuid4().hex[:8]}"
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            me_resp = await client.get("/api/auth/me")
            assert me_resp.status_code == 200
            guest_data = me_resp.json()
            assert guest_data["isAnonymous"] is True
            assert guest_data["username"] is None
            assert guest_data["createdAt"]
            assert guest_data["lastLoginAt"]
            assert JWT_COOKIE_NAME in client.cookies

            await asyncio.sleep(0.05)
            me_again = await client.get("/api/auth/me")
            assert me_again.status_code == 200
            assert me_again.json()["id"] == guest_data["id"]
            assert me_again.json()["createdAt"] == guest_data["createdAt"]
            assert me_again.json()["lastLoginAt"] >= guest_data["lastLoginAt"]

            reg_resp = await client.post(
                "/api/auth/register",
                json={"username": unique_name, "password": "password123"},
            )
            assert reg_resp.status_code == 200
            claimed = reg_resp.json()
            assert claimed["id"] == guest_data["id"]
            assert claimed["username"] == unique_name
            assert claimed["isAnonymous"] is False
            assert claimed["createdAt"] == guest_data["createdAt"]

            dup_resp = await client.post(
                "/api/auth/register",
                json={"username": unique_name.lower(), "password": "password456"},
            )
            assert dup_resp.status_code == 400

            other = httpx.AsyncClient(transport=transport, base_url="http://testserver")
            await other.get("/api/auth/me")
            taken = await other.post(
                "/api/auth/register",
                json={"username": unique_name, "password": "password789"},
            )
            assert taken.status_code == 409
            free = await other.get("/api/auth/nickname-available", params={"nickname": "FreeGuestName"})
            assert free.status_code == 200
            assert free.json()["available"] is True
            blocked = await other.get("/api/auth/nickname-available", params={"nickname": unique_name})
            assert blocked.status_code == 200
            assert blocked.json()["available"] is False
            await other.aclose()

            logout_resp = await client.post("/api/auth/logout")
            assert logout_resp.status_code == 200
            assert logout_resp.json()["ok"] is True

            after_logout = await client.get("/api/auth/me")
            assert after_logout.status_code == 200
            assert after_logout.json()["isAnonymous"] is True
            assert after_logout.json()["id"] != guest_data["id"]

            await asyncio.sleep(0.05)
            login_resp = await client.post(
                "/api/auth/login",
                json={"username": unique_name, "password": "password123"},
            )
            assert login_resp.status_code == 200
            logged_in = login_resp.json()
            assert logged_in["id"] == guest_data["id"]
            assert logged_in["username"] == unique_name
            assert logged_in["createdAt"] == guest_data["createdAt"]
            assert logged_in["lastLoginAt"] >= claimed["lastLoginAt"]
    finally:
        jwt_mod._cached_jwt_secret = previous
        await engine.dispose()


def test_extract_jwt_cookie():
    environ_asgi = {
        "asgi.scope": {
            "headers": [
                (b"host", b"localhost:8000"),
                (b"cookie", b"other=123; sketchy_session=my_token_abc; foo=bar"),
            ]
        }
    }
    assert extract_jwt_cookie(environ_asgi) == "my_token_abc"
    assert extract_jwt_cookie({"headers": [(b"cookie", b"sketchy_session=token_direct")]}) == "token_direct"
    assert extract_jwt_cookie({"HTTP_COOKIE": "sketchy_session=token_wsgi"}) == "token_wsgi"
    assert extract_jwt_cookie({}) is None
