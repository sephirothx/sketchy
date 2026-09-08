"""Making an end-to-end account into staff that can actually act.

Since #468 a role is not enough on its own: a moderator or administrator holds
a TOTP second factor (R-AUTH-20) and re-proves it before every destructive
action (R-AUTH-21). Four suites here grant a role by writing to the throwaway
database, and each of them is about something else - the moderation queue, the
tuning panel, the promotion notice - so each grants the second factor the same
way rather than walking an enrolment ceremony it is not testing.

The ceremony itself, through the real UI, is `test_two_factor_setup.py`. That
is the one that would fail if the dialogs broke; these would keep passing, and
that division is deliberate.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import AuthSession, User, UserSecondFactor


# Any valid base32; no code is ever computed from it, because these helpers
# stamp the step-up directly rather than proving one.
PLACEHOLDER_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def database_url() -> str:
    url = os.environ.get("SKETCHY_E2E_DATABASE_URL")
    if not url:
        pytest.skip("SKETCHY_E2E_DATABASE_URL is not set; run via scripts/test-e2e.sh")
    return url


async def set_role(username: str, role: str) -> None:
    """Move one account's role, and give staff what the role now requires."""
    engine = create_async_engine(database_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(User).where(User.username == username).values(role=role)
                )
                user_id = await session.scalar(
                    select(User.id).where(User.username == username)
                )
                if user_id is None or role not in ("moderator", "admin"):
                    return
                now = datetime.now(timezone.utc)
                if await session.get(UserSecondFactor, user_id) is None:
                    session.add(
                        UserSecondFactor(
                            user_id=user_id,
                            secret=PLACEHOLDER_SECRET,
                            confirmed_at=now,
                            created_at=now,
                            last_step=0,
                            failed_attempts=0,
                        )
                    )
                # Every live device of theirs is treated as having just proved
                # itself, so the fifteen-minute window is open for the run.
                await session.execute(
                    update(AuthSession)
                    .where(
                        AuthSession.user_id == user_id,
                        AuthSession.revoked_at.is_(None),
                    )
                    .values(stepped_up_at=now)
                )
    finally:
        await engine.dispose()


async def enrol_through_the_ui(page) -> str:
    """Set up two-factor authentication the way a person does, and return the
    secret so a later step can produce a code.

    Used where a test needs an account that *may* be promoted: the role change
    refuses an account with no second factor (R-AUTH-20), and doing it through
    the dialog keeps that precondition honest rather than writing the row.
    """
    import time

    from app.auth.totp import code_at, current_step

    await page.click(".account-menu button")
    await page.get_by_role("menuitem", name="Two-factor authentication").click()
    dialog = page.locator('[role="dialog"]', has_text="Two-factor authentication")
    await dialog.get_by_role("button", name="Set up").click()
    secret = (await dialog.locator(".two-factor-secret code").inner_text()).strip()
    await dialog.get_by_label("Code from your app").fill(
        code_at(secret, current_step(time.time()))
    )
    await dialog.get_by_role("button", name="Confirm").click()
    await dialog.get_by_role("button", name="I have saved them").click()
    await dialog.get_by_role("button", name="Close").click()
    return secret
