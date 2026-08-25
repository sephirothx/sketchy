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
            await page.get_by_label("Room name").fill("Friday finals")
            await page.get_by_role("spinbutton", name="Max players").fill("12")
            await page.get_by_role("spinbutton", name="Rounds").fill("5")
            await page.get_by_role("button", name="Private").click()
            await page.get_by_role("button", name="Save as preset").click()
            await page.get_by_placeholder("Name this preset").fill("Tournament night")
            await page.get_by_role("button", name="Save", exact=True).click()
            await page.get_by_text("Saved “Tournament night”.").wait_for()

            await page.get_by_label("Room name").fill("Changed")
            await page.get_by_role("spinbutton", name="Max players").fill("3")
            await page.get_by_role("spinbutton", name="Rounds").fill("1")
            await page.get_by_role("button", name="Public").click()

            # Choosing the preset applies it; there is no separate Apply step.
            await page.get_by_label("Start from a saved preset").select_option(
                label="Tournament night"
            )
            await page.get_by_text("Applied “Tournament night”.").wait_for()

            await expect(page.get_by_label("Room name")).to_have_value("Friday finals")
            assert await page.get_by_role("spinbutton", name="Max players").input_value() == "12"
            assert await page.get_by_role("spinbutton", name="Rounds").input_value() == "5"
            assert await page.get_by_role("button", name="Private").get_attribute("aria-pressed") == "true"
            assert not await page.get_by_role(
                "switch", name="Keep this room for future games"
            ).is_checked()

            # A preset applied by accident is recoverable without leaving the page.
            await page.get_by_role("button", name="Undo").click()
            await expect(page.get_by_label("Room name")).to_have_value("Changed")
            assert await page.get_by_role("spinbutton", name="Rounds").input_value() == "1"

            await page.get_by_label("Start from a saved preset").select_option(
                label="Tournament night"
            )
            await page.get_by_text("Applied “Tournament night”.").wait_for()

            await page.locator(".create-room-submit").click()
            await page.wait_for_selector('[data-testid="waiting-room"]')
            assert await page.get_by_role("spinbutton", name="Max players").input_value() == "12"
            assert await page.get_by_role("spinbutton", name="Rounds").input_value() == "5"
            await page.get_by_text("Host settings").wait_for()
        finally:
            await browser.close()
