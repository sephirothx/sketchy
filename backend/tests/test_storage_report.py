"""The live database's footprint, read from the catalogue (#895)."""
from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import text

from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from app.services.storage_report import (
    LARGEST_INDEXES,
    StorageReportUnavailable,
    format_report,
    run_report,
)

from tests.dbfixtures import create_test_db
from tests.test_drawing_reactions import record_game, registered

ON_POSTGRESQL = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")


@pytest.mark.skipif(not ON_POSTGRESQL, reason="sizes are PostgreSQL's catalogue")
async def test_the_report_covers_every_table_per_game_and_names_nobody():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        history = SqlAlchemyGameHistoryRepository(factory)
        drawer = await registered(users, "Secretdrawer")
        guesser = await registered(users, "Secretguesser")
        await record_game(history, drawer=drawer.id, reactor=guesser.id, reactions="default")
        async with factory() as session:
            await session.execute(text("ANALYZE"))
            await session.commit()

        report = await run_report(factory)

        tables = {table.table: table for table in report.tables}
        assert {"game_records", "turn_drawings", "room_messages", "users"} <= set(tables)
        assert report.finished_games == 1
        assert tables["game_records"].rows == 1
        assert tables["turn_drawings"].total_bytes > 0
        assert report.bytes_per_finished_game is not None and report.bytes_per_finished_game > 0
        assert 0 < len(report.largest_indexes) <= LARGEST_INDEXES
        # Safe to paste into an issue: names of tables and indexes, numbers.
        printed = format_report(report) + json.dumps(report.as_json())
        for personal in ("Secretdrawer", "secretdrawer", "Secretguesser", "Reactions room", "lighthouse"):
            assert personal not in printed
    finally:
        await engine.dispose()


@pytest.mark.skipif(ON_POSTGRESQL, reason="the refusal is SQLite's")
async def test_sqlite_is_refused_rather_than_guessed_at():
    factory, engine = await create_test_db()
    try:
        with pytest.raises(StorageReportUnavailable):
            await run_report(factory)
    finally:
        await engine.dispose()
