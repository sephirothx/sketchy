"""A takedown is recorded per owner rather than searched for in revisions (#1357).

R-MOD-11 keeps a hidden word out of every list its owner saves. Until #1357
the save found hidden words by searching every revision of every list the owner
had ever held, so revisions doubled as the takedown record and had to outlive
their lists. `prompt_takedowns` is that record now: written by the decision,
removed by a decision that leaves the word up and with the account.
"""
from __future__ import annotations

from uuid import UUID

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select

from app.api.moderation import create_moderation_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import PromptTakedown
from app.domain_values import PromptContentModerationState, UserRole
from app.repositories.interfaces import PromptListEntryInput
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)
from tests.dbfixtures import create_test_db
from tests.test_prompt_content_moderation import _staff_member, published, register

HIDDEN = PromptContentModerationState.HIDDEN.value


@pytest_asyncio.fixture
async def site(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "prompt-takedown-test-secret")
    factory, engine = await create_test_db()
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    app.include_router(create_moderation_router(factory))
    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    try:
        yield new_client, factory, engine, SqlAlchemyPromptListRepository(factory)
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def _cast(site, prefix: str):
    new_client, factory, _, prompts = site
    owner_http, reporter_http, moderator_http = new_client(), new_client(), new_client()
    owner = await register(owner_http, f"{prefix}Owner")
    await register(reporter_http, f"{prefix}Reporter")
    moderator = await register(moderator_http, f"{prefix}Mod")
    await _staff_member(factory, moderator, UserRole.MODERATOR)
    listed = await prompts.create_owned(
        owner["id"], name="Reported", description="", language="en",
        prompts=(PromptListEntryInput(answer="borderline word"), PromptListEntryInput(answer="fine")),
    )
    await published(factory, listed.id)
    word = next(prompt for prompt in listed.prompts if prompt.answer == "borderline word")

    async def decide(state: str, watch=None) -> None:
        filed = await reporter_http.post(
            "/api/prompt-content-reports",
            json={"promptListId": listed.id, "promptVersionId": word.prompt_version_id,
                  "reason": "other", "details": f"Decide it {state}."},
        )
        assert filed.status_code == 201, filed.text
        if watch is not None:
            watch()
        decided = await moderator_http.patch(
            f"/api/moderation/prompt-content-reports/{filed.json()['id']}",
            json={"status": "resolved", "note": state, "moderationState": state},
        )
        assert decided.status_code == 200, decided.text

    return owner, listed, word, decide


async def _records(factory) -> set[tuple[UUID, UUID]]:
    async with factory() as session:
        return set(
            (
                await session.execute(
                    select(PromptTakedown.owner_user_id, PromptTakedown.concept_id)
                )
            ).all()
        )


async def test_a_decision_records_the_takedown_and_a_restore_removes_it(site):
    _, factory, _, _ = site
    owner, _, word, decide = await _cast(site, "Rec")

    await decide("hidden")
    assert await _records(factory) == {(UUID(owner["id"]), UUID(word.concept_id))}
    await decide("hidden")
    assert len(await _records(factory)) == 1, "a second takedown is the same record"

    await decide("active")
    assert await _records(factory) == set()


async def test_the_decision_reads_no_revision(site):
    """What the takedown is, and whom it reaches, is asked of the lists as
    they are and of the records - never of revisions, which is what lets a
    list's revisions go with it (#1362)."""
    _, _, engine, prompts = site
    owner, _, _, decide = await _cast(site, "NoRev")
    issued: list[str] = []

    def capture(_conn, _cursor, statement, *_args):
        issued.append(statement)

    def watch():
        event.listen(engine.sync_engine, "before_cursor_execute", capture)

    try:
        await decide("hidden", watch)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert any("prompt_takedowns" in statement for statement in issued)
    assert not [statement for statement in issued if "prompt_list_revision" in statement]

    again = await prompts.create_owned(
        owner["id"], name="Again", description="", language="en",
        prompts=(PromptListEntryInput(answer="borderline word"),),
    )
    assert again.prompts[0].moderation_state == HIDDEN


async def test_a_save_costs_the_same_however_many_words_were_taken_down(site):
    """R-LIST-04: a save is a fixed number of statements. The records are read
    in one statement, joined to the versions they name, whatever their count."""
    from app.api.moderation import _record_takedown
    from app.db.models import PromptVersion

    _, factory, engine, prompts = site
    new_client = site[0]
    owner = await register(new_client(), "ManyTakedowns")
    many = await prompts.create_owned(
        owner["id"], name="Many", description="", language="en",
        prompts=tuple(PromptListEntryInput(answer=f"word {n}") for n in range(30)),
    )

    async def statements_of_a_save() -> int:
        target = await prompts.get_owned(owner["id"], many.id)
        issued: list[str] = []

        def count(*_args):
            issued.append("x")

        event.listen(engine.sync_engine, "before_cursor_execute", count)
        try:
            await prompts.update_owned(
                owner["id"], many.id, expected_version=target.version, name="Many",
                description="",
                prompts=(
                    *(
                        PromptListEntryInput(answer=p.answer, concept_id=p.concept_id)
                        for p in target.prompts
                    ),
                    PromptListEntryInput(answer=f"new {target.version}"),
                ),
            )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count)
        return len(issued)

    async def hide(count: int, skip: int) -> None:
        async with factory() as session, session.begin():
            for entry in many.prompts[skip:skip + count]:
                version = await session.get(PromptVersion, UUID(entry.prompt_version_id))
                version.moderation_state = HIDDEN
                await _record_takedown(
                    session, concept_id=version.concept_id, decision=HIDDEN,
                    reported_owner_user_id=None,
                )

    await hide(1, 0)
    few = await statements_of_a_save()
    await hide(20, 1)
    lots = await statements_of_a_save()
    assert len(await _records(factory)) == 21
    assert few == lots


async def test_a_released_takedown_takes_the_spellings_it_kept(site):
    """A row keeps its word's versions from the orphan collection, and the
    sweep only looks at versions the revisions it deletes named. A version kept
    by a row after its revisions went is a candidate nowhere else, so erasing
    the account used to leave the hidden text for good (#1357 review)."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func

    from app.db.models import PromptVersion
    from app.services.prompt_reclaim import (
        reclaim_retired_prompt_lists,
        reclaim_superseded_revisions,
    )
    from tests.test_prompt_content_moderation import PASSWORD
    from tests.test_superseded_revisions import LONG_AGO, _age, _revisions

    new_client, factory, _, prompts = site
    owner_http = new_client()
    owner = await register(owner_http, "Respeller")
    listed = await prompts.create_owned(
        owner["id"], name="Respelled", description="", language="en",
        prompts=(PromptListEntryInput(answer="offensive prompt"), PromptListEntryInput(answer="fine")),
    )
    word = next(p for p in listed.prompts if p.answer == "offensive prompt")
    fine = next(p for p in listed.prompts if p.answer == "fine")
    async with factory() as session, session.begin():
        from tests.test_prompt_content_moderation import taken_down

        await taken_down(session, await session.get(PromptVersion, UUID(word.prompt_version_id)))
    current = listed
    for spelling in ("offensive prompt!", "offensive  prompt?"):
        current = await prompts.update_owned(
            owner["id"], listed.id, expected_version=current.version, name="Respelled",
            description="",
            prompts=(
                PromptListEntryInput(answer=spelling, concept_id=word.concept_id),
                PromptListEntryInput(answer="fine", concept_id=fine.concept_id),
            ),
        )
    await _age(factory, (await _revisions(factory, listed.id))[:-1], LONG_AGO)
    await reclaim_superseded_revisions(factory)

    async def spellings() -> int:
        async with factory() as session:
            return int(
                await session.scalar(
                    select(func.count(PromptVersion.id)).where(
                        PromptVersion.concept_id == UUID(word.concept_id)
                    )
                )
            )

    assert await spellings() == 3, "the row keeps every spelling the save compares against"

    deleted = await owner_http.request("DELETE", "/api/auth/account", json={"password": PASSWORD})
    assert deleted.status_code == 200, deleted.text
    await reclaim_retired_prompt_lists(factory, now=datetime.now(timezone.utc) + timedelta(days=2))
    assert await spellings() == 0
