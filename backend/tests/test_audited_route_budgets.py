"""Player routes that append permanent audit rows are bounded, and a no-op writes none (#1241).

`audit_events` is append-only for the application role and has no sweep, so
nothing can ever remove what an abuser writes there. Blocking and unblocking
one pair, re-picking a doodle, removing a picture that is not there and
withdrawing a list that was never out each appended a row per call, with no
limit: 237 rows a second from one guest.
"""
from __future__ import annotations

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api import avatars as avatar_api
from app.api import user_blocks
from app.api.errors import install_refusal_handler
from app.db.models import AuditEvent
from app.repositories.interfaces import PromptListEntryInput
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository

from tests.test_avatars import env as avatar_env  # noqa: F401 - fixture
from tests.test_avatars import register
from tests.test_user_blocks import env as blocks_env  # noqa: F401 - fixture


async def audit_rows(factory, event_type: str) -> int:
    async with factory() as session:
        return await session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == event_type)
        )


# --- blocks -----------------------------------------------------------------------


@pytest_asyncio.fixture
async def small_block_budget(monkeypatch):
    monkeypatch.setattr(user_blocks, "BLOCK_CHANGES_PER_HOUR", 4)


async def test_blocking_and_unblocking_is_bounded_per_account(small_block_budget, blocks_env):  # noqa: F811
    new_client, *_ = blocks_env
    blocker, target_http = new_client(), new_client()
    await register(blocker, "Cycler")
    target = await register(target_http, "Cycled")
    codes = []
    for _ in range(3):
        codes.append((await blocker.post("/api/users/me/blocks", json={"userId": target["id"]})).status_code)
        codes.append((await blocker.delete(f"/api/users/me/blocks/{target['id']}")).status_code)
    assert codes[:4] == [201, 204, 201, 204]
    assert codes[4:] == [429, 429]


# --- pictures and doodles -----------------------------------------------------------


async def test_picking_the_doodle_already_worn_writes_nothing_and_tells_nobody(avatar_env):  # noqa: F811
    new_client, factory = avatar_env
    http = new_client()
    await register(http, "Doodler")
    first = await http.put("/api/users/me/avatar/doodle", json={"name": "kite"})
    assert first.status_code == 200
    new_client.changed.reset_mock()
    rows = await audit_rows(factory, "avatar.doodle_chosen")

    again = await http.put("/api/users/me/avatar/doodle", json={"name": "kite"})

    assert again.status_code == 200 and again.json() == first.json()
    assert await audit_rows(factory, "avatar.doodle_chosen") == rows
    new_client.changed.assert_not_awaited()


async def test_removing_a_picture_that_is_not_there_writes_nothing(avatar_env):  # noqa: F811
    new_client, factory = avatar_env
    http = new_client()
    await register(http, "Bare")
    async with factory() as session, session.begin():
        from uuid import UUID

        from app.db.models import User

        me = (await http.get("/api/auth/me")).json()
        (await session.get(User, UUID(me["id"]))).avatar_key = None
    new_client.changed.reset_mock()

    removed = await http.delete("/api/users/me/avatar")

    assert removed.status_code == 200
    assert await audit_rows(factory, "avatar.removed") == 0
    new_client.changed.assert_not_awaited()


async def test_doodle_changes_are_bounded_per_account(avatar_env, monkeypatch):  # noqa: F811
    new_client, factory = avatar_env
    http = new_client()
    await register(http, "Flicker")
    codes = []
    worn = (await http.put("/api/users/me/avatar/doodle", json={"name": "kite"})).json()["avatarKey"]
    for _ in range(avatar_api.AVATAR_CHANGE_LIMIT + 3):
        # Always a doodle other than the one worn, so every call is a change.
        name = "ghost" if worn == "doodle:kite" else "kite"
        response = await http.put("/api/users/me/avatar/doodle", json={"name": name})
        codes.append(response.status_code)
        if response.status_code == 200:
            worn = response.json()["avatarKey"]
    # The first pick above may or may not have been a change (a new account
    # wears a random doodle), so the ceiling falls here or one call earlier.
    assert codes.count(429) in (3, 4)
    assert codes[-3:] == [429] * 3
    assert set(codes[: avatar_api.AVATAR_CHANGE_LIMIT - 1]) == {200}


# --- withdrawing a list -------------------------------------------------------------


async def test_withdrawing_a_list_that_was_never_out_writes_nothing(monkeypatch):
    from app.auth.middleware import SessionAuthMiddleware
    from app.api.prompt_lists import create_prompt_list_router
    from app.auth.sessions import COOKIE_NAME, create_session
    from app.repositories.sqlalchemy import SqlAlchemyUserRepository
    from tests.dbfixtures import create_test_db

    monkeypatch.setenv("IP_HASH_SECRET", "unpublish-test-secret")
    monkeypatch.setenv("PROMPT_LIST_UNPUBLISH_LIMIT", "3")
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    prompts = SqlAlchemyPromptListRepository(factory)
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_prompt_list_router(prompts, users, factory))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            account = await users.create_anonymous("Lister")
            account = await users.claim_account(account.id, "Lister", "hash")
            issued = await create_session(factory, user_id=account.id, device_label="Test")
            http.cookies.set(COOKIE_NAME, issued.token)
            created = await prompts.create_owned(
                account.id, name="Mine", description="", language="en",
                prompts=[PromptListEntryInput(answer="otter")],
            )
            codes = [
                (await http.post(f"/api/prompt-lists/mine/{created.id}/unpublish")).status_code
                for _ in range(4)
            ]
            assert codes == [200, 200, 200, 429]
            assert await audit_rows(factory, "prompt_list.unpublished") == 0
    finally:
        await engine.dispose()
