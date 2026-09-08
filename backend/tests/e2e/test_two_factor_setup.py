"""Setting up two-factor authentication, and being asked for it again.

The ceremony R-AUTH-20 describes has three parts a browser has to get right,
and none of them is provable from the server side alone: the secret is held in
the page between the offer and the confirmation (nothing is stored until a code
comes back), the recovery codes are shown exactly once, and a destructive staff
action that is refused for want of a step-up has to raise a prompt rather than
report a failure.

The other staff suites grant the second factor straight into the database, on
purpose - they are about the moderation queue and the tuning panel. This is the
one that would fail if the dialogs broke.
"""
import time

import pytest
from playwright.async_api import async_playwright, expect

from app.auth.totp import code_at, current_step
from tests.e2e.lobby_helpers import register_account, use_guest_name
from tests.e2e.staff_helpers import set_role

BASE_URL = "http://localhost:8000"
PASSWORD = "a-good-password"


async def _open_two_factor(page):
    await page.click(".account-menu button")
    await page.get_by_role("menuitem", name="Two-factor authentication").click()
    return page.locator('[role="dialog"]', has_text="Two-factor authentication")


@pytest.mark.asyncio
async def test_a_player_sets_up_two_factor_and_is_shown_its_recovery_codes():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(10000)
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "TwoFactorPlayer")
            await register_account(page, "TwoFactorPlayer")

            dialog = await _open_two_factor(page)
            await expect(dialog).to_be_visible()
            await dialog.get_by_role("button", name="Set up").click()

            # The key the app would scan. It is in the page and nowhere else
            # until the code below proves it arrived.
            secret = (await dialog.locator(".two-factor-secret code").inner_text()).strip()
            assert secret

            await dialog.get_by_label("Code from your app").fill(
                code_at(secret, current_step(time.time()))
            )
            await dialog.get_by_role("button", name="Confirm").click()

            codes = dialog.get_by_role("list", name="Recovery codes")
            await expect(codes).to_be_visible()
            assert await codes.locator("li").count() == 10

            # Shown once: acknowledging them is the only way past, and they do
            # not come back when the dialog is reopened.
            await dialog.get_by_role("button", name="I have saved them").click()
            await expect(dialog).to_contain_text("Two-factor authentication is on")
            await expect(dialog).to_contain_text("10 recovery codes left")
        finally:
            await context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_an_operator_is_asked_to_confirm_before_a_command_runs():
    """R-AUTH-21 from the operator's side: a prompt, not a dead end.

    Pausing admission is the destructive action that needs no setup - no
    report, no room, nothing in a queue - so it is the one that shows the
    step-up prompt on its own.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(10000)
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "StepUpAdmin")
            await register_account(page, "StepUpAdmin")

            dialog = await _open_two_factor(page)
            await dialog.get_by_role("button", name="Set up").click()
            secret = (await dialog.locator(".two-factor-secret code").inner_text()).strip()
            await dialog.get_by_label("Code from your app").fill(
                code_at(secret, current_step(time.time()))
            )
            await dialog.get_by_role("button", name="Confirm").click()
            await dialog.get_by_role("button", name="I have saved them").click()
            await dialog.get_by_role("button", name="Close").click()

            # Staff, with nothing proved since: exactly the state a browser is
            # in when its step-up window has run out.
            await set_role("StepUpAdmin", "admin")
            await _clear_step_up("StepUpAdmin")

            await page.goto(f"{BASE_URL}/admin/operations?tab=controls")
            await page.wait_for_selector(
                '[role="tab"][aria-selected="true"]:has-text("Controls")'
            )
            await page.click('button:has-text("Pause new rooms")')

            prompt = page.locator('[role="dialog"]', has_text="Confirm it is you")
            await expect(prompt).to_be_visible()

            # The step just spent by the enrolment cannot be reused, which is
            # the replay rule doing its job; the next one is accepted.
            await prompt.get_by_label("Code from your authenticator app").fill(
                code_at(secret, current_step(time.time()) + 1)
            )
            await prompt.get_by_role("button", name="Confirm").click()
            await expect(prompt).not_to_be_visible()

            # And the command the prompt interrupted actually ran.
            await expect(page.locator('button:has-text("Resume")')).to_be_visible()
        finally:
            await context.close()
            await browser.close()


async def _clear_step_up(username: str) -> None:
    """Take back the step-up `set_role` stamps, so the prompt is reachable."""
    from sqlalchemy import select, update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.models import AuthSession, User
    from tests.e2e.staff_helpers import database_url

    engine = create_async_engine(database_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            async with session.begin():
                user_id = await session.scalar(
                    select(User.id).where(User.username == username)
                )
                await session.execute(
                    update(AuthSession)
                    .where(AuthSession.user_id == user_id)
                    .values(stepped_up_at=None)
                )
    finally:
        await engine.dispose()
