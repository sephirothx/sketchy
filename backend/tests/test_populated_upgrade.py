"""Every revision after the baseline runs over rows, not only over an empty schema (#893).

`tests/populated_upgrade.py` says how the rows were made. Here the schema is
built to the revision they were written at, the rows are loaded, the chain is
upgraded to head, and then the database is asked the questions the product
asks: every history surface reads back, and the integrity audit finds nothing
wrong. A revision that cannot run over these rows - a `NOT NULL` without a
backfill, a constraint the rows break, a backfill that loses them - fails
here the day it is written.
"""
from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import upgrade_database
from app.db.models import GamePromptSource, GameRecord, TurnDrawing, User

from tests.dbfixtures import create_test_engine
from tests.populated_upgrade import (
    FIXTURE_PATH,
    FIXTURE_REVISION,
    ScratchDatabase,
    load_fixture,
    migrate_to,
)

ON_POSTGRESQL = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")


def test_the_fixture_is_rows_only_and_names_its_revision():
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    assert f"at revision {FIXTURE_REVISION}" in text.splitlines()[0]
    statements = [line for line in text.splitlines() if line and not line.startswith("--")]
    assert statements and all(
        line.startswith(("INSERT INTO ", "SELECT pg_catalog.setval(")) or not line[0].isalpha()
        for line in statements
    )
    assert "CREATE " not in text and "ALTER " not in text


@pytest.mark.skipif(not ON_POSTGRESQL, reason="the dump is PostgreSQL's")
async def test_the_populated_baseline_upgrades_to_head_and_reads_back_whole():
    from app.auth.account_data import get_data_export
    from app.repositories.sqlalchemy import (
        SqlAlchemyGameHistoryRepository,
        SqlAlchemyPromptListRepository,
    )
    from app.services.friends import FriendService
    from app.services.integrity_audit import AuditBudget, IntegrityAudit

    scratch = ScratchDatabase(os.environ.get("TEST_OWNER_DATABASE_URL") or os.environ["TEST_DATABASE_URL"])
    url = await scratch.create()
    engine = create_test_engine(url, role="migration")
    try:
        await migrate_to(engine, FIXTURE_REVISION)
        await load_fixture(url)
        await upgrade_database(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            ids = dict((await session.execute(select(User.username, User.id).where(User.username.is_not(None)))).all())
            drawer, guesser = str(ids["drawer"]), str(ids["guesser"])
            public_game = await session.scalar(select(GameRecord.id).where(GameRecord.visibility == "public"))
            turn = await session.scalar(select(TurnDrawing.turn_id).where(TurnDrawing.game_id == public_game))
            pinned_revisions = await session.scalar(select(func.count()).select_from(GamePromptSource))
        assert pinned_revisions == 1

        history = SqlAlchemyGameHistoryRepository(factory)
        games = await history.get_user_games(drawer, requesting_user_id=drawer)
        assert {game.id for game in games} >= {str(public_game)}
        detail = await history.get_game_detail(str(public_game), requesting_user_id=guesser)
        assert detail is not None
        drawing = await history.get_turn_drawing(str(public_game), str(turn), requesting_user_id=guesser)
        assert drawing is not None
        gallery = await history.list_gallery(sort="top")
        assert [entry.turn_id for entry in gallery.entries] == [str(turn)]
        pins = await history.get_profile_pins(drawer)
        assert pins is not None
        from datetime import datetime, timezone

        assert await history.get_recent_co_players(drawer, since=datetime(2020, 1, 1, tzinfo=timezone.utc))

        lists = SqlAlchemyPromptListRepository(factory)
        community = await lists.list_community()
        assert [row.star_count for row in community.lists] == [1]
        assert await lists.get_community(community.lists[0].id) is not None

        listing = await FriendService(factory).listing(UUID(drawer))
        assert [str(user.id) for _row, user in listing["friends"]] == [guesser]

        async with factory() as session:
            from app.db.models import DataExport

            export_id = await session.scalar(select(DataExport.id))
        assert await get_data_export(factory, export_id=export_id, user_id=drawer) is not None

        report = await IntegrityAudit(factory, budget=AuditBudget(pass_seconds=60.0)).run_pass()
        assert {check: row["mismatches_total"] for check, row in report.items()} == dict.fromkeys(report, 0)
        assert not any(row["failed"] for row in report.values())
    finally:
        await engine.dispose()
        await scratch.drop()
