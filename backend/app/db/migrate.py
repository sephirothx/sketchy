"""Deployment entry point for applying database migrations safely."""
from __future__ import annotations

import asyncio

from app.db import create_db_engine, upgrade_database


async def _run() -> None:
    # The migration role: a short lock wait (the deploy advisory lock
    # included) and a statement budget of its own, rather than the web
    # engine's request-sized ones.
    engine = create_db_engine(role="migration")
    try:
        await upgrade_database(engine)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
