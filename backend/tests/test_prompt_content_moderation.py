"""Post-moderation reports and reversible list/prompt takedowns."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.moderation import create_moderation_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import (
    AuditEvent,
    PromptContentReport,
    PromptList,
    PromptVersion,
    User,
)
from app.domain_values import UserRole
from app.services.prompt_reclaim import reclaim_retired_prompt_lists
from app.repositories.interfaces import PromptListEntryInput, PromptListSelectionError
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)

from tests.dbfixtures import create_test_db

from tests.staffauth import mark_staff_ready

PASSWORD = "a-good-password"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "prompt-moderation-test-secret")
    factory, engine = await create_test_db()
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


async def published(factory, prompt_list_id: str) -> None:
    """Put a list where a reporter can see it: only a published list can be
    seen by anyone but its owner, so only a published list is reportable."""
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(prompt_list_id))
            row.visibility = "public"
            row.published_at = datetime.now(timezone.utc)


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
    await mark_staff_ready(factory, reviewer.id)

    prompt_list = await prompts.create_owned(
        owner["id"],
        name="Shared trouble",
        description="",
        language="en",
        prompts=(
            PromptListEntryInput(answer="offensive prompt"),
            PromptListEntryInput(answer="safe prompt"),
        ),
    )
    reported_prompt = prompt_list.prompts[0]

    unseen = await reporter_http.post(
        "/api/prompt-content-reports",
        json={
            "promptListId": prompt_list.id,
            "reason": "spam",
            "details": "Still private",
        },
    )
    assert unseen.status_code == 404
    await published(factory, prompt_list.id)

    self_report = await owner_http.post(
        "/api/prompt-content-reports",
        json={
            "promptListId": prompt_list.id,
            "reason": "other",
            "details": "self",
        },
    )
    assert self_report.status_code == 422

    submitted = await reporter_http.post(
        "/api/prompt-content-reports",
        headers={"x-request-id": "019c2000-0000-7000-8000-000000000001"},
        json={
            "promptListId": prompt_list.id,
            "promptVersionId": reported_prompt.prompt_version_id,
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
    evidence = listing.json()["incidents"][0]
    assert evidence["targetType"] == "prompt"
    assert evidence["listName"] == "Shared trouble"
    assert evidence["prompt"] == "offensive prompt"
    # The target is stated once above the complaints; the words are each
    # reporter's own (#620).
    assert evidence["reporterCount"] == 1
    assert evidence["reports"][0]["details"] == "This exact prompt contains abuse."

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

    selection = await prompts.resolve_selection([prompt_list.slug])
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
        # The owner rides along in target_user_id, but a takedown is about the
        # content, and until the pair existed the ledger could not say which.
        assert {(event.target_type, event.target_id) for event in events} == {
            ("prompt_version", reported_prompt.prompt_version_id)
        }

    list_report = await reporter_http.post(
        "/api/prompt-content-reports",
        json={
            "promptListId": prompt_list.id,
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
        await prompts.resolve_selection([prompt_list.slug])

    async with factory() as session:
        stored_list = await session.get(PromptList, UUID(prompt_list.id))
        assert stored_list is not None
        assert stored_list.moderation_state == "hidden"
        assert stored_list.moderated_by_user_id == UUID(moderator["id"])
        # Same owner, same event types, different subject: a report against the
        # whole list names the list rather than the prompt inside it.
        list_events = list(
            (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.target_type == "prompt_list"
                    )
                )
            ).all()
        )
        assert {event.event_type for event in list_events} == {
            "prompt_content_report.submitted",
            "prompt_content_report.resolved",
        }
        assert {event.target_id for event in list_events} == {prompt_list.id}


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
        prompts=(PromptListEntryInput(answer="reported prompt"),),
    )
    await published(factory, prompt_list.id)
    response = await reporter_http.post(
        "/api/prompt-content-reports",
        json={
            "promptListId": prompt_list.id,
            "promptVersionId": prompt_list.prompts[0].prompt_version_id,
            "reason": "inappropriate",
            "details": "Retain this evidence.",
        },
    )
    assert response.status_code == 201
    deleted = await owner_http.request(
        "DELETE", "/api/auth/account", json={"password": PASSWORD}
    )
    assert deleted.status_code == 200

    def _snapshots_intact(report):
        assert report.reported_owner_user_id == UUID(owner["id"])
        assert report.list_name_snapshot == "Evidence list"
        assert report.prompt_snapshot == "reported prompt"
        assert report.details == "Retain this evidence."

    # The list is retired with the account (#605): the row stays as a
    # tombstone until the sweep reclaims it, and the report still points at
    # it and at the version it cites.
    async with factory() as session:
        report = await session.get(PromptContentReport, UUID(response.json()["id"]))
        assert report is not None
        assert report.prompt_list_id == UUID(prompt_list.id)
        assert report.prompt_version_id == UUID(prompt_list.prompts[0].prompt_version_id)
        retired = await session.get(PromptList, UUID(prompt_list.id))
        assert retired.deleted_at is not None and retired.name == "Deleted list"
        _snapshots_intact(report)

    # Nothing pins the list, so the sweep drops it and the FK detaches; the
    # version the report cites is kept for the report.
    await reclaim_retired_prompt_lists(
        factory, now=datetime.now(timezone.utc) + timedelta(days=2)
    )
    async with factory() as session:
        report = await session.get(PromptContentReport, UUID(response.json()["id"]))
        assert report.prompt_list_id is None
        assert report.prompt_version_id == UUID(prompt_list.prompts[0].prompt_version_id)
        _snapshots_intact(report)


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
    await mark_staff_ready(factory, reviewer.id)

    prompt_list = await prompts.create_owned(
        owner["id"],
        name="Reported twice",
        description="",
        language="en",
        prompts=(
            PromptListEntryInput(answer="first prompt"),
            PromptListEntryInput(answer="second prompt"),
        ),
    )
    await published(factory, prompt_list.id)
    body = {
        "promptListId": prompt_list.id,
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


async def test_a_content_report_may_be_sent_without_words(env):
    """Details are optional on every report route (R-MOD-01): the list or
    prompt is the complaint, and its snapshot travels with the report. An
    empty detail is stored empty, never padded with words nobody wrote."""
    new_client, factory, prompts = env
    owner_http = new_client()
    reporter_http = new_client()
    owner = await register(owner_http, "QuietOwner")
    await register(reporter_http, "QuietReporter")
    prompt_list = await prompts.create_owned(
        owner["id"],
        name="Said nothing",
        description="",
        language="en",
        prompts=(PromptListEntryInput(answer="a prompt"),),
    )
    await published(factory, prompt_list.id)

    sent = await reporter_http.post(
        "/api/prompt-content-reports",
        json={"promptListId": prompt_list.id, "reason": "inappropriate"},
    )
    assert sent.status_code == 201
    async with factory() as session:
        stored = await session.get(PromptContentReport, UUID(sent.json()["id"]))
    assert stored is not None and stored.details == ""


async def test_content_reports_about_one_target_are_one_incident(env):
    """Prompt content groups on the target, which already names the incident:
    a list or an exact prompt version is a durable thing rather than a moment
    in a room, so there is no place or time to bound it with (#620).

    One decision hides the content once and closes every complaint about it -
    deciding them one at a time would leave the rest asking about something
    already settled - and the closed stream shows the one decision it was.
    """
    new_client, factory, prompts = env
    owner_http, moderator_http = new_client(), new_client()
    owner = await register(owner_http, "IncOwner")
    moderator = await register(moderator_http, "IncModerator")
    async with factory() as session:
        async with session.begin():
            reviewer = await session.get(User, UUID(moderator["id"]))
            assert reviewer is not None
            reviewer.role = UserRole.MODERATOR.value
    await mark_staff_ready(factory, reviewer.id)

    prompt_list = await prompts.create_owned(
        owner["id"],
        name="Trouble again",
        description="",
        language="en",
        prompts=(PromptListEntryInput(answer="the reported prompt"),),
    )
    await published(factory, prompt_list.id)

    report_ids = []
    for index in range(3):
        reporter = new_client()
        await register(reporter, f"IncRep{index}")
        response = await reporter.post(
            "/api/prompt-content-reports",
            json={
                "promptListId": prompt_list.id,
                "reason": "inappropriate" if index else "hateful_or_abusive",
                "details": f"Complaint {index}.",
            },
        )
        assert response.status_code == 201, response.text
        report_ids.append(response.json()["id"])

    queue = (
        await moderator_http.get(
            "/api/moderation/prompt-content-reports?status=pending"
        )
    ).json()
    assert queue["total"] == 1, "one target, one incident"
    [incident] = queue["incidents"]
    assert incident["reporterCount"] == 3
    assert incident["targetType"] == "list"
    assert incident["listName"] == "Trouble again"
    # The distinct reasons, in the order first given: three reporters, two
    # words for it.
    assert incident["reasons"] == ["hateful_or_abusive", "inappropriate"]
    # Each complaint keeps its own words.
    assert [row["details"] for row in incident["reports"]] == [
        "Complaint 0.",
        "Complaint 1.",
        "Complaint 2.",
    ]

    # Decided from the last complaint, not the one that names the incident.
    decided = await moderator_http.patch(
        f"/api/moderation/prompt-content-reports/{report_ids[2]}",
        json={
            "status": "resolved",
            "note": "Confirmed and hidden.",
            "moderationState": "hidden",
        },
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["reporterCount"] == 3
    assert decided.json()["moderationState"] == "hidden"

    assert (
        await moderator_http.get(
            "/api/moderation/prompt-content-reports?status=pending"
        )
    ).json()["incidents"] == []

    async with factory() as session:
        rows = (
            await session.scalars(
                select(PromptContentReport).where(
                    PromptContentReport.id.in_([UUID(row) for row in report_ids])
                )
            )
        ).all()
        assert {row.status for row in rows} == {"resolved"}
        assert {row.resolution_moderation_state for row in rows} == {"hidden"}
        # One action, so one group id - and one audit entry each, naming it.
        assert len({row.decision_group_id for row in rows}) == 1
        events = (
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.event_type == "prompt_content_report.resolved"
                )
            )
        ).all()
        assert len(events) == 3
        assert {event.details["decision_group_id"] for event in events} == {
            str(rows[0].decision_group_id)
        }

    # And one closed entry, not three.
    closed = (await moderator_http.get("/api/moderation/closed-cases")).json()
    [entry] = [row for row in closed["content"] if row["promptListId"] == prompt_list.id]
    assert entry["reporterCount"] == 3
    assert entry["outcome"] == "hidden"
    assert len(entry["reports"]) == 3

    # A second decision on any of them refuses: review is one-way per row.
    assert (
        await moderator_http.patch(
            f"/api/moderation/prompt-content-reports/{report_ids[0]}",
            json={"status": "dismissed", "note": "Second thoughts."},
        )
    ).status_code == 409


async def test_a_held_publication_is_findable_and_can_be_released(env):
    """The switch used to be a trapdoor.

    Content moderation is otherwise report-driven: somebody complains, and the
    complaint is the queue entry. A publication routed to review by R-LIST-13's
    operator switch has no complaint behind it — it was held by a posture, not
    an accusation — so it appeared in no queue, could not be played, was out of
    the catalogue, and could not be reported by its owner, who is barred from
    reporting their own list. Nothing but a hand-edited database moved it.
    """
    new_client, factory, prompts = env
    owner_http = new_client()
    moderator_http = new_client()
    owner = await register(owner_http, "HeldOwner")
    moderator = await register(moderator_http, "HeldModerator")
    async with factory() as session:
        async with session.begin():
            reviewer = await session.get(User, UUID(moderator["id"]))
            reviewer.role = UserRole.MODERATOR.value
    await mark_staff_ready(factory, reviewer.id)

    prompt_list = await prompts.create_owned(
        owner["id"],
        name="Waiting room",
        description="Held by the switch",
        language="en",
        prompts=(PromptListEntryInput(answer="otter"),),
    )
    await prompts.set_owned_publication(
        owner["id"], prompt_list.id, published=True, under_review=True
    )

    queue = await moderator_http.get("/api/moderation/prompt-lists")
    assert queue.status_code == 200
    assert queue.json()["waiting"] == 1
    [row] = queue.json()["lists"]
    assert row["id"] == prompt_list.id
    assert row["name"] == "Waiting room"
    assert row["ownerDisplayName"] == "HeldOwner"
    assert row["promptCount"] == 1

    decision = await moderator_http.patch(
        f"/api/moderation/prompt-lists/{prompt_list.id}",
        json={
            "state": "active",
            "note": "Read it; it is fine.",
            "expectedVersion": row["version"],
        },
    )

    assert decision.status_code == 200
    async with factory() as session:
        row = await session.get(PromptList, UUID(prompt_list.id))
        assert row.moderation_state == "active"
        assert row.moderated_by_user_id == reviewer.id
        assert row.moderated_at is not None
        event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == "prompt_list.review_active"
            )
        )
    assert event is not None and event.details["note"].startswith("Read it")
    # And it is now playable, which is the whole point of releasing it.
    resolved = await prompts.resolve_selection([row.slug])
    assert list(resolved.prompts) == ["otter"]
    assert (await moderator_http.get("/api/moderation/prompt-lists")).json()[
        "waiting"
    ] == 0


async def test_a_held_publication_can_be_taken_down_instead(env):
    new_client, factory, prompts = env
    owner_http = new_client()
    moderator_http = new_client()
    owner = await register(owner_http, "HeldOwner2")
    moderator = await register(moderator_http, "HeldModerator2")
    async with factory() as session:
        async with session.begin():
            reviewer = await session.get(User, UUID(moderator["id"]))
            reviewer.role = UserRole.MODERATOR.value
    await mark_staff_ready(factory, reviewer.id)
    prompt_list = await prompts.create_owned(
        owner["id"],
        name="Not fine",
        description="",
        language="en",
        prompts=(PromptListEntryInput(answer="otter"),),
    )
    held = await prompts.set_owned_publication(
        owner["id"], prompt_list.id, published=True, under_review=True
    )

    decision = await moderator_http.patch(
        f"/api/moderation/prompt-lists/{prompt_list.id}",
        json={
            "state": "hidden",
            "note": "Against the rules.",
            "expectedVersion": held.version,
        },
    )

    assert decision.status_code == 200
    async with factory() as session:
        row = await session.get(PromptList, UUID(prompt_list.id))
    assert row.moderation_state == "hidden"
    with pytest.raises(PromptListSelectionError):
        await prompts.resolve_selection([row.slug])


async def test_a_list_nobody_held_cannot_be_decided_from_this_queue(env):
    """A decision about content the queue never showed the reviewer."""
    new_client, factory, prompts = env
    owner_http = new_client()
    moderator_http = new_client()
    owner = await register(owner_http, "ActiveOwner")
    moderator = await register(moderator_http, "ActiveModerator")
    async with factory() as session:
        async with session.begin():
            reviewer = await session.get(User, UUID(moderator["id"]))
            reviewer.role = UserRole.MODERATOR.value
    await mark_staff_ready(factory, reviewer.id)
    prompt_list = await prompts.create_owned(
        owner["id"],
        name="Ordinary",
        description="",
        language="en",
        prompts=(PromptListEntryInput(answer="otter"),),
    )

    response = await moderator_http.patch(
        f"/api/moderation/prompt-lists/{prompt_list.id}",
        json={
            "state": "hidden",
            "note": "No.",
            "expectedVersion": prompt_list.version,
        },
    )

    assert response.status_code == 409


async def test_the_publication_queue_is_staff_only(env):
    new_client, factory, prompts = env
    player_http = new_client()
    await register(player_http, "OrdinaryPlayer")

    assert (await player_http.get("/api/moderation/prompt-lists")).status_code == 403



async def staffed_env(env, owner_name: str, moderator_name: str):
    """An owner, a stepped-up moderator, and a held publication."""
    new_client, factory, prompts = env
    owner_http = new_client()
    moderator_http = new_client()
    owner = await register(owner_http, owner_name)
    moderator = await register(moderator_http, moderator_name)
    async with factory() as session:
        async with session.begin():
            reviewer = await session.get(User, UUID(moderator["id"]))
            reviewer.role = UserRole.MODERATOR.value
    await mark_staff_ready(factory, reviewer.id)
    created = await prompts.create_owned(
        owner["id"],
        name="Under the switch",
        description="",
        language="en",
        prompts=(
            PromptListEntryInput(answer="otter", aliases=("river otter",)),
            PromptListEntryInput(answer="badger"),
        ),
    )
    held = await prompts.set_owned_publication(
        owner["id"], created.id, published=True, under_review=True
    )
    return owner, moderator_http, prompts, factory, created, held


async def test_the_reviewer_can_read_every_prompt_they_are_deciding_on(env):
    """A release made from a name and a count was a blind one.

    No other route could show a held list's prompts: the owner's route is the
    owner's, and the catalogue and room resolution both exclude a list that is
    not active. So the switch could not keep out anything it was turned on to
    keep out.
    """
    _, moderator_http, _, _, created, held = await staffed_env(
        env, "ReadOwner", "ReadModerator"
    )

    response = await moderator_http.get(f"/api/moderation/prompt-lists/{created.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == held.version
    assert [
        (entry["prompt"], entry["aliases"], entry["moderationState"])
        for entry in body["prompts"]
    ] == [
        ("otter", ["river otter"], "active"),
        ("badger", [], "active"),
    ]


async def test_an_edit_after_the_reviewer_opened_the_list_refuses_the_decision(env):
    """The bait and the switch.

    An owner can edit a held list, and every save is a new revision. Without
    the version on the decision, a moderator could read a harmless revision,
    the owner could save a different one, and the release would put the one
    nobody read into the catalogue.
    """
    owner, moderator_http, prompts, factory, created, held = await staffed_env(
        env, "BaitOwner", "BaitModerator"
    )
    read = (
        await moderator_http.get(f"/api/moderation/prompt-lists/{created.id}")
    ).json()

    await prompts.update_owned(
        owner["id"],
        created.id,
        expected_version=held.version,
        name="Under the switch",
        description="",
        prompts=(
            PromptListEntryInput(
                answer="otter", concept_id=created.prompts[0].concept_id
            ),
            PromptListEntryInput(answer="something nobody reviewed"),
        ),
    )

    decision = await moderator_http.patch(
        f"/api/moderation/prompt-lists/{created.id}",
        json={
            "state": "active",
            "note": "Looked fine when I read it.",
            "expectedVersion": read["version"],
        },
    )

    assert decision.status_code == 409
    assert "changed after you opened it" in decision.json()["detail"]
    async with factory() as session:
        row = await session.get(PromptList, UUID(created.id))
    assert row.moderation_state == "under_review", "nothing was released"


async def test_the_detail_route_does_not_open_a_list_nobody_held(env):
    """A reading surface for this queue, not a staff window into private lists."""
    new_client, factory, prompts = env
    owner_http = new_client()
    moderator_http = new_client()
    owner = await register(owner_http, "PrivateOwner")
    moderator = await register(moderator_http, "PrivateModerator")
    async with factory() as session:
        async with session.begin():
            reviewer = await session.get(User, UUID(moderator["id"]))
            reviewer.role = UserRole.MODERATOR.value
    await mark_staff_ready(factory, reviewer.id)
    private = await prompts.create_owned(
        owner["id"],
        name="Nobody's business",
        description="",
        language="en",
        prompts=(PromptListEntryInput(answer="otter"),),
    )

    response = await moderator_http.get(f"/api/moderation/prompt-lists/{private.id}")

    assert response.status_code == 404


async def test_withdrawing_a_held_publication_releases_the_hold(env):
    """A hold is released by withdrawing; a finding is not.

    `under_review` on a list is written in one place - a publish under the
    operator switch - so it only ever means "waiting to be published". Once the
    owner withdraws there is nothing to publish, and keeping the hold left a
    private list in the queue where a moderator could still decide on it.
    """
    owner, moderator_http, prompts, factory, created, held = await staffed_env(
        env, "WithdrawOwner", "WithdrawMod"
    )

    withdrawn = await prompts.set_owned_publication(
        owner["id"], created.id, published=False
    )

    assert withdrawn.visibility == "private"
    assert withdrawn.moderation_state == "active"
    queue = (await moderator_http.get("/api/moderation/prompt-lists")).json()
    assert queue["waiting"] == 0 and queue["lists"] == []
    decision = await moderator_http.patch(
        f"/api/moderation/prompt-lists/{created.id}",
        json={
            "state": "hidden",
            "note": "Too late.",
            "expectedVersion": withdrawn.version,
        },
    )
    assert decision.status_code == 409


async def _staff(factory, account: dict, role: UserRole) -> None:
    async with factory() as session:
        async with session.begin():
            user = await session.get(User, UUID(account["id"]))
            user.role = role.value
    await mark_staff_ready(factory, account["id"])


async def test_a_moderator_neither_sees_nor_decides_reports_about_their_own_list(env):
    """#1063: the player queue's rule (#1003) on the account that owns the
    reported list. Another moderator decides it; an administrator may decide
    their own, since a deployment's one admin would otherwise never can."""
    new_client, factory, prompts = env
    owner_http, reporter_http, other_http, admin_http = (
        new_client(), new_client(), new_client(), new_client()
    )
    owner = await register(owner_http, "ModOwner")
    await register(reporter_http, "ListReporter")
    other = await register(other_http, "OtherListMod")
    admin = await register(admin_http, "ListAdmin")
    await _staff(factory, owner, UserRole.MODERATOR)
    await _staff(factory, other, UserRole.MODERATOR)
    await _staff(factory, admin, UserRole.ADMIN)

    async def reported_list(name: str, owner_account: dict) -> str:
        created = await prompts.create_owned(
            owner_account["id"],
            name=name,
            description="",
            language="en",
            prompts=(PromptListEntryInput(answer="otter"),),
        )
        await published(factory, created.id)
        report = await reporter_http.post(
            "/api/prompt-content-reports",
            json={"promptListId": created.id, "reason": "spam", "details": "Spam."},
        )
        assert report.status_code == 201, report.text
        return report.json()["id"]

    report_id = await reported_list("Moderated by me", owner)
    own_queue = await owner_http.get(
        "/api/moderation/prompt-content-reports", params={"status": "pending"}
    )
    assert own_queue.json()["incidents"] == [], "not theirs to see"
    refused = await owner_http.patch(
        f"/api/moderation/prompt-content-reports/{report_id}",
        json={"status": "dismissed", "note": "Nothing here."},
    )
    assert refused.status_code == 403

    others_queue = await other_http.get(
        "/api/moderation/prompt-content-reports", params={"status": "pending"}
    )
    assert [r["id"] for i in others_queue.json()["incidents"] for r in i["reports"]] == [
        report_id
    ]
    decided = await other_http.patch(
        f"/api/moderation/prompt-content-reports/{report_id}",
        json={"status": "dismissed", "note": "Fine."},
    )
    assert decided.status_code == 200, decided.text

    admins_own = await reported_list("Administered by me", admin)
    admin_queue = await admin_http.get(
        "/api/moderation/prompt-content-reports", params={"status": "pending"}
    )
    assert [r["id"] for i in admin_queue.json()["incidents"] for r in i["reports"]] == [
        admins_own
    ]
    assert (
        await admin_http.patch(
            f"/api/moderation/prompt-content-reports/{admins_own}",
            json={"status": "dismissed", "note": "Mine, and fine."},
        )
    ).status_code == 200


async def test_a_moderator_cannot_release_their_own_held_list(env):
    new_client, factory, prompts = env
    moderator_http, other_http = new_client(), new_client()
    moderator = await register(moderator_http, "HeldModOwner")
    other = await register(other_http, "HeldModOther")
    await _staff(factory, moderator, UserRole.MODERATOR)
    await _staff(factory, other, UserRole.MODERATOR)
    created = await prompts.create_owned(
        moderator["id"],
        name="My own held list",
        description="",
        language="en",
        prompts=(PromptListEntryInput(answer="otter"),),
    )
    held = await prompts.set_owned_publication(
        moderator["id"], created.id, published=True, under_review=True
    )
    # Not listed or counted for them; the other moderator sees it waiting.
    own_queue = (await moderator_http.get("/api/moderation/prompt-lists")).json()
    assert own_queue["waiting"] == 0 and own_queue["lists"] == []
    others_queue = (await other_http.get("/api/moderation/prompt-lists")).json()
    assert [row["id"] for row in others_queue["lists"]] == [created.id]
    decision = {
        "state": "active",
        "note": "Looks fine to me.",
        "expectedVersion": held.version,
    }
    refused = await moderator_http.patch(
        f"/api/moderation/prompt-lists/{created.id}", json=decision
    )
    assert refused.status_code == 403
    released = await other_http.patch(
        f"/api/moderation/prompt-lists/{created.id}", json=decision
    )
    assert released.status_code == 200, released.text


async def test_an_administrator_sees_and_releases_their_own_held_list(env):
    """The exemption reaches the queue as well as the decision (#1063)."""
    new_client, factory, prompts = env
    admin_http = new_client()
    admin = await register(admin_http, "HeldAdmin")
    await _staff(factory, admin, UserRole.ADMIN)
    created = await prompts.create_owned(
        admin["id"],
        name="The admin's own",
        description="",
        language="en",
        prompts=(PromptListEntryInput(answer="otter"),),
    )
    held = await prompts.set_owned_publication(
        admin["id"], created.id, published=True, under_review=True
    )
    queue = (await admin_http.get("/api/moderation/prompt-lists")).json()
    assert queue["waiting"] == 1 and [row["id"] for row in queue["lists"]] == [created.id]
    released = await admin_http.patch(
        f"/api/moderation/prompt-lists/{created.id}",
        json={"state": "active", "note": "Mine; fine.", "expectedVersion": held.version},
    )
    assert released.status_code == 200, released.text


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(lambda entry: ("offensive prompt", ("an alias",), True), id="alias added"),
        pytest.param(lambda entry: ("offensive  prompt!", (), True), id="answer respelled"),
        pytest.param(lambda entry: ("Offensive Prompt", (), False), id="deleted and re-added"),
    ],
)
async def test_editing_a_hidden_prompt_does_not_bring_it_back(env, edit):
    """#1020: any edit to an entry - one alias - writes a new version of the
    concept, and a new version was born `active`, so a word a moderator hid
    came back in the list's next revision with nobody asked. Deleting the
    row and typing the word in again made a new concept, born active too.
    The decision carries, and the word stays out of play."""
    new_client, factory, prompts = env
    owner_http, moderator_http = new_client(), new_client()
    owner = await register(owner_http, "HiddenOwner")
    moderator = await register(moderator_http, "HidingMod")
    created = await prompts.create_owned(
        owner["id"],
        name="Has a hidden word",
        description="",
        language="en",
        prompts=(
            PromptListEntryInput(answer="offensive prompt"),
            PromptListEntryInput(answer="safe prompt"),
            PromptListEntryInput(answer="third prompt"),
        ),
    )
    hidden_entry, *others = created.prompts
    hidden_at = datetime.now(timezone.utc) - timedelta(hours=1)
    async with factory() as session:
        async with session.begin():
            version = await session.get(PromptVersion, UUID(hidden_entry.prompt_version_id))
            version.moderation_state = "hidden"
            version.moderated_by_user_id = UUID(moderator["id"])
            version.moderated_at = hidden_at

    answer, aliases, keeps_identity = edit(hidden_entry)
    updated = await prompts.update_owned(
        owner["id"],
        created.id,
        expected_version=created.version,
        name=created.name,
        description="",
        prompts=(
            PromptListEntryInput(
                answer=answer,
                concept_id=hidden_entry.concept_id if keeps_identity else None,
                aliases=aliases,
            ),
            *(
                PromptListEntryInput(answer=entry.answer, concept_id=entry.concept_id)
                for entry in others
            ),
        ),
    )
    kept = {entry.concept_id for entry in others}
    [edited] = [p for p in updated.prompts if p.concept_id not in kept]
    assert edited.prompt_version_id != hidden_entry.prompt_version_id, "a new version"
    assert edited.moderation_state == "hidden"
    async with factory() as session:
        row = await session.get(PromptVersion, UUID(edited.prompt_version_id))
        assert row.moderated_by_user_id == UUID(moderator["id"])
        assert row.moderated_at == hidden_at
    selection = await prompts.resolve_selection(
        [created.slug], requesting_user_id=owner["id"]
    )
    assert edited.answer not in selection.prompts
    assert sorted(selection.prompts) == sorted(entry.answer for entry in others)


async def test_hiding_a_reported_version_hides_the_one_the_list_has_now(env):
    """#1020 review: a report names the version a game played; if the owner
    saved a newer one before a moderator got to it, hiding only the reported
    version left the list's current one live."""
    new_client, factory, prompts = env
    owner_http, reporter_http, moderator_http = new_client(), new_client(), new_client()
    owner = await register(owner_http, "EditsFirst")
    await register(reporter_http, "PlayedIt")
    moderator = await register(moderator_http, "LateMod")
    async with factory() as session:
        async with session.begin():
            (await session.get(User, UUID(moderator["id"]))).role = UserRole.MODERATOR.value
    await mark_staff_ready(factory, moderator["id"])
    created = await prompts.create_owned(
        owner["id"],
        name="Edited after the game",
        description="",
        language="en",
        prompts=(
            PromptListEntryInput(answer="offensive prompt"),
            PromptListEntryInput(answer="safe prompt"),
        ),
    )
    await published(factory, created.id)
    played, safe = created.prompts
    report = await reporter_http.post(
        "/api/prompt-content-reports",
        json={
            "promptListId": created.id,
            "promptVersionId": played.prompt_version_id,
            "reason": "hateful_or_abusive",
            "details": "This one.",
        },
    )
    assert report.status_code == 201, report.text
    edited = await prompts.update_owned(
        owner["id"],
        created.id,
        expected_version=created.version,
        name=created.name,
        description="",
        prompts=(
            PromptListEntryInput(
                answer=played.answer, concept_id=played.concept_id, aliases=("alias",)
            ),
            PromptListEntryInput(answer=safe.answer, concept_id=safe.concept_id),
        ),
    )
    [current] = [p for p in edited.prompts if p.concept_id == played.concept_id]
    assert current.prompt_version_id != played.prompt_version_id
    assert current.moderation_state == "active", "nothing to carry yet"

    resolved = await moderator_http.patch(
        f"/api/moderation/prompt-content-reports/{report.json()['id']}",
        json={"status": "resolved", "note": "Hidden.", "moderationState": "hidden"},
    )
    assert resolved.status_code == 200, resolved.text
    async with factory() as session:
        row = await session.get(PromptVersion, UUID(current.prompt_version_id))
        assert row.moderation_state == "hidden"


async def _list_with_a_hidden_word(env, owner_name: str):
    new_client, factory, prompts = env
    owner_http = new_client()
    owner = await register(owner_http, owner_name)
    created = await prompts.create_owned(
        owner["id"],
        name="Has a hidden word",
        description="",
        language="en",
        prompts=(
            PromptListEntryInput(answer="offensive prompt"),
            PromptListEntryInput(answer="safe prompt"),
            PromptListEntryInput(answer="third prompt"),
        ),
    )
    hidden, safe, third = created.prompts
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptVersion, UUID(hidden.prompt_version_id))
            row.moderation_state = "hidden"
    return owner, prompts, created, safe, third


async def test_a_hidden_word_typed_back_a_save_later_stays_hidden(env):
    """Round two of #1020's review: matching only the previous revision lost
    the decision after one save without the word."""
    owner, prompts, created, safe, third = await _list_with_a_hidden_word(env, "TwoSaves")
    dropped = await prompts.update_owned(
        owner["id"], created.id, expected_version=created.version, name=created.name,
        description="",
        prompts=tuple(
            PromptListEntryInput(answer=e.answer, concept_id=e.concept_id) for e in (safe, third)
        ),
    )
    back = await prompts.update_owned(
        owner["id"], created.id, expected_version=dropped.version, name=created.name,
        description="",
        prompts=(
            *(PromptListEntryInput(answer=e.answer, concept_id=e.concept_id) for e in (safe, third)),
            PromptListEntryInput(answer="offensive prompt"),
        ),
    )
    [retyped] = [p for p in back.prompts if p.answer == "offensive prompt"]
    assert retyped.moderation_state == "hidden"


async def test_another_entry_respelled_into_a_hidden_word_is_hidden(env):
    owner, prompts, created, safe, third = await _list_with_a_hidden_word(env, "Respeller")
    updated = await prompts.update_owned(
        owner["id"], created.id, expected_version=created.version, name=created.name,
        description="",
        prompts=(
            PromptListEntryInput(answer="offensive prompt", concept_id=safe.concept_id),
            PromptListEntryInput(answer=third.answer, concept_id=third.concept_id),
        ),
    )
    [respelled] = [p for p in updated.prompts if p.concept_id == safe.concept_id]
    assert respelled.moderation_state == "hidden"
    [kept] = [p for p in updated.prompts if p.concept_id == third.concept_id]
    assert kept.moderation_state == "active"


async def test_restoring_a_reported_prompt_restores_every_version(env):
    """The concept-wide decision runs both ways: a restore reaches the
    versions an edit carried the hidden state to."""
    new_client, factory, prompts = env
    owner_http, reporter_http, moderator_http = new_client(), new_client(), new_client()
    owner = await register(owner_http, "Restored")
    await register(reporter_http, "Reporter2")
    moderator = await register(moderator_http, "RestoreMod")
    async with factory() as session:
        async with session.begin():
            (await session.get(User, UUID(moderator["id"]))).role = UserRole.MODERATOR.value
    await mark_staff_ready(factory, moderator["id"])
    created = await prompts.create_owned(
        owner["id"], name="Restorable", description="", language="en",
        prompts=(PromptListEntryInput(answer="borderline word"), PromptListEntryInput(answer="fine")),
    )
    await published(factory, created.id)
    word, fine = created.prompts
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptVersion, UUID(word.prompt_version_id))
            row.moderation_state = "hidden"
    edited = await prompts.update_owned(
        owner["id"], created.id, expected_version=created.version, name=created.name,
        description="",
        prompts=(
            PromptListEntryInput(answer=word.answer, concept_id=word.concept_id, aliases=("edge",)),
            PromptListEntryInput(answer=fine.answer, concept_id=fine.concept_id),
        ),
    )
    [current] = [p for p in edited.prompts if p.concept_id == word.concept_id]
    assert current.moderation_state == "hidden"
    report = await reporter_http.post(
        "/api/prompt-content-reports",
        json={
            "promptListId": created.id,
            "promptVersionId": word.prompt_version_id,
            "reason": "other",
            "details": "Was it right to hide this?",
        },
    )
    assert report.status_code == 201, report.text
    restored = await moderator_http.patch(
        f"/api/moderation/prompt-content-reports/{report.json()['id']}",
        json={"status": "resolved", "note": "It was fine.", "moderationState": "active"},
    )
    assert restored.status_code == 200, restored.text
    async with factory() as session:
        row = await session.get(PromptVersion, UUID(current.prompt_version_id))
        assert row.moderation_state == "active"


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="proves row locking, which SQLite's single test connection cannot",
)
async def test_a_hide_decided_during_a_save_reaches_the_version_the_save_writes(
    env, monkeypatch
):
    """#1092 review: a save that had read the concept as active and not yet
    written its new version, while a moderator hid the concept, committed
    that version active - the concept-wide UPDATE never saw it. The decision
    now takes the list row the save holds, so it waits and then covers it."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession

    new_client, factory, prompts = env
    owner_http, reporter_http, moderator_http = new_client(), new_client(), new_client()
    owner = await register(owner_http, "RacingOwner")
    await register(reporter_http, "RacingReporter")
    moderator = await register(moderator_http, "RacingMod")
    async with factory() as session:
        async with session.begin():
            (await session.get(User, UUID(moderator["id"]))).role = UserRole.MODERATOR.value
    await mark_staff_ready(factory, moderator["id"])
    created = await prompts.create_owned(
        owner["id"], name="Raced", description="", language="en",
        prompts=(PromptListEntryInput(answer="offensive prompt"), PromptListEntryInput(answer="fine")),
    )
    await published(factory, created.id)
    word, fine = created.prompts
    report = await reporter_http.post(
        "/api/prompt-content-reports",
        json={
            "promptListId": created.id,
            "promptVersionId": word.prompt_version_id,
            "reason": "hateful_or_abusive",
            "details": "This one.",
        },
    )
    assert report.status_code == 201, report.text

    # Hold the save at its first flush: it has read the concept as active
    # and built the new version from that, holding the list row.
    reached, release = asyncio.Event(), asyncio.Event()
    original_flush = AsyncSession.flush
    held = [True]

    async def flush_then_wait(self, *args, **kwargs):
        if held and held.pop():
            reached.set()
            await release.wait()
        return await original_flush(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "flush", flush_then_wait)
    save = asyncio.create_task(
        prompts.update_owned(
            owner["id"], created.id, expected_version=created.version, name=created.name,
            description="",
            prompts=(
                PromptListEntryInput(answer=word.answer, concept_id=word.concept_id, aliases=("edge",)),
                PromptListEntryInput(answer=fine.answer, concept_id=fine.concept_id),
            ),
        )
    )
    await asyncio.wait_for(reached.wait(), timeout=10)
    decide = asyncio.create_task(
        moderator_http.patch(
            f"/api/moderation/prompt-content-reports/{report.json()['id']}",
            json={"status": "resolved", "note": "Hidden.", "moderationState": "hidden"},
        )
    )
    await asyncio.sleep(0.3)
    assert not decide.done(), "the decision waits for the save holding the list"
    release.set()
    saved, decided = await asyncio.wait_for(asyncio.gather(save, decide), timeout=10)
    assert decided.status_code == 200, decided.text
    [current] = [p for p in saved.prompts if p.concept_id == word.concept_id]
    async with factory() as session:
        row = await session.get(PromptVersion, UUID(current.prompt_version_id))
        assert row.moderation_state == "hidden"


async def test_a_word_hidden_in_one_list_is_hidden_in_the_owners_others(env):
    """#1091: a hidden word typed into another of the owner's lists - a new
    one or one they already had - was a new concept born active. The takedown
    reaches every list the owner has, in that language; another player typing
    the same word is untouched."""
    new_client, factory, prompts = env
    owner_http, stranger_http = new_client(), new_client()
    owner = await register(owner_http, "ManyLists")
    stranger = await register(stranger_http, "Unrelated")
    first = await prompts.create_owned(
        owner["id"], name="First", description="", language="en",
        prompts=(PromptListEntryInput(answer="offensive prompt", aliases=("its alias",)),),
    )
    other = await prompts.create_owned(
        owner["id"], name="Other", description="", language="en",
        prompts=(PromptListEntryInput(answer="fine"),),
    )
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptVersion, UUID(first.prompts[0].prompt_version_id))
            row.moderation_state = "hidden"

    fresh = await prompts.create_owned(
        owner["id"], name="Fresh", description="", language="en",
        prompts=(PromptListEntryInput(answer="Offensive Prompt"), PromptListEntryInput(answer="ok")),
    )
    assert {p.answer: p.moderation_state for p in fresh.prompts} == {
        "Offensive Prompt": "hidden",
        "ok": "active",
    }

    edited = await prompts.update_owned(
        owner["id"], other.id, expected_version=other.version, name=other.name,
        description="",
        prompts=(
            PromptListEntryInput(answer="fine", concept_id=other.prompts[0].concept_id),
            PromptListEntryInput(answer="its alias"),
        ),
    )
    assert {p.answer: p.moderation_state for p in edited.prompts} == {
        "fine": "active",
        "its alias": "hidden",
    }

    theirs = await prompts.create_owned(
        stranger["id"], name="Theirs", description="", language="en",
        prompts=(PromptListEntryInput(answer="offensive prompt"),),
    )
    assert theirs.prompts[0].moderation_state == "active", "another player's list is theirs"

    elsewhere = await prompts.create_owned(
        owner["id"], name="Anderswo", description="", language="de",
        prompts=(PromptListEntryInput(answer="offensive prompt"),),
    )
    assert elsewhere.prompts[0].moderation_state == "active", "keys mean one language"


async def test_a_hidden_word_follows_the_owner_into_lists_in_no_language(env):
    """#821: a list in no language is played in every room, so a word hidden
    in one of the owner's lists and typed into an Any-language list - or the
    other way round - is the same word, respelled by its language's fold."""
    new_client, factory, prompts = env
    owner_http = new_client()
    owner = await register(owner_http, "AnyLanguageHider")
    english = await prompts.create_owned(
        owner["id"], name="Names", description="", language="en",
        prompts=(PromptListEntryInput(answer="Pikachu"),),
    )
    agnostic = await prompts.create_owned(
        owner["id"], name="More names", description="", language="zxx",
        prompts=(PromptListEntryInput(answer="Müller"),),
    )
    async with factory() as session:
        async with session.begin():
            for version_id in (
                english.prompts[0].prompt_version_id,
                agnostic.prompts[0].prompt_version_id,
            ):
                (await session.get(PromptVersion, UUID(version_id))).moderation_state = "hidden"

    into_agnostic = await prompts.create_owned(
        owner["id"], name="Pokémon", description="", language="zxx",
        prompts=(PromptListEntryInput(answer="pikachu"), PromptListEntryInput(answer="Evoli")),
    )
    assert {p.answer: p.moderation_state for p in into_agnostic.prompts} == {
        "pikachu": "hidden",
        "Evoli": "active",
    }
    # Stored as `muller` in no language and keyed `mueller` in German: the
    # same word to a German room, so the same word here.
    into_german = await prompts.create_owned(
        owner["id"], name="Namen", description="", language="de",
        prompts=(PromptListEntryInput(answer="Müller"), PromptListEntryInput(answer="Hund")),
    )
    assert {p.answer: p.moderation_state for p in into_german.prompts} == {
        "Müller": "hidden",
        "Hund": "active",
    }


async def test_an_agnostic_list_meets_a_hidden_word_in_that_word_s_own_fold(env):
    """Compared where both are played - a German room - "Bär" is the hidden
    German word and "Bar" is another one (#821 review): folding the hidden
    word the agnostic way, `bar`, hid a word nobody took down."""
    new_client, factory, prompts = env
    owner_http = new_client()
    owner = await register(owner_http, "FoldOwner")
    german = await prompts.create_owned(
        owner["id"], name="Tiere", description="", language="de",
        prompts=(PromptListEntryInput(answer="Bär"),),
    )
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptVersion, UUID(german.prompts[0].prompt_version_id))
            row.moderation_state = "hidden"

    agnostic = await prompts.create_owned(
        owner["id"], name="Mixed", description="", language="zxx",
        prompts=(PromptListEntryInput(answer="Bar"), PromptListEntryInput(answer="Baer")),
    )

    assert {p.answer: p.moderation_state for p in agnostic.prompts} == {
        "Bar": "active",
        "Baer": "hidden",
    }


async def _staff_member(factory, account: dict, role: UserRole) -> None:
    async with factory() as session:
        async with session.begin():
            (await session.get(User, UUID(account["id"]))).role = role.value
    await mark_staff_ready(factory, account["id"])


async def test_restoring_a_word_restores_the_copies_its_takedown_was_carried_to(env):
    """#1091 review: the owner's copy in another list was born hidden with the
    decision's byline. A restore reached only the original's concept, so the
    copy stayed hidden with no report to decide it - and, as a hidden word,
    re-hid the original the next time its entry was edited."""
    new_client, factory, prompts = env
    owner_http, reporter_http, moderator_http = new_client(), new_client(), new_client()
    owner = await register(owner_http, "RestoredOwner")
    await register(reporter_http, "RestoreReporter")
    moderator = await register(moderator_http, "RestoreModerator")
    await _staff_member(factory, moderator, UserRole.MODERATOR)
    first = await prompts.create_owned(
        owner["id"], name="Original", description="", language="en",
        prompts=(PromptListEntryInput(answer="borderline word"), PromptListEntryInput(answer="fine")),
    )
    await published(factory, first.id)
    word = first.prompts[0]

    async def decide(state: str) -> None:
        report = await reporter_http.post(
            "/api/prompt-content-reports",
            json={
                "promptListId": first.id,
                "promptVersionId": word.prompt_version_id,
                "reason": "other",
                "details": f"Decide it {state}.",
            },
        )
        assert report.status_code == 201, report.text
        decided = await moderator_http.patch(
            f"/api/moderation/prompt-content-reports/{report.json()['id']}",
            json={"status": "resolved", "note": state, "moderationState": state},
        )
        assert decided.status_code == 200, decided.text

    await decide("hidden")
    copy = await prompts.create_owned(
        owner["id"], name="Copy", description="", language="en",
        prompts=(PromptListEntryInput(answer="borderline word"),),
    )
    assert copy.prompts[0].moderation_state == "hidden"
    # A list in no language shares its words with every language (#821).
    agnostic_copy = await prompts.create_owned(
        owner["id"], name="Any language copy", description="", language="zxx",
        prompts=(PromptListEntryInput(answer="borderline word"),),
    )
    assert agnostic_copy.prompts[0].moderation_state == "hidden"
    # ...and from there to every language that plays it: the carry crosses
    # languages through it, so the restore below has to as well.
    french_copy = await prompts.create_owned(
        owner["id"], name="Copie", description="", language="fr",
        prompts=(PromptListEntryInput(answer="Borderline Word"),),
    )
    assert french_copy.prompts[0].moderation_state == "hidden"

    # Decided hidden a second time: the copy carries the new decision too,
    # or the restore below - matching on it - would miss the copy.
    await decide("hidden")
    await decide("active")
    async with factory() as session:
        carried = await session.get(PromptVersion, UUID(copy.prompts[0].prompt_version_id))
        assert carried.moderation_state == "active", "the carried copy comes back too"
        carried_agnostic = await session.get(
            PromptVersion, UUID(agnostic_copy.prompts[0].prompt_version_id)
        )
        assert carried_agnostic.moderation_state == "active", "and the one in no language"
        carried_french = await session.get(
            PromptVersion, UUID(french_copy.prompts[0].prompt_version_id)
        )
        assert carried_french.moderation_state == "active", "and the one it reached from there"
    another = await prompts.create_owned(
        owner["id"], name="After the restore", description="", language="en",
        prompts=(PromptListEntryInput(answer="borderline word"),),
    )
    assert another.prompts[0].moderation_state == "active", "nothing left to carry"

    latest = await prompts.get_owned(owner["id"], first.id)
    edited = await prompts.update_owned(
        owner["id"], first.id, expected_version=latest.version, name=first.name,
        description="",
        prompts=(
            PromptListEntryInput(answer=word.answer, concept_id=word.concept_id, aliases=("edge",)),
            PromptListEntryInput(answer="fine", concept_id=first.prompts[1].concept_id),
        ),
    )
    [again] = [p for p in edited.prompts if p.concept_id == word.concept_id]
    assert again.moderation_state == "active", "the restore stands through an edit"


async def test_a_takedown_outlives_its_deleted_list(env):
    """#1091 review: the lookup reaches hidden words through list revisions,
    and reclaiming a deleted list's unpinned revisions a day later let the word
    be typed into a new list active. A revision holding a takedown is kept."""
    from datetime import datetime, timedelta, timezone

    from app.services.prompt_reclaim import reclaim_retired_prompt_lists

    new_client, factory, prompts = env
    owner_http = new_client()
    owner = await register(owner_http, "Deleter")
    doomed = await prompts.create_owned(
        owner["id"], name="Doomed", description="", language="en",
        prompts=(PromptListEntryInput(answer="offensive prompt"),),
    )
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptVersion, UUID(doomed.prompts[0].prompt_version_id))
            row.moderation_state = "hidden"
            row.moderated_at = datetime.now(timezone.utc)
    assert await prompts.delete_owned(owner["id"], doomed.id)
    await reclaim_retired_prompt_lists(factory, now=datetime.now(timezone.utc) + timedelta(days=2))

    fresh = await prompts.create_owned(
        owner["id"], name="Fresh start", description="", language="en",
        prompts=(PromptListEntryInput(answer="offensive prompt"),),
    )
    assert fresh.prompts[0].moderation_state == "hidden"



async def test_an_erased_owners_takedown_is_not_kept_for_nobody(env):
    """The takedown pins its revision only while the list has an owner whose
    saves look there; an erased account's retired list is reclaimed as any
    other, rather than keeping its hidden text for good."""
    from datetime import datetime, timedelta, timezone

    from app.db.models import PromptListRevision
    from app.services.prompt_reclaim import reclaim_retired_prompt_lists

    new_client, factory, prompts = env
    owner_http = new_client()
    owner = await register(owner_http, "Erased")
    doomed = await prompts.create_owned(
        owner["id"], name="Ownerless", description="", language="en",
        prompts=(PromptListEntryInput(answer="offensive prompt"),),
    )
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptVersion, UUID(doomed.prompts[0].prompt_version_id))
            row.moderation_state = "hidden"
    assert await prompts.delete_owned(owner["id"], doomed.id)
    async with factory() as session:
        async with session.begin():
            (await session.get(PromptList, UUID(doomed.id))).owner_user_id = None
    await reclaim_retired_prompt_lists(factory, now=datetime.now(timezone.utc) + timedelta(days=2))
    async with factory() as session:
        left = await session.scalar(
            select(func.count(PromptListRevision.id)).where(
                PromptListRevision.prompt_list_id == UUID(doomed.id)
            )
        )
    assert left == 0
