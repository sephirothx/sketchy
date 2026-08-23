"""Private room-setting preset storage and API contracts."""

from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.room_presets import create_room_preset_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import RoomPreset
from app.repositories.interfaces import PromptListEntryInput
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)
from app.services.room_presets import RoomPresetError, RoomPresetService


from tests.dbfixtures import create_test_db

pytestmark = pytest.mark.asyncio
PASSWORD = "a-good-password"


def settings(slug: str, **overrides) -> dict:
    value = {
        "name": "Friday room",
        "isPublic": False,
        "maxPlayers": 12,
        "rounds": 5,
        "drawingSeconds": 120,
        "customPrompts": "",
        "customPromptsOnly": False,
        "hintMode": "none",
        "scoringMode": "pressure",
        "spectatorsSeePrompt": True,
        "hideMaskedPrompt": False,
        "allowedTools": ["brush", "shapes"],
        "colorMode": "colorblind_safe",
        "promptListSlugs": [slug],
        "promptListShareCodes": [],
    }
    value.update(overrides)
    return value


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "room-preset-test-secret")
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    prompt_lists = SqlAlchemyPromptListRepository(factory)
    service = RoomPresetService(factory, prompt_lists)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(users, factory))
    app.include_router(create_room_preset_router(service))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, users, prompt_lists, service, factory
    await engine.dispose()


async def register(client: AsyncClient, username: str = "PresetOwner") -> dict:
    response = await client.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()


async def owned_prompt_list(prompt_lists, owner_id: str, name: str = "My prompts"):
    return await prompt_lists.create_owned(
        owner_id,
        name=name,
        description="",
        language="en",
        visibility="private",
        prompts=(PromptListEntryInput(answer="red panda"),),
    )


async def test_crud_is_private_versioned_and_configuration_only(env):
    client, _, prompt_lists, _, factory = env
    owner = await register(client)
    prompt_list = await owned_prompt_list(prompt_lists, owner["id"])

    created = await client.post(
        "/api/room-presets",
        json={"name": "  Tournament   night ", "settings": settings(prompt_list.slug)},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Tournament night"
    assert body["version"] == 1
    assert UUID(body["id"]).version == 7
    assert body["settings"] == settings(prompt_list.slug)
    assert "code" not in body
    assert "members" not in body
    assert "roomId" not in body

    listed = await client.get("/api/room-presets")
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()] == ["Tournament night"]
    assert "settings" not in listed.json()[0]

    updated_list = await prompt_lists.update_owned(
        owner["id"],
        prompt_list.id,
        expected_version=1,
        name=prompt_list.name,
        description="",
        visibility="private",
        prompts=(PromptListEntryInput(answer="snow leopard"),),
    )
    assert updated_list.version == 2
    fetched = await client.get(f"/api/room-presets/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["settings"]["promptListSlugs"] == [prompt_list.slug]

    changed_settings = settings(prompt_list.slug, rounds=7, isPublic=True)
    updated = await client.put(
        f"/api/room-presets/{body['id']}",
        json={
            "expectedVersion": 1,
            "name": "Finals",
            "settings": changed_settings,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["settings"]["rounds"] == 7
    assert updated.json()["settings"]["isPublic"] is True

    stale = await client.put(
        f"/api/room-presets/{body['id']}",
        json={
            "expectedVersion": 1,
            "name": "Stale",
            "settings": changed_settings,
        },
    )
    assert stale.status_code == 409

    deleted = await client.delete(f"/api/room-presets/{body['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/room-presets/{body['id']}")).status_code == 404
    async with factory() as session:
        assert await session.scalar(select(RoomPreset.id)) is None


async def test_rejects_guests_quick_prompts_shared_lists_and_duplicate_names(env):
    client, users, prompt_lists, service, _ = env
    guest = await users.create_anonymous("Guest")
    with pytest.raises(RoomPresetError, match="Create an account"):
        await service.create(
            owner_user_id=guest.id,
            name="Guest preset",
            settings={
                "name": "",
                "is_public": True,
                "max_players": 8,
                "rounds": 3,
                "drawing_seconds": 90,
                "custom_prompts": "",
                "custom_prompts_only": False,
                "hint_mode": "checkpoints",
                "scoring_mode": "default",
                "spectators_see_prompt": False,
                "hide_masked_prompt": False,
                "allowed_tools": ["brush"],
                "color_mode": "all",
                "prompt_list_slugs": ["missing"],
                "prompt_list_share_codes": [],
            },
        )

    await client.get("/api/auth/me")
    assert (await client.get("/api/room-presets")).status_code == 403

    owner = await register(client)
    prompt_list = await owned_prompt_list(prompt_lists, owner["id"])
    quick = await client.post(
        "/api/room-presets",
        json={
            "name": "Quick",
            "settings": settings(prompt_list.slug, customPrompts="secret prompt"),
        },
    )
    assert quick.status_code == 422

    shared = await client.post(
        "/api/room-presets",
        json={
            "name": "Shared",
            "settings": settings(prompt_list.slug, promptListShareCodes=["abcdefgh"]),
        },
    )
    assert shared.status_code == 422

    first = await client.post(
        "/api/room-presets",
        json={"name": "My setup", "settings": settings(prompt_list.slug)},
    )
    assert first.status_code == 201
    duplicate = await client.post(
        "/api/room-presets",
        json={"name": " MY  SETUP ", "settings": settings(prompt_list.slug)},
    )
    assert duplicate.status_code == 409

    other_client = AsyncClient(transport=client._transport, base_url="http://test")
    async with other_client:
        other = await register(other_client, "OtherPresetOwner")
        external_list = await owned_prompt_list(prompt_lists, other["id"], "External")
        external = await client.post(
            "/api/room-presets",
            json={"name": "External", "settings": settings(external_list.slug)},
        )
        assert external.status_code == 422
        assert (await other_client.get(f"/api/room-presets/{first.json()['id']}")).status_code == 404


async def test_deleted_prompt_list_makes_preset_visibly_unavailable(env):
    client, _, prompt_lists, _, _ = env
    owner = await register(client)
    prompt_list = await owned_prompt_list(prompt_lists, owner["id"])
    created = await client.post(
        "/api/room-presets",
        json={"name": "Fragile", "settings": settings(prompt_list.slug)},
    )
    assert created.status_code == 201
    assert await prompt_lists.delete_owned(owner["id"], prompt_list.id)

    response = await client.get(f"/api/room-presets/{created.json()['id']}")
    assert response.status_code == 422
    assert "unavailable" in response.json()["detail"]


async def test_account_may_save_at_most_twenty_presets(env):
    client, _, prompt_lists, _, factory = env
    owner = await register(client)
    prompt_list = await owned_prompt_list(prompt_lists, owner["id"])
    for number in range(20):
        response = await client.post(
            "/api/room-presets",
            json={
                "name": f"Preset {number + 1}",
                "settings": settings(prompt_list.slug),
            },
        )
        assert response.status_code == 201

    overflow = await client.post(
        "/api/room-presets",
        json={"name": "Preset 21", "settings": settings(prompt_list.slug)},
    )
    assert overflow.status_code == 422
    assert "at most 20" in overflow.json()["detail"]
    async with factory() as session:
        assert len((await session.scalars(select(RoomPreset.id))).all()) == 20
