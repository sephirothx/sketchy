"""Persistent group-room configuration is usable from the real player flow."""

import pytest
from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import register_account, use_guest_name


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_owner_reopens_same_persistent_room_after_live_instance_empties():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "FridayHost")
            await register_account(page, "FridayHost")
            await page.get_by_role("button", name="Create room").click()
            await page.get_by_role(
                "switch", name="Keep this room for future games"
            ).check()
            await page.locator(".create-room-name-field input").fill("Friday artists")
            await page.locator(".create-room-submit").click()
            await page.wait_for_selector('[data-testid="waiting-room"]')
            await page.get_by_text("Persistent room settings").wait_for()
            code_text = await page.inner_text(".room-copy-button")
            code = code_text.split("Code:")[1].strip()

            await page.get_by_role("button", name="Leave room").click()
            await page.get_by_text("My persistent rooms").wait_for()
            owned = page.locator(".public-room-card").filter(has_text="Friday artists")
            assert code in await owned.inner_text()
            await owned.get_by_role("button", name="Open room").click()

            await page.wait_for_selector('[data-testid="waiting-room"]')
            assert code in await page.inner_text(".room-copy-button")
            await page.get_by_text("Persistent room settings").wait_for()
        finally:
            await browser.close()
