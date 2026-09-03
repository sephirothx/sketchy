"""Cross-device registered-account settings and boundary validation."""
from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.user_settings import (
    DEFAULT_KEY_BINDINGS,
    UserSettingsSeed,
    create_user_settings_router,
    seed_user_settings,
)
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import Base, UserSettings
from app.repositories.sqlalchemy import SqlAlchemyUserRepository


pytestmark = pytest.mark.asyncio
PASSWORD = "a-good-password"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "settings-test-secret")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    users = SqlAlchemyUserRepository(factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(users, factory))
    app.include_router(create_user_settings_router(factory))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http, factory
    await engine.dispose()


async def test_guests_remain_local_only(env):
    http, factory = env
    guest = (
        await http.post("/api/auth/display-name", json={"displayName": "Visitor"})
    ).json()
    response = await http.get("/api/users/me/settings")
    assert response.status_code == 403
    async with factory() as session:
        assert await session.get(UserSettings, UUID(guest["id"])) is None


async def test_registration_seeds_and_patch_persists_settings(env):
    http, factory = env
    seeded = {
        "theme": "dark",
        "soundEffects": False,
        "confettiEffects": False,
        "volume": 0.35,
        "brushCursor": "circle",
        "keyBindings": {**DEFAULT_KEY_BINDINGS, "brush": ["b"]},
        "colorblindSafeColors": True,
    }
    registered = await http.post(
        "/api/auth/register",
        json={
            "username": "SettingsOwner",
            "password": PASSWORD,
            "settings": seeded,
        },
    )
    assert registered.status_code == 200

    loaded = await http.get("/api/users/me/settings")
    assert loaded.status_code == 200
    for key, value in seeded.items():
        assert loaded.json()[key] == value

    patched = await http.patch(
        "/api/users/me/settings",
        json={"theme": "light", "volume": 0.9},
    )
    assert patched.status_code == 200
    assert patched.json()["theme"] == "light"
    assert patched.json()["volume"] == 0.9
    assert patched.json()["brushCursor"] == "circle"

    async with factory() as session:
        row = await session.scalar(select(UserSettings))
        assert row is not None
        assert row.theme == "light"
        assert row.sound_effects_volume == 0.9


async def test_registration_seed_never_overwrites_existing_settings(env):
    http, factory = env
    registered = await http.post(
        "/api/auth/register",
        json={
            "username": "SeedOnce",
            "password": PASSWORD,
            "settings": {"theme": "dark"},
        },
    )
    assert registered.status_code == 200
    existing = await seed_user_settings(
        factory,
        user_id=registered.json()["id"],
        values=UserSettingsSeed(theme="light"),
    )
    assert existing["theme"] == "dark"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"theme": "sepia"},
        {"volume": -0.01},
        {"volume": 1.01},
        {"brushCursor": "dot"},
        {"keyBindings": {"brush": ["b"]}},
    ],
)
async def test_patch_rejects_invalid_or_unbounded_values(env, body):
    http, _ = env
    assert (
        await http.post(
            "/api/auth/register",
            json={"username": "Validation", "password": PASSWORD},
        )
    ).status_code == 200
    response = await http.patch("/api/users/me/settings", json=body)
    assert response.status_code == 422


async def test_database_checks_reject_invalid_theme_and_volume(env):
    http, factory = env
    registered = await http.post(
        "/api/auth/register",
        json={"username": "DbChecks", "password": PASSWORD},
    )
    user_id = UUID(registered.json()["id"])
    async with factory() as session:
        async with session.begin():
            row = await session.get(UserSettings, user_id)
            assert row is not None
            await session.delete(row)

    async with factory() as session:
        async with session.begin():
            defaults = UserSettings(user_id=user_id)
            session.add(defaults)
            await session.flush()
            assert defaults.theme == "system"
            assert defaults.sound_effects_volume == 0.7
            assert defaults.key_bindings == DEFAULT_KEY_BINDINGS
            await session.delete(defaults)

    with pytest.raises(IntegrityError):
        async with factory() as session:
            async with session.begin():
                session.add(
                    UserSettings(
                        user_id=user_id,
                        theme="sepia",
                        sound_effects_volume=2,
                    )
                )
