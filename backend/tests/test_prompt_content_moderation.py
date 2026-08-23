"""Post-moderation reports and reversible list/prompt takedowns."""
from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.moderation import create_moderation_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import (
    AuditEvent,
    Base,
    PromptContentReport,
    PromptList,
    PromptVersion,
    User,
)
from app.db import create_db_engine
from app.domain_values import UserRole
from app.repositories.interfaces import PromptListEntryInput, PromptListSelectionError
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)

pytestmark = pytest.mark.asyncio
PASSWORD = "a-good-password"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "prompt-moderation-test-secret")
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    users = SqlAlchemyUserRepository(factory)
    prompts = SqlAlchemyPromptListRepository(factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(users, factory))
    app.include_router(create_moderation_router(factory))
    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )
        clients.append(client)
        return client

    try:
        yield new_client, factory, prompts
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def register(client: AsyncClient, username: str) -> dict:
    assert (await client.get("/api/auth/me")).status_code == 200
    response = await client.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()


async def test_exact_prompt_and_list_reports_drive_audited_takedowns(env):
    new_client, factory, prompts = env
    owner_http = new_client()
    reporter_http = new_client()
    moderator_http = new_client()
    owner = await register(owner_http, "PromptOwner")
    # Registering is what authenticates reporter_http; the payload is unused.
    await register(reporter_http, "PromptReporter")
    moderator = await register(moderator_http, "PromptModerator")
    async with factory() as session:
        async with session.begin():
            reviewer = await session.get(User, UUID(moderator["id"]))
            assert reviewer is not None
            reviewer.role = UserRole.MODERATOR.value

    prompt_list = await prompts.create_owned(
        owner["id"],
        name="Shared trouble",
        description="",
        language="en",
        visibility="unlisted",
        prompts=(
            PromptListEntryInput(answer="offensive prompt"),
            PromptListEntryInput(answer="safe prompt"),
        ),
    )
    reported_prompt = prompt_list.prompts[0]

    self_report = await owner_http.post(
        "/api/prompt-content-reports",
        json={
            "promptListId": prompt_list.id,
            "shareCode": prompt_list.share_code,
            "reason": "other",
            "details": "self",
        },
    )
    assert self_report.status_code == 422
    no_capability = await reporter_http.post(
        "/api/prompt-content-reports",
        json={
            "promptListId": prompt_list.id,
            "reason": "spam",
            "details": "No code",
        },
    )
    assert no_capability.status_code == 404

    submitted = await reporter_http.post(
        "/api/prompt-content-reports",
        headers={"x-request-id": "019c2000-0000-7000-8000-000000000001"},
        json={
            "promptListId": prompt_list.id,
            "promptVersionId": reported_prompt.prompt_version_id,
            "shareCode": prompt_list.share_code,
            "reason": "hateful_or_abusive",
            "details": "This exact prompt contains abuse.",
        },
    )
    assert submitted.status_code == 201
    report_id = submitted.json()["id"]

    listing = await moderator_http.get(
        "/api/moderation/prompt-content-reports?status=pending"
    )
    assert listing.status_code == 200
    evidence = listing.json()["reports"][0]
    assert evidence["targetType"] == "prompt"
    assert evidence["listName"] == "Shared trouble"
    assert evidence["prompt"] == "offensive prompt"
    assert evidence["details"] == "This exact prompt contains abuse."

    resolved = await moderator_http.patch(
        f"/api/moderation/prompt-content-reports/{report_id}",
        headers={"x-request-id": "019c2000-0000-7000-8000-000000000002"},
        json={
            "status": "resolved",
            "note": "Confirmed and hidden.",
            "moderationState": "hidden",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["moderationState"] == "hidden"
    assert (
        await moderator_http.patch(
            f"/api/moderation/prompt-content-reports/{report_id}",
            json={
                "status": "dismissed",
                "note": "Overwrite",
            },
        )
    ).status_code == 409

    selection = await prompts.resolve_selection(
        [prompt_list.slug], share_codes=(prompt_list.share_code,)
    )
    assert selection.prompts == ("safe prompt",)

    async with factory() as session:
        hidden = await session.get(
            PromptVersion, UUID(reported_prompt.prompt_version_id)
        )
        assert hidden is not None
        assert hidden.moderation_state == "hidden"
        assert hidden.moderated_by_user_id == UUID(moderator["id"])
        assert hidden.moderated_at is not None
        events = list(
            (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.event_type.like("prompt_content_report.%")
                    )
                )
            ).all()
        )
        assert {event.event_type for event in events} == {
            "prompt_content_report.submitted",
            "prompt_content_report.resolved",
        }
        assert all(event.ip_hash and len(event.ip_hash) == 64 for event in events)

    list_report = await reporter_http.post(
        "/api/prompt-content-reports",
        json={
            "promptListId": prompt_list.id,
            "shareCode": prompt_list.share_code,
            "reason": "spam",
            "details": "The whole list is spam.",
        },
    )
    list_review = await moderator_http.patch(
        f"/api/moderation/prompt-content-reports/{list_report.json()['id']}",
        json={
            "status": "resolved",
            "note": "List hidden.",
            "moderationState": "hidden",
        },
    )
    assert list_review.status_code == 200
    with pytest.raises(PromptListSelectionError):
        await prompts.resolve_selection(
            [prompt_list.slug], share_codes=(prompt_list.share_code,)
        )

    async with factory() as session:
        stored_list = await session.get(PromptList, UUID(prompt_list.id))
        assert stored_list is not None
        assert stored_list.moderation_state == "hidden"
        assert stored_list.moderated_by_user_id == UUID(moderator["id"])


async def test_report_snapshots_survive_owner_deletion(env):
    new_client, factory, prompts = env
    owner_http = new_client()
    reporter_http = new_client()
    owner = await register(owner_http, "DeletedOwner")
    await register(reporter_http, "EvidenceReporter")
    prompt_list = await prompts.create_owned(
        owner["id"],
        name="Evidence list",
        description="",
        language="en",
        visibility="unlisted",
        prompts=(PromptListEntryInput(answer="reported prompt"),),
    )
    response = await reporter_http.post(
        "/api/prompt-content-reports",
        json={
            "promptListId": prompt_list.id,
            "promptVersionId": prompt_list.prompts[0].prompt_version_id,
            "shareCode": prompt_list.share_code,
            "reason": "inappropriate",
            "details": "Retain this evidence.",
        },
    )
    assert response.status_code == 201
    deleted = await owner_http.request(
        "DELETE", "/api/auth/account", json={"password": PASSWORD}
    )
    assert deleted.status_code == 200

    async with factory() as session:
        report = await session.get(PromptContentReport, UUID(response.json()["id"]))
        assert report is not None
        assert report.prompt_list_id is None
        assert report.prompt_version_id is None
        assert report.reported_owner_user_id == UUID(owner["id"])
        assert report.list_name_snapshot == "Evidence list"
        assert report.prompt_snapshot == "reported prompt"
        assert report.details == "Retain this evidence."


async def test_the_same_content_cannot_be_reported_twice_while_it_waits(env):
    """A second open report on the same target adds no evidence, only noise."""

    new_client, factory, prompts = env
    owner_http = new_client()
    reporter_http = new_client()
    moderator_http = new_client()
    owner = await register(owner_http, "DupeOwner")
    await register(reporter_http, "DupeReporter")
    moderator = await register(moderator_http, "DupeModerator")
    async with factory() as session:
        async with session.begin():
            reviewer = await session.get(User, UUID(moderator["id"]))
            reviewer.role = UserRole.MODERATOR.value

    prompt_list = await prompts.create_owned(
        owner["id"],
        name="Reported twice",
        description="",
        language="en",
        visibility="unlisted",
        prompts=(
            PromptListEntryInput(answer="first prompt"),
            PromptListEntryInput(answer="second prompt"),
        ),
    )
    body = {
        "promptListId": prompt_list.id,
        "shareCode": prompt_list.share_code,
        "reason": "spam",
        "details": "Reporting the list itself.",
    }

    first = await reporter_http.post("/api/prompt-content-reports", json=body)
    assert first.status_code == 201

    again = await reporter_http.post("/api/prompt-content-reports", json=body)
    assert again.status_code == 409
    assert "already reported" in again.json()["detail"]

    # A specific prompt inside the same list is a different target, so it is
    # still reportable while the list-level report is open.
    prompt_report = await reporter_http.post(
        "/api/prompt-content-reports",
        json={**body, "promptVersionId": prompt_list.prompts[0].prompt_version_id},
    )
    assert prompt_report.status_code == 201

    async with factory() as session:
        open_reports = await session.scalar(
            select(func.count(PromptContentReport.id)).where(
                PromptContentReport.status == "pending"
            )
        )
    assert open_reports == 2

    # Once a moderator has dealt with it, the same reporter may raise it again:
    # that is a new incident rather than a repeat of an unread one.
    await moderator_http.patch(
        f"/api/moderation/prompt-content-reports/{first.json()['id']}",
        json={"status": "dismissed", "note": "Not actionable."},
    )
    after_review = await reporter_http.post("/api/prompt-content-reports", json=body)
    assert after_review.status_code == 201
