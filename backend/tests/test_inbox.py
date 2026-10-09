"""The account inbox (#1436): what a read shows, reading, paging, and how long
an entry - and a warning - is kept.

The writes that put entries there are pinned beside the facts they are about:
shares in `test_api_shares.py`, warnings and reviewed reports in
`test_moderation_api.py`, friends in `test_friends_api.py`, roles in
`test_admin_controls.py`, invitations and the room gate in
`handlers/test_inbox_gate.py`.
"""
from __future__ import annotations

import asyncio

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.inbox import INBOX_PAGE, create_inbox_router, inbox_payload
from app.auth.middleware import SessionAuthMiddleware
from app.auth.pending_role import OFFER_LIFETIME
from app.auth.retention import purge_expired_inbox_entries, purge_expired_warnings
from app.auth.routes import create_auth_router
from app.db.models import IdentityAlias, InboxEntry, User, UserWarning, generate_uuid
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.auth.warnings import has_unacknowledged_warning
from app.services import inbox as inbox_service
from app.services.inbox import INBOX_RETENTION_DAYS, add_entry, count_reviewed_reports

from tests.dbfixtures import create_test_db

PASSWORD = "a-good-password"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "inbox-test-secret")
    factory, engine = await create_test_db()
    told = AsyncMock()
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    app.include_router(create_inbox_router(factory, on_inbox_changed=told))
    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    new_client.told = told
    try:
        yield new_client, factory
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def register(client: AsyncClient, username: str) -> dict:
    assert (await client.get("/api/auth/me")).status_code == 200
    response = await client.post(
        "/api/auth/register", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()


async def entry(
    factory, user_id: str, kind: str = "role", *, ago=timedelta(), read: bool = False, **fields
) -> str:
    """One entry, its id answered. `read` for a count of reviewed reports
    beside another: an account holds one unread one."""
    async with factory() as session:
        async with session.begin():
            owned = select(InboxEntry.id).where(InboxEntry.user_id == UUID(user_id))
            before = set((await session.scalars(owned)).all())
            at = datetime.now(timezone.utc) - ago
            if read:
                session.add(
                    InboxEntry(
                        id=generate_uuid(), user_id=UUID(user_id), kind=kind,
                        subject_id=UUID(str(fields["subject_id"])) if fields.get("subject_id") else None,
                        params=fields.get("params", {}), created_at=at, read_at=at,
                    )
                )
            else:
                await add_entry(session, user_id=user_id, kind=kind, created_at=at, **fields)
            await session.flush()
            [added] = set((await session.scalars(owned)).all()) - before
    return str(added)


async def test_an_account_with_nothing_to_be_told_reads_an_empty_inbox(env):
    new_client, _ = env
    client = new_client()
    await register(client, "Ordinary")
    assert (await client.get("/api/inbox")).json() == {
        "entries": [],
        "unreadCount": 0,
        "next": None,
        "mustAcknowledge": None,
        "pendingRole": None,
    }


async def test_an_offer_leads_to_enrolment_only_while_it_stands(env):
    """The entry stays as what happened; its way in is read from the offer,
    so an offer withdrawn or taken up stops sending anybody to enrol (#1436)."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Offered")
    async with factory() as session:
        async with session.begin():
            user = await session.get(User, UUID(account["id"]))
            user.pending_role = "moderator"
            user.pending_role_at = datetime.now(timezone.utc)
    await entry(factory, account["id"], params={"role": "moderator", "change": "offered"})

    body = (await client.get("/api/inbox")).json()
    [shown] = body["entries"]
    assert (shown["kind"], shown["role"], shown["change"], shown["offerOpen"]) == (
        "role", "moderator", "offered", True,
    )
    assert body["pendingRole"] == "moderator"

    async with factory() as session:
        async with session.begin():
            user = await session.get(User, UUID(account["id"]))
            user.pending_role_at = datetime.now(timezone.utc) - OFFER_LIFETIME - timedelta(minutes=1)
    body = (await client.get("/api/inbox")).json()
    # Lapsed: enrolment would grant nothing now (R-ROLE-02).
    assert body["entries"][0]["offerOpen"] is False and body["pendingRole"] is None

    async with factory() as session:
        async with session.begin():
            user = await session.get(User, UUID(account["id"]))
            user.pending_role = None
            user.pending_role_at = None
    body = (await client.get("/api/inbox")).json()
    assert body["entries"][0]["offerOpen"] is False and body["pendingRole"] is None


async def test_reading_is_by_name_or_all_and_only_ever_ones_own(env):
    new_client, factory = env
    mine, theirs = new_client(), new_client()
    me = await register(mine, "Reader")
    them = await register(theirs, "Other")
    first = await entry(factory, me["id"], params={"role": "user", "change": "removed"})
    await entry(factory, me["id"], "reports_reviewed", params={"count": 2})
    other = await entry(factory, them["id"], "reports_reviewed", params={"count": 1})

    assert (await mine.post("/api/inbox/read", json={"ids": [other]})).json() == {"unreadCount": 2}
    assert (await theirs.get("/api/inbox")).json()["unreadCount"] == 1
    new_client.told.assert_not_awaited()

    assert (await mine.post("/api/inbox/read", json={"ids": [first, "nonsense"]})).json() == {
        "unreadCount": 1
    }
    # Every other tab of the account hears that the count moved.
    new_client.told.assert_awaited_once_with(me["id"])
    assert (await mine.post("/api/inbox/read", json={"all": True})).json() == {"unreadCount": 0}
    assert [e["read"] for e in (await mine.get("/api/inbox")).json()["entries"]] == [True, True]


async def test_the_inbox_is_read_a_page_at_a_time_newest_first(env):
    new_client, factory = env
    client = new_client()
    account = await register(client, "Busy")
    for index in range(INBOX_PAGE + 3):
        await entry(
            factory, account["id"], "reports_reviewed",
            ago=timedelta(minutes=index), params={"count": index + 1}, read=index > 0,
        )
    first = (await client.get("/api/inbox")).json()
    assert [e["count"] for e in first["entries"]] == list(range(1, INBOX_PAGE + 1))
    assert first["unreadCount"] == 1
    rest = (await client.get("/api/inbox", params={"before": first["next"]})).json()
    assert [e["count"] for e in rest["entries"]] == [INBOX_PAGE + 1, INBOX_PAGE + 2, INBOX_PAGE + 3]
    assert rest["next"] is None
    # Somebody else's entry, or none at all, is not a place to page from.
    assert (await client.get("/api/inbox", params={"before": str(generate_uuid())})).status_code == 404


async def test_an_entry_is_kept_ninety_days_and_a_warning_twelve_months(env):
    """An entry is only the message (R-INBOX-06): it goes after ninety days,
    read or not. A warning is moderation history and is kept a year."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Aging")
    await entry(factory, account["id"], "reports_reviewed", ago=timedelta(days=INBOX_RETENTION_DAYS + 1), params={"count": 1})
    await entry(factory, account["id"], "reports_reviewed", ago=timedelta(days=INBOX_RETENTION_DAYS - 1), params={"count": 2}, read=True)
    async with factory() as session:
        async with session.begin():
            for days in (366, 300):
                session.add(
                    UserWarning(
                        id=generate_uuid(),
                        user_id=UUID(account["id"]),
                        reason=f"{days} days ago",
                        created_at=datetime.now(timezone.utc) - timedelta(days=days),
                        acknowledged_at=datetime.now(timezone.utc),
                    )
                )

    await purge_expired_inbox_entries(factory)
    await purge_expired_warnings(factory)

    assert [e["count"] for e in (await client.get("/api/inbox")).json()["entries"]] == [2]
    async with factory() as session:
        reasons = (await session.scalars(select(UserWarning.reason))).all()
    assert reasons == ["300 days ago"]


async def test_an_erased_account_takes_its_inbox_and_its_warnings_with_it(env):
    """Erasure leaves nothing of the inbox behind, and the warnings go with
    the account rather than being orphaned (#1436). An entry elsewhere about
    the erased account as a friend is about nobody now, and goes too."""
    new_client, factory = env
    leaving, staying = new_client(), new_client()
    gone = await register(leaving, "Leaving")
    kept = await register(staying, "Staying")
    await entry(factory, gone["id"], "reports_reviewed", params={"count": 1})
    await entry(factory, kept["id"], "friend_request", subject_id=gone["id"])
    async with factory() as session:
        async with session.begin():
            session.add(UserWarning(id=generate_uuid(), user_id=UUID(gone["id"]), reason="Tone."))

    deleted = await leaving.request("DELETE", "/api/auth/account", json={"password": PASSWORD})
    assert deleted.status_code == 200, deleted.text

    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(InboxEntry)) == 0
        assert await session.scalar(select(func.count()).select_from(UserWarning)) == 0


async def test_a_merged_guests_entries_are_the_accounts(env):
    """A guest's entries, merged into the account it became, are the
    account's: read across every identity, as shares are (#1430)."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Merged")
    guest_id = generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(User(id=guest_id, display_name="Guest 1", state="merged"))
            await session.flush()
            session.add(IdentityAlias(source_user_id=guest_id, target_user_id=UUID(account["id"])))
    await entry(factory, str(guest_id), "reports_reviewed", params={"count": 4})
    payload = await inbox_payload(factory, account["id"])
    assert [e["count"] for e in payload["entries"]] == [4]
    assert (await client.post("/api/inbox/read", json={"all": True})).json() == {"unreadCount": 0}


async def test_reviewed_reports_are_counted_for_who_the_reporter_is_now(env):
    """A guest's report counts for the account it became, into the one unread
    line; an erased reporter is told nothing; and the line is dated to the
    day, not the decision (R-MOD-20, R-INBOX-06)."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Reporter")
    guest_id, erased_id = generate_uuid(), generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(User(id=guest_id, display_name="Guest 2", state="merged"))
            session.add(User(id=erased_id, display_name="Gone", state="deleted"))
            await session.flush()
            session.add(IdentityAlias(source_user_id=guest_id, target_user_id=UUID(account["id"])))
    decided = datetime(2026, 10, 9, 17, 42, 13, tzinfo=timezone.utc)
    async with factory() as session:
        async with session.begin():
            moved = await count_reviewed_reports(
                session, {UUID(account["id"]): 1, guest_id: 2, erased_id: 1}, now=decided
            )
    assert moved == [UUID(account["id"])]
    async with factory() as session:
        async with session.begin():
            await count_reviewed_reports(session, {guest_id: 1}, now=decided)
        rows = (await session.scalars(select(InboxEntry))).all()
    assert [(row.user_id, row.params) for row in rows] == [(UUID(account["id"]), {"count": 4})]
    assert rows[0].created_at.replace(tzinfo=timezone.utc) == datetime(2026, 10, 9, tzinfo=timezone.utc)


async def test_an_account_holds_one_unread_count_of_reviewed_reports(env, monkeypatch):
    """The index two moderators deciding at once meet at: the second insert
    finds the first's line and counts into it rather than adding another."""
    new_client, factory = env
    account = await register(new_client(), "Counted")
    await entry(factory, account["id"], "reports_reviewed", params={"count": 1})
    original = inbox_service._count_into_unread
    looked = 0

    async def found_nothing_first(*args):
        # As the loser of the race sees it: nothing unread when it looked.
        nonlocal looked
        looked += 1
        return False if looked == 1 else await original(*args)

    monkeypatch.setattr(inbox_service, "_count_into_unread", found_nothing_first)
    async with factory() as session:
        async with session.begin():
            await count_reviewed_reports(session, {UUID(account["id"]): 2})
        counts = (await session.scalars(select(InboxEntry.params))).all()
    assert counts == [{"count": 3}]


async def test_a_guests_warning_follows_it_into_the_account(env):
    """Warned as a guest, then signed in: the warning is the account's to
    answer, and holds the account's seats until it is (R-INBOX-04)."""
    new_client, factory = env
    account = await register(new_client(), "WarnedLater")
    guest_id, warning_id = generate_uuid(), generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(User(id=guest_id, display_name="Guest 3", state="anonymous"))
            await session.flush()
            session.add(UserWarning(id=warning_id, user_id=guest_id, reason="Tone."))
    await entry(factory, str(guest_id), "warning", subject_id=warning_id)

    await SqlAlchemyUserRepository(factory).merge_guest_into_account(str(guest_id), account["id"])

    assert await has_unacknowledged_warning(factory, account["id"])
    async with factory() as session:
        assert await session.scalar(select(UserWarning.user_id)) == UUID(account["id"])
        assert await session.scalar(select(InboxEntry.user_id)) == UUID(account["id"])
    assert (await inbox_payload(factory, account["id"]))["mustAcknowledge"]["id"] == str(warning_id)


async def test_a_guests_inbox_becomes_the_accounts_one_entry_per_fact(env):
    """Merged in, the guest's entries obey the account's rules: one entry per
    drawing, read if either was, and one unread count of reviewed reports.
    Left with the guest, a drawing's entry was outside the index that keeps a
    fact to one entry, and a later share added a second (R-INBOX-05)."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "MergedInbox")
    guest_id, turn_id, other_turn = generate_uuid(), generate_uuid(), generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(User(id=guest_id, display_name="Guest 4", state="anonymous"))
    await entry(factory, str(guest_id), "drawing_shared", subject_id=turn_id)
    await entry(factory, str(guest_id), "drawing_shared", subject_id=other_turn)
    await entry(factory, str(guest_id), "reports_reviewed", params={"count": 2})
    await entry(factory, account["id"], "drawing_shared", subject_id=turn_id, read=True)
    await entry(factory, account["id"], "reports_reviewed", params={"count": 1})

    await SqlAlchemyUserRepository(factory).merge_guest_into_account(str(guest_id), account["id"])

    async with factory() as session:
        rows = (await session.scalars(select(InboxEntry))).all()
        assert {row.user_id for row in rows} == {UUID(account["id"])}
        by_fact = sorted(
            (row.kind, row.subject_id == turn_id, row.read_at is not None, row.params) for row in rows
        )
        assert by_fact == [
            ("drawing_shared", False, False, {}),
            ("drawing_shared", True, True, {}),
            ("reports_reviewed", False, False, {"count": 3}),
        ]
    async with factory() as session:
        async with session.begin():
            again = await add_entry(
                session, user_id=account["id"], kind="drawing_shared", subject_id=turn_id
            )
    assert again is False, "the drawing already has its entry"


async def test_a_decision_landing_mid_merge_is_counted_not_overwritten(env):
    """A moderator's decision holds the account's count open while the guest
    merges in. The merge waits for it and adds the guest's count to what it
    finds; it used to read the count unlocked and write back a sum built on
    the old value, losing the decision. PostgreSQL only: SQLite has one
    writer, so the two cannot interleave."""
    new_client, factory = env
    async with factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("row locks interleave only on PostgreSQL")
    account = await register(new_client(), "RacedMerge")
    guest_id = generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(User(id=guest_id, display_name="Guest 5", state="anonymous"))
    await entry(factory, account["id"], "reports_reviewed", params={"count": 1})
    await entry(factory, str(guest_id), "reports_reviewed", params={"count": 2})

    async with factory() as deciding:
        transaction = await deciding.begin()
        await count_reviewed_reports(deciding, {UUID(account["id"]): 1})
        merging = asyncio.create_task(
            SqlAlchemyUserRepository(factory).merge_guest_into_account(
                str(guest_id), account["id"]
            )
        )
        await asyncio.sleep(0.5)
        assert not merging.done(), "the merge waits for the decision's lock"
        await transaction.commit()
    await asyncio.wait_for(merging, timeout=10)

    async with factory() as session:
        counts = (
            await session.scalars(
                select(InboxEntry.params).where(InboxEntry.kind == "reports_reviewed")
            )
        ).all()
    assert counts == [{"count": 4}]
