"""The registered-owner REST workflow for persistent prompt lists."""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.prompt_lists import create_prompt_list_router, share_limiter
from app.auth.middleware import SessionAuthMiddleware
from app.auth.sessions import COOKIE_NAME, create_session
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)

from tests.dbfixtures import create_test_db

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def env():
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    prompts = SqlAlchemyPromptListRepository(factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_prompt_list_router(prompts, users))
    share_limiter.reset()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http, users, factory
    await engine.dispose()


async def sign_in(http, factory, user_id: str) -> None:
    issued = await create_session(factory, user_id=user_id, device_label="Test")
    http.cookies.set(COOKIE_NAME, issued.token)


async def test_guests_cannot_persist_quick_prompts(env):
    http, users, factory = env
    guest = await users.create_anonymous("Guest")
    await sign_in(http, factory, guest.id)

    response = await http.post(
        "/api/prompt-lists/mine",
        json={"name": "Nope", "prompts": [{"prompt": "apple"}]},
    )

    assert response.status_code == 403
    assert "Create an account" in response.json()["detail"]


async def test_owner_can_create_revise_reuse_and_share_a_list(env):
    http, users, factory = env
    account = await users.create_anonymous("Owner")
    account = await users.claim_account(account.id, "Owner", "test-hash")
    await sign_in(http, factory, account.id)

    created_response = await http.post(
        "/api/prompt-lists/mine",
        json={
            "name": "Animals",
            "language": "en",
            "visibility": "private",
            "prompts": [{"prompt": "red panda"}, {"prompt": "otter"}],
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["version"] == 1
    assert created["promptCount"] == 2
    assert created["shareCode"] is None
    assert (
        await http.get(f"/api/prompt-lists/{created['slug']}/prompt-stats")
    ).status_code == 404

    mine = (await http.get("/api/prompt-lists/mine")).json()
    assert [(item["name"], item["promptCount"]) for item in mine] == [
        ("Animals", 2)
    ]
    detail = (
        await http.get(f"/api/prompt-lists/mine/{created['id']}")
    ).json()
    panda = detail["prompts"][0]

    updated_response = await http.put(
        f"/api/prompt-lists/mine/{created['id']}",
        json={
            "expectedVersion": 1,
            "name": "Animals",
            "description": "Shared with friends",
            "visibility": "unlisted",
            "prompts": [
                {
                    "conceptId": panda["conceptId"],
                    "prompt": "giant panda",
                    "aliases": ["panda"],
                },
                {"prompt": "capybara"},
            ],
        },
    )
    assert updated_response.status_code == 200
    updated = updated_response.json()
    assert updated["version"] == 2
    assert updated["shareCode"]

    stale = await http.put(
        f"/api/prompt-lists/mine/{created['id']}",
        json={
            "expectedVersion": 1,
            "name": "Stale",
            "visibility": "private",
            "prompts": [{"prompt": "apple"}],
        },
    )
    assert stale.status_code == 409

    http.cookies.clear()
    shared = await http.post(
        "/api/prompt-lists/shared", json={"code": updated["shareCode"]}
    )
    assert shared.status_code == 200
    assert shared.json()["slug"] == created["slug"]
    assert [prompt["prompt"] for prompt in shared.json()["prompts"]] == [
        "giant panda",
        "capybara",
    ]
    assert all("promptVersionId" in prompt for prompt in shared.json()["prompts"])
    assert "shareCode" not in shared.json()
    assert (await http.get("/api/prompt-lists")).json() == []
