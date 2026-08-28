"""Durable key/value settings, read and written inside a caller's transaction.

`app_config` has held exactly one row since it shipped - the auto-generated
`ip_hash_secret` - and its only accessor, `get_ip_hash_secret`, is written
around that one key's needs: it generates a value when the row is missing and
retries a racing insert. Nothing in it is reusable for a setting an operator
types in.

The functions here are the general shape instead, and they take a `session`
rather than a `session_factory` on purpose. Every write that reaches this
module is an audited administrative change (#446), and an audit event that
commits separately from the change it describes is a ledger that can disagree
with the world. Handing the caller's session in is what lets the row and its
audit event share one transaction.
"""
from __future__ import annotations


from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AppConfig


async def read_prefixed(
    session_factory: async_sessionmaker[AsyncSession], prefix: str
) -> dict[str, str]:
    """Every stored value under one namespace, keyed without the prefix.

    Read in one query at startup rather than one per setting: a process that
    asks the database twenty times before it is ready is twenty chances to be
    slow for no reason.
    """
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(AppConfig).where(AppConfig.key.startswith(prefix))
            )
        ).all()
    return {row.key.removeprefix(prefix): row.value for row in rows}


async def read_one(
    session_factory: async_sessionmaker[AsyncSession], key: str
) -> str | None:
    """One stored value, or None when nothing has been written under that key."""
    async with session_factory() as session:
        row = await session.get(AppConfig, key)
    return row.value if row is not None else None


async def put(session: AsyncSession, key: str, value: str) -> None:
    """Store one value, replacing whatever was there.

    Read-then-write rather than a dialect-specific upsert, because this runs on
    both SQLite and PostgreSQL and the writes are administrative: a handful a
    day, each already inside a transaction that serializes it.
    """
    row = await session.get(AppConfig, key)
    if row is None:
        session.add(AppConfig(key=key, value=value))
    else:
        row.value = value


async def drop(session: AsyncSession, key: str) -> None:
    """Forget one value, so whatever computes the default answers again."""
    await session.execute(delete(AppConfig).where(AppConfig.key == key))

