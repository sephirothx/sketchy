"""A pass bought through the stub shows on the thanks page, in Settings and in the inbox (#1475)."""
from __future__ import annotations

import uuid

from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import register_account, use_guest_name

BASE_URL = "http://localhost:8000"


def unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


async def test_a_pass_bought_through_the_stub_shows_everywhere():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        page = await (await browser.new_context()).new_page()
        name = unique("Marta")
        await page.goto(BASE_URL)
        await use_guest_name(page, name)
        await register_account(page, name)

        await page.goto(f"{BASE_URL}/settings/support")
        pane = page.get_by_test_id("support-pane")
        await pane.wait_for()
        await pane.get_by_role("button", name="Continue to checkout").click()
        await page.get_by_role("button", name="Pay").click()

        await page.get_by_test_id("support-thanks").get_by_text("Thank you").wait_for()

        await page.goto(f"{BASE_URL}/settings/support")
        await pane.get_by_text("You're a supporter. Thank you!").wait_for()
        await pane.get_by_text("renews on").wait_for()

        await page.goto(BASE_URL)
        await page.locator(".identity-chip .supporter-mark").wait_for()

        await page.goto(f"{BASE_URL}/support/cancel")
        await page.get_by_role("button", name="Cancel renewal").click()
        await page.get_by_text("Done. Your pass stays active").wait_for()
        await browser.close()


async def test_a_guest_cannot_reach_checkout():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        page = await (await browser.new_context()).new_page()
        await page.goto(BASE_URL)
        await use_guest_name(page, unique("Visitor"))
        await page.goto(f"{BASE_URL}/settings/support")
        pane = page.get_by_test_id("support-pane")
        await pane.get_by_text("You need an account to get a pass.").wait_for()
        assert await pane.get_by_role("button", name="Continue to checkout").count() == 0
        # The price is known before signing up.
        await pane.get_by_text("Lifetime").wait_for()
        await browser.close()
