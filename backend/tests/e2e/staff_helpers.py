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
BASE_URL = "http://localhost:8000"


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
                            password_proved_at=now,
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

    # Settings → Account, where it now lives beside the password and the
    # signed-in devices rather than in the header menu.
    await page.goto(f"{BASE_URL}/settings/account")
    await page.get_by_role("button", name="Set up").click()
    # By accessible name: the settings overlay is a dialog too, and it
    # carries this row's label.
    dialog = page.get_by_role("dialog", name="Two-factor authentication")
    # No page of explanation first: the dialog offers a secret as it opens.
    secret = (await dialog.locator(".two-factor-secret code").inner_text()).strip()
    # Six boxes that submit themselves on the last digit, so there is no
    # button to press.
    await type_code(dialog, code_at(secret, current_step(time.time())))
    await dialog.locator(".two-factor-ack input").check()
    await dialog.get_by_role("button", name="Done").click()
    # Setting one up asks for no password, so a role still needs this: it is
    # what says the authenticator is the account owner's (R-AUTH-20).
    await dialog.get_by_label("Your password").fill("a-good-password")
    await dialog.get_by_role("button", name="Confirm it’s yours").click()
    await dialog.get_by_role("button", name="Close").click()
    return secret


async def type_code(scope, code: str) -> None:
    """Fill the six boxes a code is entered into.

    One box per digit, so `fill` on a single field no longer reaches it; the
    first box takes the whole string, which is the paste path the component
    handles and the one a person uses too.
    """
    await scope.locator(".code-box").first.fill(code)
