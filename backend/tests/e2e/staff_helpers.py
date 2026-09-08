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


async def offer_role(username: str, role: str = "moderator") -> None:
    """Record the offer an administrator's grant would record.

    Moderator, because that is the only role an offer can be for: `admin` is
    not granted over the network and so cannot be waited for either, and the
    CHECK on `users.pending_role` says so.

    A staff role is not granted outright to an account with no proved second
    factor (R-AUTH-20): it waits, and enrolling is what takes it up. Written
    here rather than driven through the operations page, because the suites
    that need an account with something waiting on it are not about how an
    administrator reaches the button.
    """
    engine = create_async_engine(database_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(User)
                    .where(User.username == username)
                    .values(
                        pending_role=role,
                        pending_role_at=datetime.now(timezone.utc),
                    )
                )
    finally:
        await engine.dispose()


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


async def take_up_the_offer(page, password: str = "a-good-password") -> str:
    """Enrol the second factor a standing offer is waiting on, and return the
    secret so a later step can produce a code.

    This *is* the promotion (R-AUTH-20): an administrator offers the role, the
    account stays what it was, and setting up the factor is what makes the
    role take effect. Every *other* device is signed out with it; this one is
    handed a fresh session for the role it now holds, so the page this ran in
    comes back staff rather than signed out.

    Driven through the dialog rather than written into the database, because
    the ceremony being reachable is half of what the flow is for: the entry
    only appears at all once something is waiting on it.
    """
    import time

    from app.auth.totp import code_at, current_step

    # Settings → Account, where the entry appears for an account that has been
    # offered a role - and for no other player.
    await page.goto(f"{BASE_URL}/settings/account")
    await page.get_by_role("button", name="Set up").click()
    # By accessible name: the settings overlay is a dialog too, and it
    # carries this row's label.
    dialog = page.get_by_role("dialog", name="Two-factor authentication")
    # No page of explanation first: the dialog offers a secret as it opens.
    secret = (await dialog.locator(".two-factor-secret code").inner_text()).strip()
    # The password says whose account this is being bound to; the code says an
    # authenticator produced it. The role is granted on the pair.
    await dialog.get_by_label("Your password").fill(password)
    # Six boxes that submit themselves on the last digit, so there is no
    # button to press.
    await type_code(dialog, code_at(secret, current_step(time.time())))
    await dialog.locator(".two-factor-ack input").check()
    await dialog.get_by_role("button", name="Done").click()
    # And the role that was waiting has begun.
    await dialog.get_by_role("button", name="Done").click()
    return secret


async def type_code(scope, code: str) -> None:
    """Fill the six boxes a code is entered into.

    One box per digit, so `fill` on a single field no longer reaches it; the
    first box takes the whole string, which is the paste path the component
    handles and the one a person uses too.
    """
    await scope.locator(".code-box").first.fill(code)
