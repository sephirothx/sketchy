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
async def test_two_factor_is_set_up_once_and_then_asked_for_again():
    """Enrolment, the codes, and the step-up prompt, in one browser.

    Deliberately one test rather than three. Each one would want its own
    browser, and the suite already runs eight workers against a single server;
    two extra browsers were enough to push the heaviest game tests past their
    timeouts. The three things checked here are steps of one flow anyway, and
    a person performs them in this order.
    """
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

            # Shown once: acknowledging them is the only way past.
            await dialog.get_by_role("button", name="I have saved them").click()
            await expect(dialog).to_contain_text("Two-factor authentication is on")
            await expect(dialog).to_contain_text("10 recovery codes left")
            await dialog.get_by_role("button", name="Close").click()

            # Staff, with nothing proved since: exactly the state a browser
            # is in once its step-up window has run out.
            await set_role("TwoFactorPlayer", "admin")
            await _clear_step_up("TwoFactorPlayer")

            # Closing a room this test opened itself, rather than pausing
            # admission. Both are destructive staff actions that raise the
            # prompt (R-AUTH-21), but a pause is *server-wide* - it refuses
            # new rooms, games and restart votes for everybody - and this
            # suite runs eight workers against one server, so holding one even
            # for a second failed whichever room or game happened to be
            # starting elsewhere. A room of our own is the same gate with none
            # of the blast radius.
            await page.goto(BASE_URL)
            await page.click('button:has-text("Create room")')
            # Named, because the operator's table lists every room on the
            # server and the other workers' rooms are in it too.
            await page.fill(
                'input[placeholder="Leave blank for a random name!"]',
                "TwoFactorRoom",
            )
            await page.click('button:has-text("Create room")')
            await page.wait_for_selector('[data-testid="waiting-room"]')

            await page.goto(f"{BASE_URL}/admin/operations?tab=controls")
            await page.wait_for_selector(
                '[role="tab"][aria-selected="true"]:has-text("Controls")'
            )
            room_row = page.locator(".ops-table tbody tr", has_text="TwoFactorRoom")
            await expect(room_row).to_be_visible()
            await room_row.get_by_role("button", name="Close room").click()
            await room_row.get_by_role("button", name="Confirm close").click()

            prompt = page.locator('[role="dialog"]', has_text="Confirm it is you")
            await expect(prompt).to_be_visible()

            # The step the enrolment just spent cannot be reused, which is the
            # replay rule doing its job; the next one is accepted.
            await prompt.get_by_label("Code from your authenticator app").fill(
                code_at(secret, current_step(time.time()) + 1)
            )
            await prompt.get_by_role("button", name="Confirm").click()
            await expect(prompt).not_to_be_visible()

            # And the command the prompt interrupted actually ran: the row is
            # gone from a table this test is the only writer of.
            await expect(room_row).to_have_count(0)
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
