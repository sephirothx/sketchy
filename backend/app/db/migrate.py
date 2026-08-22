"""Deployment entry point for applying database migrations safely."""
from __future__ import annotations

import asyncio

from app.db import async_engine, upgrade_database


async def _run() -> None:
    try:
        await upgrade_database(async_engine)
    finally:
        await async_engine.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
