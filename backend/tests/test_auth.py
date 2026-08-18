"""JWT, password, and REST authentication behaviour."""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import jwt as jwt_module
from app.auth.jwt import COOKIE_NAME, create_token, decode_token
from app.auth.middleware import SessionAuthMiddleware, user_id_from_cookie_header
from app.auth.names import validate_name, NameError_
from app.auth.password import (
    DUMMY_HASH,
    PasswordPolicyError,
    hash_password,
    validate_password,
    verify_password,
)
from app.auth.rate_limit import RateLimiter
from app.auth.routes import (
    create_auth_router,
    login_limiter,
    lookup_limiter,
    register_limiter,
)
from app.db.models import Base
from app.repositories.sqlalchemy import SqlAlchemyUserRepository


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    jwt_module.reset_secret_cache()
    for limiter in (login_limiter, register_limiter, lookup_limiter):
        limiter.reset()

    repo = SqlAlchemyUserRepository(session_factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=session_factory)
    app.include_router(create_auth_router(repo, session_factory))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    await engine.dispose()
    jwt_module.reset_secret_cache()


# --- tokens ---------------------------------------------------------------

def test_token_round_trip_and_rejection():
    token = create_token("user-1", "secret")
    assert decode_token(token, "secret") == "user-1"
    assert decode_token(token, "other-secret") is None
    assert decode_token("not-a-token", "secret") is None
    assert decode_token("", "secret") is None


def test_cookie_header_parsing():
    token = create_token("user-1", "secret")
    assert user_id_from_cookie_header(f"{COOKIE_NAME}={token}", "secret") == "user-1"
    assert user_id_from_cookie_header(f"{COOKIE_NAME}=tampered", "secret") is None
    assert user_id_from_cookie_header("unrelated=1", "secret") is None
    assert user_id_from_cookie_header(None, "secret") is None


def test_token_carries_no_account_details():
    """Only the subject travels, so a claim or login takes effect at once."""
    import jwt as pyjwt

    payload = pyjwt.decode(create_token("user-1", "secret"), "secret", algorithms=["HS256"])
    assert set(payload) == {"sub", "iat", "exp"}


# --- passwords ------------------------------------------------------------

@pytest.mark.asyncio
async def test_password_hash_and_verify():
    hashed = await hash_password("a-good-password")
    assert hashed != "a-good-password"
    assert await verify_password(hashed, "a-good-password") is True
    assert await verify_password(hashed, "wrong") is False
    assert await verify_password("not-a-hash", "a-good-password") is False


@pytest.mark.asyncio
async def test_dummy_hash_is_verifiable_but_never_matches():
    """Used for absent usernames, so it must behave like a real hash."""
    assert await verify_password(DUMMY_HASH, "no-such-account") is True
    assert await verify_password(DUMMY_HASH, "anything-else") is False


@pytest.mark.parametrize("bad", ["", "short", "x" * 129, 12345, None])
def test_password_policy_rejects(bad):
    with pytest.raises(PasswordPolicyError):
        validate_password(bad)


# --- names ----------------------------------------------------------------

@pytest.mark.parametrize("good", ["abc", "Stefano", "a-b_c", "0123456789abcdef"])
def test_valid_names(good):
    assert validate_name(good) == good


@pytest.mark.parametrize(
    "bad", ["ab", "", "x" * 17, "has space", "Guest", "ADMIN", "emoji😀", "semi;colon"]
)
def test_invalid_names(bad):
    with pytest.raises(NameError_):
        validate_name(bad)


# --- rate limiting --------------------------------------------------------

def test_rate_limiter_is_per_key():
    limiter = RateLimiter(limit=2, window_seconds=60)
    assert [limiter.check("a"), limiter.check("a"), limiter.check("a")] == [True, True, False]
    assert limiter.check("b") is True


# --- REST -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_me_provisions_a_guest_and_sets_an_httponly_cookie(client):
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["isAnonymous"] is True
    assert body["username"] is None
    assert body["createdAt"] and body["lastLoginAt"]

    cookie = response.headers["set-cookie"].lower()
    assert COOKIE_NAME in cookie
    # HttpOnly keeps the token out of JavaScript; Lax blunts cross-site POSTs.
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    # Long-lived on purpose: expiry would orphan a guest's accumulated stats.
    assert "max-age=31536000" in cookie


@pytest.mark.asyncio
async def test_me_is_stable_across_calls(client):
    first = (await client.get("/api/auth/me")).json()
    second = (await client.get("/api/auth/me")).json()
    assert first["id"] == second["id"]


@pytest.mark.asyncio
async def test_register_claims_the_current_guest_identity(client):
    guest = (await client.get("/api/auth/me")).json()

    registered = await client.post(
        "/api/auth/register", json={"username": "Stefano", "password": "a-good-password"}
    )
    assert registered.status_code == 200
    body = registered.json()
    # Same id: everything the guest accumulated stays attached to them.
    assert body["id"] == guest["id"]
    assert body["isAnonymous"] is False
    assert body["username"] == "Stefano"

    assert (await client.get("/api/auth/me")).json()["username"] == "Stefano"


@pytest.mark.asyncio
async def test_register_rejects_a_taken_username_case_insensitively(client):
    await client.get("/api/auth/me")
    await client.post(
        "/api/auth/register", json={"username": "Stefano", "password": "a-good-password"}
    )

    other = AsyncClient(transport=client._transport, base_url="http://test")
    async with other:
        await other.get("/api/auth/me")
        clash = await other.post(
            "/api/auth/register", json={"username": "STEFANO", "password": "another-password"}
        )
    assert clash.status_code == 409


@pytest.mark.asyncio
async def test_register_rejects_weak_password_and_bad_username(client):
    await client.get("/api/auth/me")
    assert (
        await client.post("/api/auth/register", json={"username": "ok-name", "password": "short"})
    ).status_code == 400
    assert (
        await client.post(
            "/api/auth/register", json={"username": "has space", "password": "a-good-password"}
        )
    ).status_code == 400


@pytest.mark.asyncio
async def test_login_logout_round_trip(client):
    await client.get("/api/auth/me")
    await client.post(
        "/api/auth/register", json={"username": "Stefano", "password": "a-good-password"}
    )

    assert (await client.post("/api/auth/logout")).status_code == 200
    # Logging out drops the session, so the next visit is a brand new guest.
    fresh = (await client.get("/api/auth/me")).json()
    assert fresh["isAnonymous"] is True

    signed_in = await client.post(
        "/api/auth/login", json={"username": "stefano", "password": "a-good-password"}
    )
    assert signed_in.status_code == 200
    assert signed_in.json()["username"] == "Stefano"


@pytest.mark.asyncio
async def test_login_failures_are_indistinguishable(client):
    await client.get("/api/auth/me")
    await client.post(
        "/api/auth/register", json={"username": "Stefano", "password": "a-good-password"}
    )

    wrong_password = await client.post(
        "/api/auth/login", json={"username": "Stefano", "password": "not-the-password"}
    )
    no_such_user = await client.post(
        "/api/auth/login", json={"username": "nobody", "password": "not-the-password"}
    )
    assert wrong_password.status_code == no_such_user.status_code == 401
    assert wrong_password.json()["detail"] == no_such_user.json()["detail"]


@pytest.mark.asyncio
async def test_nickname_availability_reflects_registered_usernames(client):
    await client.get("/api/auth/me")
    await client.post(
        "/api/auth/register", json={"username": "Stefano", "password": "a-good-password"}
    )

    taken = await client.get("/api/auth/nickname-available", params={"name": "stefano"})
    assert taken.json()["available"] is False

    free = await client.get("/api/auth/nickname-available", params={"name": "someone-new"})
    assert free.json()["available"] is True

    invalid = await client.get("/api/auth/nickname-available", params={"name": "ab"})
    assert invalid.json()["available"] is False


@pytest.mark.asyncio
async def test_login_is_rate_limited(client):
    await client.get("/api/auth/me")
    await client.post(
        "/api/auth/register", json={"username": "Stefano", "password": "a-good-password"}
    )

    statuses = [
        (
            await client.post(
                "/api/auth/login", json={"username": "Stefano", "password": "guess"}
            )
        ).status_code
        for _ in range(12)
    ]
    assert 429 in statuses, "brute force was never throttled"


@pytest.mark.asyncio
async def test_registering_twice_is_rejected(client):
    await client.get("/api/auth/me")
    await client.post(
        "/api/auth/register", json={"username": "Stefano", "password": "a-good-password"}
    )
    again = await client.post(
        "/api/auth/register", json={"username": "Another", "password": "a-good-password"}
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_guest_display_name_is_persisted_and_survives_reload(client):
    await client.get("/api/auth/me")
    saved = await client.post("/api/auth/display-name", json={"displayName": "Wanderer"})
    assert saved.status_code == 200
    assert saved.json()["displayName"] == "Wanderer"
    # Persisted server-side, so a cleared localStorage does not lose the choice.
    assert (await client.get("/api/auth/me")).json()["displayName"] == "Wanderer"


@pytest.mark.asyncio
async def test_guest_cannot_take_a_registered_username_as_display_name(client):
    await client.get("/api/auth/me")
    await client.post(
        "/api/auth/register", json={"username": "Stefano", "password": "a-good-password"}
    )

    guest = AsyncClient(transport=client._transport, base_url="http://test")
    async with guest:
        await guest.get("/api/auth/me")
        clash = await guest.post("/api/auth/display-name", json={"displayName": "stefano"})
        assert clash.status_code == 409
        assert (
            await guest.post("/api/auth/display-name", json={"displayName": "has space"})
        ).status_code == 400


@pytest.mark.asyncio
async def test_claiming_an_account_aligns_display_name_with_username(client):
    await client.get("/api/auth/me")
    await client.post("/api/auth/display-name", json={"displayName": "Wanderer"})
    claimed = await client.post(
        "/api/auth/register", json={"username": "Stefano", "password": "a-good-password"}
    )
    # Registered players play as their username, so the two must not drift.
    assert claimed.json()["displayName"] == "Stefano"
