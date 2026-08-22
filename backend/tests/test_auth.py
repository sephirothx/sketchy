"""Opaque sessions, password, and REST authentication behavior."""
from __future__ import annotations

import pytest
import pytest_asyncio
from argon2 import PasswordHasher
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.middleware import SessionAuthMiddleware
from app.auth.names import validate_name, NameError_
from app.auth.password import (
    DUMMY_HASH,
    PasswordPolicyError,
    hash_password,
    password_needs_rehash,
    validate_password,
    verify_password,
)
from app.auth.rate_limit import RateLimiter
from app.auth.sessions import (
    COOKIE_NAME,
    hash_session_token,
    session_token_from_cookie_header,
)
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
    for limiter in (login_limiter, register_limiter, lookup_limiter):
        limiter.reset()

    repo = SqlAlchemyUserRepository(session_factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=session_factory)
    app.include_router(create_auth_router(repo, session_factory))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        http._test_user_repo = repo
        http._test_session_factory = session_factory
        yield http
    await engine.dispose()


# --- tokens ---------------------------------------------------------------

def test_token_hash_is_one_way_and_fixed_length():
    token = "opaque-token-with-no-account-data"
    digest = hash_session_token(token)
    assert len(digest) == 64
    assert token not in digest
    assert hash_session_token(token) == digest


def test_cookie_header_parsing():
    token = "raw-opaque-token"
    assert session_token_from_cookie_header(f"{COOKIE_NAME}={token}") == token
    assert session_token_from_cookie_header("unrelated=1") is None
    assert session_token_from_cookie_header(None) is None


def test_token_carries_no_account_details():
    """Opaque credentials contain no decodable user id or account fields."""
    import base64
    import secrets

    token = secrets.token_urlsafe(32)
    decoded = base64.urlsafe_b64decode(token + "=")
    assert len(decoded) == 32
    assert b"user" not in decoded


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


@pytest.mark.asyncio
async def test_stale_argon2_parameters_are_detected_and_hashes_fit_storage():
    password = "a-good-password"
    current = await hash_password(password)
    stale = PasswordHasher(
        time_cost=1, memory_cost=8192, parallelism=1
    ).hash(password)

    assert await password_needs_rehash(current) is False
    assert await password_needs_rehash(stale) is True
    assert await password_needs_rehash("not-a-hash") is False
    assert len(current) <= 255


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


class FakeClock:
    """A monotonic reading the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_clients_that_have_aged_out_stop_being_tracked():
    """Every distinct caller used to leave a permanent entry behind."""
    clock = FakeClock()
    limiter = RateLimiter(limit=5, window_seconds=60, clock=clock)

    for index in range(100):
        assert limiter.check(f"visitor-{index}") is True
    assert limiter.tracked_keys() == 100

    # A whole window later, none of them can refuse anything any more.
    clock.advance(61)
    assert limiter.check("someone-else") is True
    assert limiter.tracked_keys() == 1


def test_a_client_still_inside_its_window_is_never_forgotten():
    """Sweeping must not hand a saturated client a fresh allowance."""
    clock = FakeClock()
    limiter = RateLimiter(limit=2, window_seconds=60, clock=clock)

    assert limiter.check("attacker") is True
    assert limiter.check("attacker") is True
    assert limiter.check("attacker") is False

    # Long enough to trigger a sweep, but not to expire the attempts.
    clock.advance(59)
    for index in range(50):
        limiter.check(f"noise-{index}")
    assert limiter.check("attacker") is False, "the limit outlived the sweep"

    # Only once the attempts themselves age out does the allowance return.
    clock.advance(2)
    assert limiter.check("attacker") is True


def test_flooding_the_limiter_cannot_evict_a_saturated_bucket():
    """A size cap would let a client buy its way out; ageing must not."""
    clock = FakeClock()
    limiter = RateLimiter(limit=1, window_seconds=300, clock=clock)

    assert limiter.check("attacker") is True
    assert limiter.check("attacker") is False

    for index in range(5_000):
        clock.advance(0.01)
        limiter.check(f"flood-{index}")

    assert limiter.check("attacker") is False


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
async def test_active_sessions_can_be_listed_and_revoked_individually(client):
    await client.post(
        "/api/auth/register",
        json={"username": "Devices", "password": "a-good-password"},
        headers={"user-agent": "Firefox/120 (Linux)"},
    )
    other = AsyncClient(transport=client._transport, base_url="http://test")
    async with other:
        signed_in = await other.post(
            "/api/auth/login",
            json={"username": "Devices", "password": "a-good-password"},
            headers={"user-agent": "Chrome/140 (Windows)"},
        )
        assert signed_in.status_code == 200

        listed = await client.get("/api/auth/sessions")
        assert listed.status_code == 200
        sessions = listed.json()["sessions"]
        assert len(sessions) == 2
        assert sum(item["current"] for item in sessions) == 1
        other_session = next(item for item in sessions if not item["current"])
        assert "Chrome" in other_session["deviceLabel"]
        assert "token" not in other_session

        revoked = await client.delete(
            f"/api/auth/sessions/{other_session['id']}"
        )
        assert revoked.status_code == 200
        assert (await other.get("/api/auth/sessions")).status_code == 401


@pytest.mark.asyncio
async def test_logout_all_revokes_every_device(client):
    await client.post(
        "/api/auth/register",
        json={"username": "Everywhere", "password": "a-good-password"},
    )
    other = AsyncClient(transport=client._transport, base_url="http://test")
    async with other:
        await other.post(
            "/api/auth/login",
            json={"username": "Everywhere", "password": "a-good-password"},
        )
        response = await client.post("/api/auth/logout-all")
        assert response.status_code == 200
        assert response.json()["revoked"] == 2
        assert (await other.get("/api/auth/sessions")).status_code == 401


@pytest.mark.asyncio
async def test_login_rehashes_a_stale_password(client, monkeypatch):
    from unittest.mock import AsyncMock
    from app.auth import routes as routes_module

    await client.post(
        "/api/auth/register",
        json={"username": "RehashMe", "password": "a-good-password"},
    )
    credentials = await client._test_user_repo.get_credentials_by_username("RehashMe")
    assert credentials is not None

    monkeypatch.setattr(
        routes_module, "password_needs_rehash", AsyncMock(return_value=True)
    )
    replacement = await hash_password("a-good-password")
    monkeypatch.setattr(
        routes_module, "hash_password", AsyncMock(return_value=replacement)
    )

    response = await client.post(
        "/api/auth/login",
        json={"username": "RehashMe", "password": "a-good-password"},
    )
    assert response.status_code == 200
    refreshed = await client._test_user_repo.get_credentials_by_username("RehashMe")
    assert refreshed is not None
    assert refreshed.password_hash == replacement
    assert refreshed.password_hash != credentials.password_hash


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


@pytest.mark.asyncio
async def test_a_new_guest_starts_with_no_name(client):
    """An empty display name is the signal that this is someone's first run.

    Nothing is invented for them: they either choose a name or sign up.
    """
    body = (await client.get("/api/auth/me")).json()
    assert body["displayName"] == ""
    assert body["isAnonymous"] is True


# --- name color -----------------------------------------------------------

@pytest.mark.asyncio
async def test_registered_player_colour_is_stored_on_the_account(client):
    """Settings keeps the colour in localStorage; the account is what lets it
    show up anywhere the player is not currently sitting."""
    await client.post(
        "/api/auth/register", json={"username": "colorist", "password": "a-good-password"}
    )

    response = await client.post("/api/auth/name-color", json={"nameColor": "#4F46E5"})

    assert response.status_code == 200
    assert response.json()["nameColor"] == "#4f46e5"
    assert (await client.get("/api/auth/me")).json()["nameColor"] == "#4f46e5"


@pytest.mark.asyncio
async def test_a_guest_cannot_colour_their_name(client):
    """Grey italics is the only cue an unclaimed name carries."""
    await client.get("/api/auth/me")
    response = await client.post("/api/auth/name-color", json={"nameColor": "#4f46e5"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_a_colour_that_is_not_a_colour_is_rejected(client):
    await client.post(
        "/api/auth/register", json={"username": "painter", "password": "a-good-password"}
    )
    assert (
        await client.post("/api/auth/name-color", json={"nameColor": "red"})
    ).status_code == 400
