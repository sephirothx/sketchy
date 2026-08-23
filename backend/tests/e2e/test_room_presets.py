"""Saved room-setting presets work through the real creation flow."""

import pytest
from playwright.async_api import async_playwright, expect

from tests.e2e.lobby_helpers import register_account, use_guest_name


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_registered_player_saves_applies_and_uses_room_preset():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "PresetHost")
            await register_account(page, "PresetHost")
            await page.get_by_role("button", name="Create room").click()
            await page.get_by_label("Room name (optional)").fill("Friday finals")
            await page.get_by_role("spinbutton", name="Max players").fill("12")
            await page.get_by_role("spinbutton", name="Rounds").fill("5")
            await page.get_by_role("button", name="Private").click()
            await page.get_by_label("Preset name").fill("Tournament night")
            await page.get_by_role("button", name="Save new").click()
            await page.get_by_label("Saved preset").select_option(label="Tournament night")

            await page.get_by_label("Room name (optional)").fill("Changed")
            await page.get_by_role("spinbutton", name="Max players").fill("3")
            await page.get_by_role("spinbutton", name="Rounds").fill("1")
            await page.get_by_role("button", name="Public").click()
            await page.get_by_role("button", name="Apply").click()

            await expect(page.get_by_label("Room name (optional)")).to_have_value("Friday finals")
            assert await page.get_by_role("spinbutton", name="Max players").input_value() == "12"
            assert await page.get_by_role("spinbutton", name="Rounds").input_value() == "5"
            assert await page.get_by_role("button", name="Private").get_attribute("aria-pressed") == "true"
            assert not await page.get_by_role(
                "switch", name="Keep this room for future games"
            ).is_checked()

            await page.locator(".create-room-submit").click()
            await page.wait_for_selector('[data-testid="waiting-room"]')
            assert await page.get_by_role("spinbutton", name="Max players").input_value() == "12"
            assert await page.get_by_role("spinbutton", name="Rounds").input_value() == "5"
            await page.get_by_text("Host settings").wait_for()
        finally:
            await browser.close()
