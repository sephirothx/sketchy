"""A player's own prompt lists: bounded per account, and cheap to read (#1236).

The own-list routes had no limit, and each call on a list at the ceiling (500
prompts of 20 aliases) built a ~21,000-object ORM graph, up to four times per
save. One registered account could hold the only event loop and write
gigabytes an hour of permanent rows.
"""
from __future__ import annotations

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.api.errors import install_refusal_handler
from app.api.prompt_lists import create_prompt_list_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.sessions import COOKIE_NAME, create_session
from app.repositories.interfaces import PromptListEntryInput
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)

from tests.dbfixtures import create_test_db


@pytest_asyncio.fixture
async def site(monkeypatch):
    monkeypatch.setenv("PROMPT_LIST_SAVE_LIMIT", "3")
    monkeypatch.setenv("PROMPT_LIST_CREATE_LIMIT", "3")
    monkeypatch.setenv("PROMPT_LIST_READ_LIMIT", "4")
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    prompts = SqlAlchemyPromptListRepository(factory)
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_prompt_list_router(prompts, users, factory))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http, users, factory, prompts, engine
    await engine.dispose()


async def signed_in(http, users, factory, name: str) -> str:
    account = await users.create_anonymous(name)
    account = await users.claim_account(account.id, name, "test-hash")
    issued = await create_session(factory, user_id=account.id, device_label="Test")
    http.cookies.set(COOKIE_NAME, issued.token)
    return account.id


async def test_saves_are_bounded_per_account(site):
    http, users, factory, *_ = site
    await signed_in(http, users, factory, "Saver")
    created = (await http.post(
        "/api/prompt-lists/mine", json={"name": "Mine", "prompts": [{"prompt": "otter"}]}
    )).json()

    codes = []
    version = created["version"]
    for index in range(4):
        response = await http.put(
            f"/api/prompt-lists/mine/{created['id']}",
            json={"name": "Mine", "expectedVersion": version, "prompts": [{"prompt": f"otter{index}"}]},
        )
        codes.append(response.status_code)
        if response.status_code == 200:
            version = response.json()["version"]
    assert codes == [200, 200, 200, 429]
    assert response.json()["errorCode"] == "too_many_attempts"


async def test_creates_duplicates_and_deletes_share_one_daily_budget(site):
    """Create-then-delete frees the slot at once, so the churn is what is counted."""
    http, users, factory, *_ = site
    await signed_in(http, users, factory, "Churner")
    first = (await http.post(
        "/api/prompt-lists/mine", json={"name": "One", "prompts": [{"prompt": "otter"}]}
    )).json()
    duplicate = await http.post(f"/api/prompt-lists/mine/{first['id']}/duplicate", json={"name": "Two"})
    deleted = await http.delete(f"/api/prompt-lists/mine/{first['id']}")
    refused = await http.post(
        "/api/prompt-lists/mine", json={"name": "Three", "prompts": [{"prompt": "otter"}]}
    )

    assert duplicate.status_code == 201
    assert deleted.status_code == 204
    assert refused.status_code == 429


async def test_one_account_s_budget_is_not_another_s(site):
    http, users, factory, *_ = site
    await signed_in(http, users, factory, "First")
    for index in range(3):
        await http.post("/api/prompt-lists/mine", json={"name": f"L{index}", "prompts": [{"prompt": "otter"}]})
    await signed_in(http, users, factory, "Second")
    response = await http.post("/api/prompt-lists/mine", json={"name": "Mine", "prompts": [{"prompt": "otter"}]})
    assert response.status_code == 201


async def test_reading_one_list_is_bounded_too(site):
    http, users, factory, *_ = site
    await signed_in(http, users, factory, "Reader")
    created = (await http.post(
        "/api/prompt-lists/mine", json={"name": "Mine", "prompts": [{"prompt": "otter"}]}
    )).json()
    codes = [(await http.get(f"/api/prompt-lists/mine/{created['id']}")).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 200, 429]


def _entries(prompts: int, aliases: int) -> list[PromptListEntryInput]:
    return [
        PromptListEntryInput(
            answer=f"prompt{index}",
            aliases=tuple(f"prompt{index}alias{alias}" for alias in range(aliases)),
        )
        for index in range(prompts)
    ]


async def test_reading_a_list_costs_the_same_few_statements_whatever_it_holds(site):
    """Thirty statements for a list at the ceiling before; four now, flat."""
    http, users, factory, prompts, engine = site
    owner = await signed_in(http, users, factory, "Counter")
    small = await prompts.create_owned(owner, name="Small", description="", language="en", prompts=_entries(2, 1))
    large = await prompts.create_owned(owner, name="Large", description="", language="en", prompts=_entries(120, 8))
    issued = []

    def count(*_args, **_kwargs):
        issued.append(1)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        read_small = await prompts.get_owned(owner, small.id)
        small_statements = len(issued)
        issued.clear()
        read_large = await prompts.get_owned(owner, large.id)
        large_statements = len(issued)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)

    assert small_statements == large_statements <= 5
    assert [entry.answer for entry in read_large.prompts] == [f"prompt{index}" for index in range(120)]
    assert read_large.prompts[7].aliases == tuple(sorted(f"prompt7alias{alias}" for alias in range(8)))
    assert read_small.prompt_count == 2


async def test_a_save_that_lost_the_race_is_refused_before_its_content_is_folded(site, monkeypatch):
    http, users, factory, prompts, engine = site
    owner = await signed_in(http, users, factory, "Racer")
    created = await prompts.create_owned(owner, name="Race", description="", language="en", prompts=_entries(3, 1))

    folded = []
    original = SqlAlchemyPromptListRepository._clean_owned_entries

    def watching(entries, *, language):
        folded.append(len(entries))
        return original(entries, language=language)

    monkeypatch.setattr(SqlAlchemyPromptListRepository, "_clean_owned_entries", staticmethod(watching))
    from app.repositories.interfaces import PromptListConflictError

    try:
        await prompts.update_owned(
            owner, created.id, expected_version=created.version + 5, name="Race",
            description="", prompts=_entries(3, 1),
        )
    except PromptListConflictError:
        pass
    else:  # pragma: no cover - the assertion below says what went wrong
        raise AssertionError("a stale version was saved")
    assert folded == []


async def test_a_list_is_read_as_one_revision_even_when_a_save_lands_mid_read(site, monkeypatch):
    """#1291 review: the entries were read at the version the list's row gave,
    the tags at whichever revision was current by the next statement, so a
    save committed between the two handed the editor one revision's prompts
    beside the next one's tags."""
    from sqlalchemy import update

    from app.db.models import PromptList

    http, users, factory, prompts, engine = site
    owner = await signed_in(http, users, factory, "Reader")
    created = await prompts.create_owned(
        owner, name="Tagged", description="", language="en", prompts=_entries(2, 0), tags=["animals"],
    )
    await prompts.update_owned(
        owner, created.id, expected_version=created.version, name="Tagged",
        description="", prompts=_entries(2, 0), tags=["food-and-drink"],
    )
    # Back to revision one as the list's row says it, and the second save
    # "lands" between reading that row and reading the tags.
    async with factory() as session, session.begin():
        await session.execute(update(PromptList).values(version=created.version))
    original = SqlAlchemyPromptListRepository._revision_entries

    async def a_save_lands(session, prompt_list_id, version):
        entries = await original(session, prompt_list_id, version)
        # Another transaction's commit: the row changes, this session's copy
        # of it does not.
        await session.execute(
            update(PromptList).values(version=created.version + 1)
            .execution_options(synchronize_session=False)
        )
        return entries

    monkeypatch.setattr(SqlAlchemyPromptListRepository, "_revision_entries", staticmethod(a_save_lands))

    read = await prompts.get_owned(owner, created.id)

    assert (read.version, read.tags) == (created.version, ("animals",))
