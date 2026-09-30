"""The application's own queries use the partial indexes they were given (#554).

A partial index only matches a plan whose predicate names the literal its
predicate names; a value bound as a parameter, which is what SQLAlchemy does
by default and what asyncpg prepares, does not. These explain the real
statements, with their real binding, and read the plan back.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import re

import pytest

from app.db.models import Base

from tests.dbfixtures import create_test_db, create_test_engine


ON_POSTGRESQL = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")


def test_the_indexes_named_here_exist_in_the_metadata():
    names = {index.name for table in Base.metadata.sorted_tables for index in table.indexes}
    assert {
        "ix_room_messages_lobby_newest",
        "ix_user_bans_unrevoked_newest",
        "ix_email_outbox_sent_at_sent",
        "ix_audit_events_type_created_at",
    } <= names
    assert "ix_audit_events_event_type" not in names, "replaced by the composite that leads with it"


async def _plan_of(session, statement) -> str:
    """Run the statement the way the application does, then explain exactly
    what reached the driver: the same text, the same bound parameters."""
    from sqlalchemy import event

    captured: list[tuple[str, tuple]] = []
    connection = await session.connection()
    sync_connection = await connection.get_raw_connection()
    assert sync_connection is not None

    def before(conn, cursor, statement_text, parameters, context, executemany):
        captured.append((statement_text, parameters))

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", before)
    try:
        await session.execute(statement)
    finally:
        event.remove(engine, "before_cursor_execute", before)
    statement_text, parameters = captured[-1]
    raw = (
        await connection.exec_driver_sql("EXPLAIN (FORMAT TEXT) " + statement_text, parameters)
    ).scalars().all()
    return "\n".join(raw)


async def _seed(factory, now: datetime) -> None:
    """Enough rows, skewed the way production is, for the planner to have a
    choice: an empty table is a trivial sort whatever the indexes say."""
    from sqlalchemy import insert

    from app.db.models import EmailOutboxEntry, RoomMessage, User, UserBan, generate_uuid

    async with factory() as session:
        async with session.begin():
            speaker = generate_uuid()
            session.add(User(id=speaker, display_name="Speaker"))
            await session.flush()
            await session.execute(
                insert(RoomMessage),
                [
                    {
                        "id": generate_uuid(),
                        "room_instance_id": None if i % 40 == 0 else generate_uuid(),
                        "sender_user_id": speaker,
                        "sender_player_id": None if i % 40 == 0 else generate_uuid(),
                        "sender_display_name_snapshot": "S",
                        "sender_is_anonymous_snapshot": True,
                        "is_spectator": False,
                        "message_kind": "chat",
                        "audience": "lobby" if i % 40 == 0 else "room",
                        "audience_user_ids": [],
                        "text": f"line {i}",
                        "created_at": now - timedelta(seconds=i),
                        "expires_at": now + timedelta(days=29),
                    }
                    for i in range(4_000)
                ],
            )
            await session.execute(
                insert(EmailOutboxEntry),
                [
                    {
                        "id": generate_uuid(),
                        "user_id": speaker,
                        "to_address": "a@b.c",
                        "template": "verify_email",
                        "payload": {},
                        "state": "pending" if i % 100 == 0 else "sent",
                        "attempts": 1,
                        "next_attempt_at": now,
                        "sent_at": None if i % 100 == 0 else now - timedelta(days=i % 60),
                        "created_at": now - timedelta(days=i % 60),
                    }
                    for i in range(4_000)
                ],
            )
            await session.execute(
                insert(UserBan),
                [
                    {
                        "id": generate_uuid(),
                        "user_id": speaker,
                        "banned_by_user_id": speaker,
                        "reason": "spam",
                        "revoked_at": None if i % 20 == 0 else now - timedelta(minutes=i),
                        "expires_at": None,
                        "created_at": now - timedelta(minutes=i),
                    }
                    for i in range(4_000)
                ],
            )
    await _analyze(factory, ("room_messages", "email_outbox", "user_bans"))


async def _analyze(factory, tables: tuple[str, ...]) -> None:
    """Statistics are the owner's to refresh (#896): as the application role
    ANALYZE skips each table with a warning, and the plans stay generic."""
    from sqlalchemy import text

    owner_url = os.environ.get("TEST_OWNER_DATABASE_URL")
    if owner_url:
        owner = create_test_engine(owner_url)
        try:
            async with owner.connect() as connection:
                for table in tables:
                    await connection.execute(text(f"ANALYZE {table}"))
                await connection.commit()
        finally:
            await owner.dispose()
    else:
        async with factory() as session:
            for table in tables:
                await session.execute(text(f"ANALYZE {table}"))
            await session.commit()


@pytest.mark.skipif(not ON_POSTGRESQL, reason="plans are PostgreSQL's")
async def test_the_lobby_restore_and_the_sent_purge_use_their_partial_indexes():
    from sqlalchemy import func, literal, select

    from app.db.models import EmailOutboxEntry, RoomMessage, UserBan
    from app.auth.bans import active_ban_filter
    from app.domain_values import EmailOutboxState

    factory, engine = await create_test_db()
    try:
        now = datetime.now(timezone.utc)
        await _seed(factory, now)
        async with factory() as session:
            lobby = (
                select(RoomMessage.id)
                .where(
                    RoomMessage.audience == literal("lobby", literal_execute=True),
                    RoomMessage.expires_at > now,
                )
                .order_by(RoomMessage.created_at.desc(), RoomMessage.id.desc())
                .limit(50)
            )
            assert "ix_room_messages_lobby_newest" in await _plan_of(session, lobby)

            # A bound value matches too while PostgreSQL plans each execution
            # with the value in hand; a generic plan for a prepared statement
            # cannot prove `audience = $1` implies the predicate, which is why
            # the application inlines the literal rather than relying on it.
            sent = (
                select(EmailOutboxEntry.id)
                .where(
                    EmailOutboxEntry.state
                    == literal(EmailOutboxState.SENT.value, literal_execute=True),
                    EmailOutboxEntry.sent_at <= now - timedelta(days=30),
                )
                .order_by(EmailOutboxEntry.sent_at, EmailOutboxEntry.id)
                .limit(500)
            )
            assert "ix_email_outbox_sent_at_sent" in await _plan_of(session, sent)

            bans = (
                select(UserBan.id)
                .where(*active_ban_filter(now))
                .order_by(UserBan.created_at.desc())
                .limit(50)
            )
            assert "ix_user_bans_unrevoked_newest" in await _plan_of(session, bans)
            assert func is not None
    finally:
        await engine.dispose()


@pytest.mark.skipif(not ON_POSTGRESQL, reason="plans are PostgreSQL's")
async def test_a_history_page_is_an_ordered_walk_of_the_players_seats():
    """#477: a profile's page reads down `ix_game_participants_user_history`
    and stops, rather than gathering every game the player sat in and sorting
    them first - the first page and a deep one alike, for the owner, a visitor
    and a signed-in stranger, whose private-game filter is in the index rather
    than probed per row. Sequential and bitmap scans are switched off, since
    reading a whole slice and sorting it is the cheaper plan at the sizes a
    test can seed and not at a real player's: what is proven is that the index
    serves each run's order, so no Sort sits inside a run."""
    from sqlalchemy import event, insert

    from app.db.models import GameParticipant, GameRecord, User, generate_uuid
    from app.repositories.sqlalchemy import SqlAlchemyGameHistoryRepository

    factory, engine = await create_test_db()
    try:
        player, stranger = generate_uuid(), generate_uuid()
        others = [generate_uuid() for _ in range(20)]
        start = datetime(2026, 6, 1, tzinfo=timezone.utc)
        games, seats = [], []
        # The player sits in one game of every ten, so their seats are a
        # slice of the table and the history is a few pages deep.
        for index in range(2_000):
            game_id, finished_at = generate_uuid(), start + timedelta(minutes=index)
            games.append(
                {
                    "id": game_id,
                    "payload_hash": f"walk-{index}",
                    "room_name": "Walk",
                    "scoring_mode": "default",
                    "hint_mode": "none",
                    "drawing_seconds": 60,
                    "total_rounds": 1,
                    "player_count": 1,
                    "started_at": finished_at - timedelta(minutes=1),
                    "finished_at": finished_at,
                    "visibility": "public" if index % 3 else "private",
                }
            )
            seats.append(
                {
                    "id": generate_uuid(),
                    "game_id": game_id,
                    "user_id": player if index % 10 == 0 else others[index % 20],
                    "finished_at": finished_at,
                    "visibility": games[-1]["visibility"],
                    "final_score": 0,
                    "final_rank": 1,
                }
            )
        async with factory() as session:
            async with session.begin():
                session.add_all(
                    [User(id=player, display_name="Walker"), User(id=stranger, display_name="Visitor")]
                    + [User(id=other, display_name=f"Other {n}") for n, other in enumerate(others)]
                )
                await session.flush()
                await session.execute(insert(GameRecord), games)
                await session.execute(insert(GameParticipant), seats)
        await _analyze(factory, ("game_records", "game_participants"))

        captured: list[tuple[str, tuple]] = []

        def before(conn, cursor, statement_text, parameters, context, executemany):
            if "game_participants.finished_at DESC" in statement_text:
                captured.append((statement_text, parameters))

        history = SqlAlchemyGameHistoryRepository(factory)
        event.listen(engine.sync_engine, "before_cursor_execute", before)
        try:
            for viewer in (player, None, stranger):
                viewer_id = None if viewer is None else str(viewer)
                first = await history.get_user_games(
                    str(player), limit=20, requesting_user_id=viewer_id
                )
                await history.get_user_games(
                    str(player), limit=20, cursor=first.next_cursor,
                    requesting_user_id=viewer_id,
                )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", before)

        assert len(captured) == 6
        for statement_text, parameters in captured:
            async with engine.connect() as connection:
                await connection.exec_driver_sql("SET enable_seqscan = off")
                await connection.exec_driver_sql("SET enable_bitmapscan = off")
                plan = "\n".join(
                    (
                        await connection.exec_driver_sql(
                            "EXPLAIN (FORMAT TEXT) " + statement_text, parameters
                        )
                    ).scalars().all()
                )
            assert "ix_game_participants_user_history" in plan, plan
            assert "Seq Scan" not in plan, plan
            # Anything under the Append is a run; a Sort node there would be
            # one run sorting its whole slice of the table. Above it the runs
            # are merged - a Merge Append, or a Sort over a page from each.
            runs = plan.split("Append", 1)[1] if "Append" in plan else plan
            assert not re.search(r"->\s+Sort\b", runs), plan
            assert "Append" in plan or "Sort" not in plan, plan
    finally:
        await engine.dispose()


def _rows_read(node: dict) -> int:
    """Rows every index scan under `node` read, summed over its loops - the
    ones it produced and the ones a filter on it threw away, which is where a
    per-row probe that finds nothing hides its cost."""
    own = (
        sum(
            node.get(key, 0)
            for key in ("Actual Rows", "Rows Removed by Filter", "Rows Removed by Index Recheck")
        )
        * node.get("Actual Loops", 1)
        if "Index" in node.get("Node Type", "")
        else 0
    )
    return own + sum(_rows_read(child) for child in node.get("Plans", ()))


@pytest.mark.skipif(not ON_POSTGRESQL, reason="plans are PostgreSQL's")
async def test_shared_private_games_cost_the_smaller_private_history():
    """#1371 review: the private games a signed-in viewer shared with the
    subject are a semi-join of two private runs, and the planner has to lead
    with the shorter. Pinned to one side - a probe PostgreSQL cannot reorder -
    a prolific private-room player would pay their whole private history to
    open any stranger's profile, or a stranger the subject's. Either way
    round, with nothing shared, a page here reads a handful of rows, not the
    thousands one side holds; a probe fenced with `OFFSET 0` fails it."""
    import json

    from sqlalchemy import event, insert

    from app.db.models import GameParticipant, GameRecord, User, generate_uuid
    from app.repositories.sqlalchemy import SqlAlchemyGameHistoryRepository

    factory, engine = await create_test_db()
    try:
        heavy, light, friend = generate_uuid(), generate_uuid(), generate_uuid()
        start = datetime(2026, 6, 1, tzinfo=timezone.utc)
        games, seats = [], []
        # 3,000 private games the heavy player shared with a friend, five the
        # light player did: heavy and light never met.
        for index in range(3_005):
            game_id, finished_at = generate_uuid(), start + timedelta(minutes=index)
            player = light if index % 601 == 0 else heavy
            games.append(
                {
                    "id": game_id,
                    "payload_hash": f"shared-{index}",
                    "room_name": "Private",
                    "scoring_mode": "default",
                    "hint_mode": "none",
                    "drawing_seconds": 60,
                    "total_rounds": 1,
                    "player_count": 2,
                    "started_at": finished_at - timedelta(minutes=1),
                    "finished_at": finished_at,
                    "visibility": "private",
                }
            )
            for user_id in (player, friend):
                seats.append(
                    {
                        "id": generate_uuid(),
                        "game_id": game_id,
                        "user_id": user_id,
                        "finished_at": finished_at,
                        "visibility": "private",
                        "final_score": 0,
                        "final_rank": 1,
                    }
                )
        async with factory() as session:
            async with session.begin():
                session.add_all(
                    [
                        User(id=heavy, display_name="Heavy"),
                        User(id=light, display_name="Light"),
                        User(id=friend, display_name="Friend"),
                    ]
                )
                await session.flush()
                await session.execute(insert(GameRecord), games)
                await session.execute(insert(GameParticipant), seats)
        await _analyze(factory, ("game_records", "game_participants", "users"))

        captured: list[tuple[str, tuple]] = []

        def before(conn, cursor, statement_text, parameters, context, executemany):
            if "game_participants.finished_at DESC" in statement_text:
                captured.append((statement_text, parameters))

        history = SqlAlchemyGameHistoryRepository(factory)
        event.listen(engine.sync_engine, "before_cursor_execute", before)
        try:
            for viewer, subject in ((heavy, light), (light, heavy)):
                page = await history.get_user_games(str(subject), requesting_user_id=str(viewer))
                assert page.games == ()
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", before)

        assert len(captured) == 2
        for statement_text, parameters in captured:
            async with engine.connect() as connection:
                [raw] = (
                    await connection.exec_driver_sql(
                        "EXPLAIN (ANALYZE, FORMAT JSON) " + statement_text, parameters
                    )
                ).scalars().all()
            plan = (json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"]
            assert _rows_read(plan) < 100, json.dumps(plan, indent=1)
    finally:
        await engine.dispose()
