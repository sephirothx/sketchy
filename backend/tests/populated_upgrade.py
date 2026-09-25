"""A database with rows in it, frozen at one revision, for every later revision to run over (#893).

CI replays the migration chain on an empty database, which proves the chain
is sound and nothing about data: a backfill, a `NOT NULL` tightening or a
constraint added over existing rows is only proven where somebody wrote a
seeded test for it. So this seeds one database through the application's own
writers - accounts, a friendship, a published and starred list whose revision
a finished game pins, played games with drawings, reactions from the room and
the Gallery, a profile pin, a lobby line, a finished export - at
`FIXTURE_REVISION`, and dumps its rows as SQL. `tests/test_populated_upgrade.py`
restores the schema at that revision, loads the rows, upgrades to head and
reads every history surface back, so each revision written after it runs over
rows the day it is written.

Regenerate only when a fold moves the baseline (the dump is data at one
revision; later revisions must upgrade it, not replace it):

    TEST_DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_test \\
      backend/.venv/bin/python -m tests.populated_upgrade --write

`PG_DUMP` names the `pg_dump` binary when it is not on the path.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
from uuid import UUID, uuid4

import asyncpg
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from tests.parallel_databases import drop_database

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "fixtures" / "populated_upgrade.sql"
# The revision the rows were written at. Moves only with a fold.
FIXTURE_REVISION = "c3e4f5a6b7d8"
SEED_TIME = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


@dataclass
class Seeded:
    """The ids a reader needs to ask for what was written."""

    drawer: str
    guesser: str
    outsider: str
    game_id: str
    turn_id: str
    pinned_game_id: str
    list_id: str
    export_id: str


async def seed(factory: async_sessionmaker[AsyncSession]) -> Seeded:
    """Write one of everything worth upgrading over, through the real writers."""
    from app.auth.account_data import create_data_export, process_data_export
    from app.repositories.interfaces import PromptListEntryInput
    from app.repositories.sqlalchemy import (
        SqlAlchemyGameHistoryRepository,
        SqlAlchemyPromptListRepository,
        SqlAlchemyUserRepository,
    )
    from app.services.friends import FriendService
    from app.services.message_retention import MessageRetentionService
    from tests.test_drawing_reactions import record_game, registered
    from tests.test_owned_prompt_lists import _current_revision_id, _pin_a_game_to

    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    lists = SqlAlchemyPromptListRepository(factory)
    await lists.seed_list_tags()

    drawer = await registered(users, "Drawer")
    guesser = await registered(users, "Guesser")
    outsider = await registered(users, "Outsider")
    await users.create_anonymous(display_name="Passerby")

    friends = FriendService(factory)
    await friends.request(UUID(drawer.id), UUID(guesser.id))
    await friends.accept(UUID(guesser.id), UUID(drawer.id))

    owned = await lists.create_owned(
        drawer.id,
        name="Seaside",
        description="Things by the sea",
        language="en",
        prompts=(PromptListEntryInput(answer="lighthouse", aliases=("light house",)), PromptListEntryInput(answer="gull")),
        tags=("nature",),
    )
    await lists.set_owned_publication(drawer.id, owned.id, published=True)
    await lists.set_star(guesser.id, owned.id, starred=True)
    await _pin_a_game_to(factory, drawer.id, await _current_revision_id(factory, owned.id))
    from sqlalchemy import select

    from app.db.models import GamePromptSource

    async with factory() as session:
        pinned_game = await session.scalar(select(GamePromptSource.game_id).limit(1))

    recorded = await record_game(
        history, drawer=drawer.id, reactor=guesser.id, reactions="default", visibility="public"
    )
    await history.set_drawing_reaction(
        None, recorded.turn_id, requesting_user_id=outsider.id, emoji="wow", from_gallery=True
    )
    await history.set_profile_pins(requesting_user_id=drawer.id, turn_ids=[recorded.turn_id])

    messages = MessageRetentionService(factory)
    await messages.record_lobby(
        user_id=guesser.id,
        display_name="Guesser",
        name_color=None,
        is_anonymous=False,
        text="good game",
        sent_at=SEED_TIME,
    )
    await messages.drain()
    await messages.aclose()

    export = await create_data_export(factory, user_id=drawer.id)
    await process_data_export(factory, export_id=export.id)

    return Seeded(
        drawer=drawer.id,
        guesser=guesser.id,
        outsider=outsider.id,
        game_id=recorded.game_id,
        turn_id=recorded.turn_id,
        pinned_game_id=str(pinned_game),
        list_id=owned.id,
        export_id=str(export.id),
    )


class ScratchDatabase:
    """One empty database for a populated upgrade, created and dropped by a role that may."""

    def __init__(self, admin_url: str) -> None:
        self.base = make_url(admin_url)
        self.name = f"sketchy_test_upgrade_{uuid4().hex[:12]}"

    @property
    def url(self) -> str:
        return self.base.set(database=self.name).render_as_string(hide_password=False)

    def _server(self) -> str:
        return self.base.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)

    async def create(self) -> str:
        connection = await asyncpg.connect(self._server())
        try:
            await connection.execute(f'CREATE DATABASE "{self.name}"')
        finally:
            await connection.close()
        return self.url

    async def drop(self) -> None:
        connection = await asyncpg.connect(self._server())
        try:
            await drop_database(connection, self.name)
        finally:
            await connection.close()


async def migrate_to(engine: AsyncEngine, revision: str) -> None:
    from alembic import command

    from app.db import get_alembic_config

    config = get_alembic_config()

    def run(connection):
        config.attributes["connection"] = connection
        command.upgrade(config, revision)

    async with engine.begin() as connection:
        await connection.run_sync(run)


async def load_fixture(url: str) -> None:
    """The dumped rows, as the one script pg_dump wrote."""
    connection = await asyncpg.connect(make_url(url).set(drivername="postgresql").render_as_string(hide_password=False))
    try:
        await connection.execute(FIXTURE_PATH.read_text(encoding="utf-8"))
    finally:
        await connection.close()


def _dump(url: str) -> str:
    target = make_url(url)
    binary = os.environ.get("PG_DUMP") or shutil.which("pg_dump") or "pg_dump"
    completed = subprocess.run(
        [
            binary,
            "--data-only",
            "--column-inserts",
            "--no-owner",
            "--no-privileges",
            "--exclude-table=alembic_version",
            f"--host={target.host}",
            f"--port={target.port or 5432}",
            f"--username={target.username}",
            target.database,
        ],
        env={**os.environ, "PGPASSWORD": target.password or ""},
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [
        line
        for line in completed.stdout.splitlines()
        # Session settings pg_dump emits for its own restore: a script loaded
        # through a driver keeps only the rows and what they need.
        if not line.startswith(("SET ", "SELECT pg_catalog.set_config", "\\restrict", "\\unrestrict", "--"))
        and line.strip()
    ]
    header = (
        f"-- Rows seeded through the application's writers at revision {FIXTURE_REVISION} (#893).\n"
        "-- Generated by `python -m tests.populated_upgrade --write`; not edited by hand.\n"
    )
    return header + "\n".join(lines) + "\n"


async def write_fixture(admin_url: str) -> None:
    from app.db import get_engine_connect_args

    scratch = ScratchDatabase(admin_url)
    url = await scratch.create()
    try:
        engine = create_async_engine(url, connect_args=get_engine_connect_args(url, role="migration"))
        try:
            await migrate_to(engine, FIXTURE_REVISION)
            await seed(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()
        FIXTURE_PATH.write_text(_dump(url), encoding="utf-8")
    finally:
        await scratch.drop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate fixtures/populated_upgrade.sql.")
    parser.add_argument("--write", action="store_true", required=True)
    parser.parse_args()
    url = os.environ.get("TEST_OWNER_DATABASE_URL") or os.environ["TEST_DATABASE_URL"]
    asyncio.run(write_fixture(url))
    print(f"wrote {FIXTURE_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
