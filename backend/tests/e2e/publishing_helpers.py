"""Giving an end-to-end account what publishing asks of it.

Publishing needs a confirmed email address (R-LIST-12), and the E2E server
sends no mail, so no address can be confirmed through the UI. Suites about
what happens after a list is published write the confirmation into the
throwaway database instead, the way `staff_helpers` grants a role; the gate
itself is covered by `test_owned_prompt_lists.py`, which publishes nothing.

It also holds a published list for review, for the suites about the
moderator's side of R-LIST-13's queue.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import PromptListEdition, User
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


async def hold_for_review(prompt_list_id: str) -> None:
    """Put a list's live edition back in the review queue, as R-LIST-13's
    operator switch would have held it when it was published.

    The switch itself is server-wide: turning it on would hold every list any
    other test publishes meanwhile, in a suite that runs in parallel. A list
    published with the switch off and then held here has the shape a held one
    has - one `under_review` edition, nothing live - and nothing else moves.
    """
    engine = create_async_engine(database_url())
    try:
        async with engine.begin() as connection:
            held = await connection.execute(
                update(PromptListEdition)
                .where(
                    PromptListEdition.prompt_list_id == UUID(prompt_list_id),
                    PromptListEdition.state == "published",
                )
                .values(state="under_review")
            )
            # Nothing live means nothing was held, and a test going on from
            # here would fail later, somewhere that does not say why.
            assert held.rowcount == 1, f"list {prompt_list_id} has no live edition to hold"
    finally:
        await engine.dispose()
