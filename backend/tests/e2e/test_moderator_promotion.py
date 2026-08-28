"""Promoting a player by name, and the player being told without reloading.

Worth a browser test for the reason `test_admin_tuning.py` gives for its own:
the change is made on one machine, travels over a socket, and has to land in a
page that never reloaded. Three legs - the search that finds the account, the
`PATCH` that changes it, and the push that tells its owner - and none of them is
visible from either side alone.

Unlike a maintenance pause, this is safe on a shared server: it creates its own
two accounts and touches nothing process-wide.
"""
import os

import pytest
from playwright.async_api import async_playwright, expect
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import User
from app.domain_values import UserRole
from tests.e2e.lobby_helpers import register_account, use_guest_name


BASE_URL = "http://localhost:8000"


def _database_url() -> str:
    url = os.environ.get("SKETCHY_E2E_DATABASE_URL")
    if not url:
        pytest.skip("SKETCHY_E2E_DATABASE_URL is not set; run via scripts/test-e2e.sh")
    return url


async def set_role(username: str, role: str) -> None:
    """Move one account's role through the same throwaway database the server
    uses - the way every other end-to-end test makes an account staff."""
    engine = create_async_engine(_database_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(User).where(User.username == username).values(role=role)
                )
    finally:
        await engine.dispose()


async def a_registered_page(browser, username: str):
    context = await browser.new_context()
    page = await context.new_page()
    page.set_default_timeout(10000)
    await page.goto(BASE_URL)
    await use_guest_name(page, username)
    await register_account(page, username)
    return context, page


@pytest.mark.asyncio
async def test_an_administrator_promotes_by_name_and_the_player_is_told():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        admin_context, admin_page = await a_registered_page(browser, "PromoAdmin")
        await set_role("PromoAdmin", UserRole.ADMIN.value)
        await admin_page.reload()
        player_context, player_page = await a_registered_page(browser, "PromoPlayer")

        try:
            # Connected before anything happens and never reloaded after, so
            # what lands in it lands over the socket.
            await player_page.bring_to_front()
            await player_page.wait_for_timeout(500)

            await admin_page.bring_to_front()
            await admin_page.goto(f"{BASE_URL}/admin/operations?tab=controls")
            await admin_page.wait_for_selector(
                '[role="tab"][aria-selected="true"]:has-text("Controls")'
            )

            # By name. The id is never typed anywhere in this test, which is
            # the whole of #507's third complaint.
            await admin_page.fill("#ops-role-search", "PromoPlayer")
            row = admin_page.locator(".ops-role-results li", has_text="PromoPlayer")
            await expect(row).to_have_count(1)
            await row.locator('button:has-text("Select")').click()

            await admin_page.fill("#ops-role-reason", "joining the safety rota")
            await admin_page.click('button:has-text("Set role")')

            # The administrator's own feedback, where they are looking rather
            # than at the top of a panel they scrolled past.
            await expect(
                admin_page.locator(".app-toast", has_text="PromoPlayer is now a moderator.")
            ).to_be_visible()
            await expect(row.locator(".chip", has_text="moderator")).to_be_visible()

            # And the player, in a page that has not reloaded since before the
            # promotion existed.
            await player_page.bring_to_front()
            notice = player_page.locator(
                '[role="dialog"]', has_text="You are now a moderator"
            )
            await expect(notice).to_be_visible()
            await notice.locator('button:has-text("Understood")').click()
            await expect(notice).to_have_count(0)

            # The menu offers what the role now allows, still without a reload.
            await player_page.click(".identity-chip")
            await expect(
                player_page.get_by_role("menuitem", name="Moderation")
            ).to_be_visible()
        finally:
            # Through the database, so a failed assertion above does not leave
            # a moderator behind for the rest of the run.
            await set_role("PromoPlayer", UserRole.USER.value)
            await admin_context.close()
            await player_context.close()
            await browser.close()
