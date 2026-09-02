"""What the server records about itself, and who is allowed to look."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.operations import create_operations_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import AuditEvent, Base, RuntimeEvent, RuntimeStatsDaily, User
from app.domain_values import RuntimeEventType, UserRole
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.runtime_metrics import (
    RuntimeMetrics,
    flush_events,
    metrics,
    purge_expired_events,
)
from app.auth.mail import queue_email
from app.request_timing import RequestTimingMiddleware
from app.domain_values import EmailTemplate
from app.services.queue_depths import QueueDepths
from app.services.readiness import LoopHealth, ReadinessProbe
from app.services.telemetry import RING_MINUTES, Telemetry


pytestmark = pytest.mark.asyncio
PASSWORD = "a-good-password"
# What the `env` fixture wired into the router, for tests that drive it.
INJECTED: dict[str, object] = {}


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "analytics-test-secret")
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    # Outermost, as in main.py: it is what gives the request the id the
    # audit ledger and the log lines share.
    app.add_middleware(RequestTimingMiddleware, telemetry=Telemetry())
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    # Fresh signal stores rather than the process's, so nothing another test
    # (or this test module's own imports) recorded leaks into an assertion.
    INJECTED["readiness"] = ReadinessProbe(factory)
    INJECTED["telemetry"] = Telemetry()
    INJECTED["queues"] = QueueDepths(factory, cache_seconds=0.0)
    app.include_router(
        create_operations_router(
            factory,
            readiness=INJECTED["readiness"],
            telemetry=INJECTED["telemetry"],
            queue_depths=INJECTED["queues"],
            mail_sweep_seconds=30.0,
        )
    )

    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )
        clients.append(client)
        return client

    # The module-level recorder is shared; a test that inherits another test's
    # buffer is a test that passes for the wrong reason.
    metrics.drain()
    try:
        yield new_client, factory
    finally:
        metrics.drain()
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


async def promote(factory, user_id: str) -> None:
    async with factory() as session:
        async with session.begin():
            user = await session.get(User, UUID(user_id))
            user.role = UserRole.ADMIN.value


async def test_observations_become_rows_and_daily_totals(env):
    _, factory = env
    recorder = RuntimeMetrics()
    day = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    recorder.record(RuntimeEventType.ROOM_CREATED, room_id="r1", now=day)
    recorder.record(
        RuntimeEventType.ROOM_CLOSED, room_id="r1", value=90, now=day
    )
    recorder.record(
        RuntimeEventType.ROOM_CLOSED, room_id="r2", value=310, now=day
    )

    assert await flush_events(factory, recorder=recorder) == 3
    # Draining is what makes a second flush a no-op rather than a duplicate.
    assert await flush_events(factory, recorder=recorder) == 0

    async with factory() as session:
        assert await session.scalar(select(func.count(RuntimeEvent.id))) == 3
        closed = await session.get(RuntimeStatsDaily, (day.date(), "room.closed"))
        assert closed.occurrences == 2
        assert closed.value_sum == 400
        # The longest-lived room, which an average would hide.
        assert closed.value_max == 310


async def test_retention_keeps_the_trend_and_drops_the_detail(env):
    _, factory = env
    recorder = RuntimeMetrics()
    now = datetime(2026, 8, 24, tzinfo=timezone.utc)
    recorder.record(
        RuntimeEventType.PLAYER_JOINED, now=now - timedelta(days=45)
    )
    recorder.record(RuntimeEventType.PLAYER_JOINED, now=now - timedelta(days=1))
    await flush_events(factory, recorder=recorder)

    removed = await purge_expired_events(factory, days=30, now=now)

    assert removed == 1
    async with factory() as session:
        assert await session.scalar(select(func.count(RuntimeEvent.id))) == 1
        # The aggregate for the purged day is untouched: what is lost is the
        # ability to ask about one minute, not the shape of the month.
        surviving = await session.scalar(
            select(func.count(RuntimeStatsDaily.metric))
        )
        assert surviving == 2


async def test_a_full_buffer_drops_the_oldest_and_says_so(env):
    """Losing observations beats losing the server that makes them."""
    recorder = RuntimeMetrics(max_buffered=3)
    for _ in range(5):
        recorder.record(RuntimeEventType.PLAYER_JOINED)

    assert recorder.buffered == 3
    assert recorder.dropped_events == 2
    # The totals still count everything that happened, so the gap is visible
    # rather than merely absent.
    assert recorder.totals()["player.joined"] == 5


async def test_gauges_are_set_rather_than_accumulated(env):
    """An accumulating gauge drifts once and then lies for ever."""
    recorder = RuntimeMetrics()
    recorder.observe(rooms=4, players=17)
    recorder.observe(rooms=2, players=9)

    assert recorder.gauges.rooms == 2
    assert recorder.gauges.players == 9
    assert recorder.gauges.peak_rooms == 4
    assert recorder.gauges.peak_players == 17


async def test_the_operator_views_are_closed_to_everyone_else(env):
    new_client, factory = env
    player = new_client()
    await register(player, "OrdinaryPlayer")

    for path in (
        "/api/admin/metrics",
        "/api/admin/metrics/daily",
        "/api/admin/metrics/events",
        "/api/admin/audit",
    ):
        response = await player.get(path)
        # 404 rather than 403: whether this deployment has an admin page is not
        # something an ordinary player needs to learn.
        assert response.status_code == 404, path

    anonymous = new_client()
    assert (await anonymous.get("/api/admin/metrics")).status_code == 401


async def test_an_administrator_sees_live_counts_and_game_outcomes(env):
    new_client, factory = env
    admin = new_client()
    account = await register(admin, "Operator")
    await promote(factory, account["id"])
    metrics.observe(rooms=3, players=11, active_games=2)

    body = (await admin.get("/api/admin/metrics")).json()

    assert body["live"] == {"rooms": 3, "players": 11, "activeGames": 2}
    assert body["peak"]["players"] >= 11
    assert body["games"] == {"finished": 0, "abandoned": 0, "shutdown": 0}


async def test_scraping_is_off_until_a_token_is_configured(env, monkeypatch):
    new_client, _ = env
    anyone = new_client()

    assert (await anyone.get("/metrics")).status_code == 404

    monkeypatch.setenv("METRICS_TOKEN", "scrape-me")
    assert (await anyone.get("/metrics")).status_code == 401
    authorized = await anyone.get(
        "/metrics", headers={"authorization": "Bearer scrape-me"}
    )
    assert authorized.status_code == 200
    assert "sketchy_rooms_live" in authorized.text
    assert authorized.headers["content-type"].startswith("text/plain")


async def test_looking_at_one_player_is_itself_recorded(env):
    """The per-player view is a surveillance surface on the game's own players."""
    new_client, factory = env
    admin, subject = new_client(), new_client()
    operator = await register(admin, "Watcher")
    watched = await register(subject, "Watched")
    await promote(factory, operator["id"])

    response = await admin.get(f"/api/admin/players/{watched['id']}/activity")

    assert response.status_code == 200
    assert response.json()["player"]["displayName"] == "Watched"
    async with factory() as session:
        event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == "admin.player_activity_viewed"
            )
        )
        assert event is not None
        assert event.actor_user_id == UUID(operator["id"])
        assert event.target_id == watched["id"]


async def test_the_ledger_can_be_asked_about_one_subject(env):
    """The question #397's target pair exists to answer."""
    new_client, factory = env
    admin = new_client()
    operator = await register(admin, "Auditor")
    await promote(factory, operator["id"])
    async with factory() as session:
        async with session.begin():
            from app.db.models import generate_uuid

            session.add_all(
                [
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="prompt_content_report.resolved",
                        target_type="prompt_list",
                        target_id="list-one",
                        details={},
                    ),
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="prompt_content_report.resolved",
                        target_type="prompt_list",
                        target_id="list-two",
                        details={},
                    ),
                ]
            )

    filtered = await admin.get(
        "/api/admin/audit?targetType=prompt_list&targetId=list-one"
    )

    entries = filtered.json()["entries"]
    assert [entry["targetId"] for entry in entries] == ["list-one"]


async def test_an_abandoned_game_counts_turns_but_not_the_game(env):
    """Otherwise a room that keeps emptying inflates everyone's totals, and
    the average score - which divides by games played - drifts upward."""
    from app.services.user_stats_projection import increment_user_stats_projection
    from app.db.models import UserStatsDaily

    _, factory = env
    async with factory() as session:
        async with session.begin():
            player = User(
                username="Statistician",
                password_hash="hash",
                display_name="Statistician",
                state="registered",
            )
            session.add(player)
            await session.flush()
            player_id = player.id

    day = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    async with factory() as session:
        async with session.begin():
            await increment_user_stats_projection(
                session,
                finished_at=day,
                participants=[(player_id, 300, 1)],
                turn_drawer_ids=[player_id, player_id],
                guess_user_ids=[player_id],
                counts_as_played=False,
            )

    async with factory() as session:
        row = await session.get(UserStatsDaily, (player_id, day.date()))
        assert row.turns_played == 2
        assert row.prompts_guessed == 1
        assert row.drawings_made == 2
        assert row.games_played == 0
        assert row.games_won == 0
        assert row.total_score == 0


async def test_the_account_payload_says_which_staff_surfaces_to_offer(env):
    """The client cannot offer a door it does not know exists - and must not
    offer one that will not open."""
    new_client, factory = env
    player, operator = new_client(), new_client()
    await register(player, "JustAPlayer")
    account = await register(operator, "Staff")

    assert (await player.get("/api/auth/me")).json()["role"] == "user"
    assert (await operator.get("/api/auth/me")).json()["role"] == "user"

    await promote(factory, account["id"])

    assert (await operator.get("/api/auth/me")).json()["role"] == "admin"
    # The role in the payload decides what is shown; it never decides what is
    # allowed. An ordinary player asking directly still gets nothing.
    assert (await player.get("/api/admin/metrics")).status_code == 404


async def test_the_ledger_names_its_subjects_without_storing_the_names(env):
    """A page of UUIDs is unreadable, but a name copied into an append-only
    table is personal data erasure cannot reach. Resolved on read, so deleting
    an account stops the ledger naming them while the entry still stands."""
    from sqlalchemy import func

    from app.auth.account_data import DELETED_DISPLAY_NAME
    from app.db.models import generate_uuid

    new_client, factory = env
    admin, subject = new_client(), new_client()
    operator = await register(admin, "LedgerReader")
    named = await register(subject, "NamedSubject")
    await promote(factory, operator["id"])

    async with factory() as session:
        async with session.begin():
            session.add(
                AuditEvent(
                    id=generate_uuid(),
                    event_type="ban.created",
                    actor_user_id=UUID(operator["id"]),
                    target_user_id=UUID(named["id"]),
                    target_type="user",
                    target_id=named["id"],
                    details={},
                )
            )

    # By event type, not by position: deleting the account below writes its own
    # entry, which would otherwise become the newest one.
    entry = (
        await admin.get("/api/admin/audit?eventType=ban.created")
    ).json()["entries"][0]
    assert entry["actorName"] == "LedgerReader"
    assert entry["targetName"] == "NamedSubject"
    # The row itself holds ids and nothing else - the name is never written.
    async with factory() as session:
        stored = await session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "ban.created")
        )
        assert "NamedSubject" not in str(stored.details)
        assert "NamedSubject" not in (stored.target_id or "")

    # Erase the subject. The entry survives; the name it renders does not.
    deleted = await subject.request(
        "DELETE", "/api/auth/account", json={"password": PASSWORD}
    )
    assert deleted.status_code == 200

    after = (
        await admin.get("/api/admin/audit?eventType=ban.created")
    ).json()["entries"][0]
    assert after["targetName"] == DELETED_DISPLAY_NAME
    assert after["actorName"] == "LedgerReader"
    async with factory() as session:
        assert await session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.event_type == "ban.created"
            )
        ) == 1


async def test_an_id_written_without_dashes_still_finds_its_name(env):
    """Casting a UUID to text drops the dashes, so a backfilled entry spells
    the same account differently from one written by code. Both have to
    resolve, or half the ledger renders as raw ids."""
    from app.db.models import generate_uuid

    new_client, factory = env
    admin, subject = new_client(), new_client()
    operator = await register(admin, "SpellingAdmin")
    named = await register(subject, "SpellingSubj")
    await promote(factory, operator["id"])

    dashed = named["id"]
    bare = dashed.replace("-", "")
    assert bare != dashed

    async with factory() as session:
        async with session.begin():
            session.add_all(
                AuditEvent(
                    id=generate_uuid(),
                    event_type=event_type,
                    actor_user_id=UUID(operator["id"]),
                    target_user_id=UUID(dashed),
                    target_type="user",
                    target_id=spelling,
                    details={},
                )
                for event_type, spelling in (
                    ("ban.created", dashed),
                    ("ban.revoked", bare),
                )
            )

    entries = (await admin.get("/api/admin/audit")).json()["entries"]
    by_type = {entry["eventType"]: entry for entry in entries}

    assert by_type["ban.created"]["targetName"] == "SpellingSubj"
    assert by_type["ban.revoked"]["targetName"] == "SpellingSubj"
    # Each is answered in the spelling it was stored in, so the id column keeps
    # showing what is actually on the row.
    assert by_type["ban.revoked"]["targetId"] == bare


async def test_the_admin_payload_carries_the_process_signals(env):
    """The page's numbers: rates and percentiles over the window, sixty-point
    series behind them, and the queues and loops the scrape also sees."""
    new_client, factory = env
    admin = new_client()
    account = await register(admin, "Operator")
    await promote(factory, account["id"])
    store: Telemetry = INJECTED["telemetry"]  # type: ignore[assignment]
    store.http_request("GET", "/api/rooms", 200, 0.02)
    store.socket_event("draw", "ok", 0.001)
    store.record_loop_lag(0.004)

    body = (await admin.get("/api/admin/metrics")).json()

    assert body["windowMinutes"] == 5
    assert body["http"]["total"] == 1
    assert body["http"]["p95Ms"] is not None
    assert body["socket"]["total"] == 1
    assert body["process"]["loopLagMs"] == 4.0
    assert body["process"]["uptimeSeconds"] >= 0
    assert body["database"]["readiness"] is None
    assert body["database"]["historyWritesAbandoned"]["total"] == 0
    assert body["queues"]["mailOutbox"] == {
        "pending": 0,
        "oldestSeconds": None,
        "sweepSeconds": 30.0,
    }
    assert body["queues"]["dataExports"] == {"pending": 0, "oldestSeconds": None}
    assert body["loops"] == {}
    assert all(len(points) == RING_MINUTES for points in body["series"].values())


async def test_queued_mail_shows_as_depth_and_age(env):
    new_client, factory = env
    admin = new_client()
    account = await register(admin, "Operator")
    await promote(factory, account["id"])
    async with factory() as session:
        async with session.begin():
            queue_email(
                session,
                to_address="someone@example.test",
                template=list(EmailTemplate)[0],
                payload={},
            )

    body = (await admin.get("/api/admin/metrics")).json()

    assert body["queues"]["mailOutbox"]["pending"] == 1
    assert body["queues"]["mailOutbox"]["oldestSeconds"] >= 0


async def test_a_supervised_loop_that_stopped_is_reported_as_such(env):
    new_client, factory = env
    admin = new_client()
    account = await register(admin, "Operator")
    await promote(factory, account["id"])
    probe: ReadinessProbe = INJECTED["readiness"]  # type: ignore[assignment]

    async def done() -> None:
        return None

    import asyncio

    task = asyncio.create_task(done())
    await task
    health = LoopHealth("mail_delivery")
    health.record_failure()
    probe.supervise("mail_delivery", task, health)

    body = (await admin.get("/api/admin/metrics")).json()

    assert body["loops"]["mail_delivery"]["running"] is False
    assert body["loops"]["mail_delivery"]["consecutiveFailures"] == 1
    assert body["loops"]["mail_delivery"]["secondsSinceSuccess"] is None


async def test_the_scrape_carries_every_new_family(env, monkeypatch):
    new_client, factory = env
    monkeypatch.setenv("METRICS_TOKEN", "scrape-me")
    store: Telemetry = INJECTED["telemetry"]  # type: ignore[assignment]
    probe: ReadinessProbe = INJECTED["readiness"]  # type: ignore[assignment]
    store.http_request("GET", "/api/rooms", 200, 0.02)
    store.socket_event("draw", "ok", 0.001)
    store.db_query(0.001)
    store.record_loop_lag(0.001)
    store.history_write_abandoned("game", "timeout")
    await probe.check_database()

    async def forever() -> None:
        import asyncio

        await asyncio.sleep(3600)

    import asyncio

    task = asyncio.create_task(forever())
    health = LoopHealth("presence_broadcast")
    health.record_success()
    probe.supervise("presence_broadcast", task, health)
    async with factory() as session:
        async with session.begin():
            queue_email(
                session,
                to_address="someone@example.test",
                template=list(EmailTemplate)[0],
                payload={},
            )

    try:
        text = (
            await new_client().get("/metrics", headers={"authorization": "Bearer scrape-me"})
        ).text
    finally:
        task.cancel()

    for needle in (
        'sketchy_http_requests_total{method="GET",route="/api/rooms",status_class="2xx"} 1',
        'sketchy_http_request_duration_seconds_bucket{route="/api/rooms",le="+Inf"} 1',
        'sketchy_socket_events_total{event="draw",outcome="ok"} 1',
        "sketchy_event_loop_lag_seconds_count 1",
        "sketchy_db_queries_total 1",
        'sketchy_history_writes_abandoned_total{kind="game",reason="timeout"} 1',
        "sketchy_mail_outbox_pending 1",
        "sketchy_data_exports_pending 0",
        'sketchy_loop_running{loop="presence_broadcast"} 1',
        'sketchy_loop_consecutive_failures{loop="presence_broadcast"} 0',
        "sketchy_db_ready 1",
        "sketchy_process_uptime_seconds ",
        # The nine that were there before are still there.
        "sketchy_rooms_live ",
    ):
        assert needle in text, needle
    # SQLite keeps no pool count, and the family is absent rather than zero.
    assert "sketchy_db_pool_" not in text


async def test_the_ledger_row_and_the_response_share_one_request_id(env):
    """One id, quoted by the client, in the response, and on the audit row."""
    new_client, factory = env
    admin, subject = new_client(), new_client()
    operator = await register(admin, "Watcher")
    watched = await register(subject, "Watched")
    await promote(factory, operator["id"])

    # No header sent: the id is the one the middleware minted, which the
    # ledger can only know by reading the request's context rather than
    # minting a second one of its own.
    response = await admin.get(f"/api/admin/players/{watched['id']}/activity")

    minted = response.headers["x-request-id"]
    async with factory() as session:
        event = await session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "admin.player_activity_viewed")
        )
        assert event.request_id == minted


async def test_a_database_outage_costs_the_scrape_only_the_queue_family(env, monkeypatch):
    """The scrape is read *during* an outage; it must not go down with the database."""
    import asyncio

    from app.api import operations

    new_client, _ = env
    monkeypatch.setenv("METRICS_TOKEN", "scrape-me")
    depths: QueueDepths = INJECTED["queues"]  # type: ignore[assignment]

    async def refused():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(depths, "_query", refused)
    response = await new_client().get("/metrics", headers={"authorization": "Bearer scrape-me"})
    assert response.status_code == 200
    assert "sketchy_event_loop_lag_seconds" in response.text
    assert "sketchy_mail_outbox_pending" not in response.text

    async def hung():
        await asyncio.sleep(3600)

    monkeypatch.setattr(depths, "_query", hung)
    monkeypatch.setattr(operations, "QUEUE_SCRAPE_TIMEOUT_SECONDS", 0.05)
    response = await new_client().get("/metrics", headers={"authorization": "Bearer scrape-me"})
    assert response.status_code == 200
    assert "sketchy_mail_outbox_pending" not in response.text
