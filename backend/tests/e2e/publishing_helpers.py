"""Giving an end-to-end account what publishing asks of it.

Publishing needs a confirmed email address (R-LIST-12), and the E2E server
sends no mail, so no address can be confirmed through the UI. Suites about
what happens after a list is published write the confirmation into the
throwaway database instead, the way `staff_helpers` grants a role; the gate
itself is covered by `test_owned_prompt_lists.py`, which publishes nothing.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import User
from tests.e2e.staff_helpers import database_url


async def confirm_email(username: str) -> None:
    engine = create_async_engine(database_url())
    try:
        async with engine.begin() as connection:
            await connection.execute(
                update(User)
                .where(User.username == username)
                .values(
                    email=f"{username.lower()}@example.test",
                    email_verified_at=datetime.now(timezone.utc),
                )
            )
    finally:
        await engine.dispose()
