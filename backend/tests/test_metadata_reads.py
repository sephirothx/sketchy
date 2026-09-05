"""Metadata reads leave blobs in the database, and history checks who is asking first (#611)."""
from __future__ import annotations

import tracemalloc
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.exc import InvalidRequestError, MissingGreenlet
from sqlalchemy.orm.exc import DetachedInstanceError

from app.api.bug_reports import create_bug_report_router
from app.auth.account_data import (
    create_data_export,
    latest_counted_export,
    list_data_exports,
    process_data_export,
)
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import BugReport, DataExport, generate_uuid
from app.domain_values import BugReportArea
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from app.rooms import RoomManager

from tests.dbfixtures import create_test_db
from tests.test_account_data import record_private_game
from tests.test_bug_reports import PASSWORD

pytestmark = pytest.mark.asyncio


def _capture(engine) -> list[str]:
    statements: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    return statements


def _selects(statements: list[str]) -> list[str]:
    return [s for s in statements if s.lstrip().upper().startswith("SELECT")]


async def _bug_reports(factory, count: int, payload_bytes: int) -> None:
    payload = b"\x89PNG" + bytes(payload_bytes - 4)
    async with factory() as session:
        async with session.begin():
            session.add_all(
                BugReport(
                    id=generate_uuid(),
                    reporter_user_id=None,
                    area=BugReportArea.OTHER.value,
                    severity="minor",
                    summary=f"report {index}",
                    details="",
                    client_context={},
                    server_context={},
                    screenshot_status="ready",
                    screenshot_payload=payload,
                    screenshot_content_type="image/png",
                    screenshot_byte_size=len(payload),
                    screenshot_checksum_sha256="0" * 64,
                    screenshot_width=800,
                    screenshot_height=600,
                )
                for index in range(count)
            )


async def _admin_client(factory, monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "metadata-read-test-secret")
    users = SqlAlchemyUserRepository(factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(users, factory))
    app.include_router(create_bug_report_router(factory, RoomManager()))
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    assert (await client.get("/api/auth/me")).status_code == 200  # a guest, then a claim
    registered = await client.post(
        "/api/auth/register", json={"username": "queueadmin", "password": PASSWORD}
    )
    assert registered.status_code == 200, registered.text
    async with factory() as session:
        async with session.begin():
            from sqlalchemy import update

            from app.db.models import User

            await session.execute(update(User).values(role="admin"))
    return client


async def test_the_bug_report_queue_never_selects_a_screenshot_payload(monkeypatch):
    factory, engine = await create_test_db()
    try:
        client = await _admin_client(factory, monkeypatch)
        await _bug_reports(factory, 20, 1024 * 1024)
        statements = _capture(engine)

        tracemalloc.start()
        response = await client.get("/api/admin/bug-reports")
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert response.status_code == 200
        reports = response.json()["reports"]
        assert len(reports) == 20
        assert all(r["screenshot"]["status"] == "ready" for r in reports)
        assert all(r["screenshot"]["byteSize"] == 1024 * 1024 for r in reports)
        queue_selects = [s for s in _selects(statements) if "bug_reports" in s]
        assert queue_selects, "the queue read must be visible to the capture"
        assert all("screenshot_payload" not in s for s in queue_selects)
        assert peak < 4 * 1024 * 1024, f"the queue read allocated {peak} bytes for 20 MiB of payloads"
        await client.aclose()
    finally:
        await engine.dispose()


async def test_export_status_and_cooldown_reads_never_select_the_artifact():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        account = await users.create_anonymous("Exporter")
        job = await create_data_export(factory, user_id=account.id)
        assert await process_data_export(factory, export_id=job.id)
        statements = _capture(engine)

        jobs = await list_data_exports(factory, user_id=account.id)
        async with factory() as session:
            latest = await latest_counted_export(session, UUID(account.id))
        from app.auth.account_data import export_status_payload

        assert len(jobs) == 1 and jobs[0].status == "ready"
        assert export_status_payload(jobs[0])["downloadUrl"] is not None
        assert latest is not None and latest.id == jobs[0].id
        export_selects = [s for s in _selects(statements) if "data_exports" in s]
        assert export_selects and all(
            "data_exports.artifact " not in s and "data_exports.artifact," not in s
            for s in export_selects
        )
        with pytest.raises((InvalidRequestError, MissingGreenlet, DetachedInstanceError)):
            _ = jobs[0].artifact  # deferred with raiseload: a fetch here is a defect
        async with factory() as session:
            whole = await session.get(DataExport, jobs[0].id)
            assert whole.artifact is not None, "the download path still has the bytes"
    finally:
        await engine.dispose()


async def test_a_stranger_asking_for_a_game_is_refused_after_one_statement():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        player = await users.create_anonymous("Player")
        other = await users.create_anonymous("Other")
        stranger = await users.create_anonymous("Stranger")
        history = SqlAlchemyGameHistoryRepository(factory)
        game_id = await record_private_game(history, owner_id=player.id, other_id=other.id)
        statements = _capture(engine)

        assert await history.get_game_detail(game_id, stranger.id) is None
        refused = _selects(statements)
        # The two alias lookups and the game select with the participation
        # test: no turns, outcomes, guesses, offers or ledger were loaded.
        assert len(refused) == 3, refused
        assert not any("turn_records" in s for s in refused)

        statements.clear()
        detail = await history.get_game_detail(game_id, player.id)
        assert detail is not None and len(detail.turns) == 2
        assert detail.summary.rule_snapshot is not None
        assert not any(" users" in s.lower() and "join" in s.lower() for s in _selects(statements))
        assert not any("FROM users" in s for s in _selects(statements)[1:]), (
            "presentation comes from snapshots; no live user rows are loaded"
        )

        statements.clear()
        summaries = await history.get_user_games(player.id)
        assert [s.id for s in summaries] == [game_id]
        assert summaries[0].rule_snapshot == {}
        list_selects = [s for s in _selects(statements) if "game_records" in s]
        assert list_selects and all("rule_snapshot " not in s and "rule_snapshot," not in s for s in list_selects)
    finally:
        await engine.dispose()
