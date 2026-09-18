"""Deployment entry point for applying database migrations safely."""
from __future__ import annotations

import asyncio

from app.db import (
    create_db_engine,
    get_migration_database_url,
    summarise_on_dispose,
    upgrade_database,
)


async def _run() -> None:
    # The migration role: a short lock wait (the deploy advisory lock
    # included) and a statement budget of its own, rather than the web
    # engine's request-sized ones.
    # As the schema owner (MIGRATION_DATABASE_URL, #896): the web role can
    # read and write rows and nothing else. The upgrade grants that role its
    # privileges on whatever the revisions created.
    engine = create_db_engine(get_migration_database_url(), role="migration")
    # How long the migration ran and what it did, as one log line (#892).
    summarise_on_dispose(engine, role="migration", command="app.db.migrate")
    try:
        await upgrade_database(engine)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
