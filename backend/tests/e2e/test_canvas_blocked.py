"""A browser that scrambles canvas reads is told so, and nobody else is (R-UX-15).

Firefox's `privacy.resistFingerprinting` - the default in Tor Browser, Mullvad
Browser and LibreWolf - answers a canvas read with noise, and the game paints by
reading back. Every stroke landed in a rectangle of static. A page cannot change
the setting, so the lobby says what to do, and a room keeps saying it as a chip.
"""

from uuid import uuid4

from playwright.async_api import async_playwright, expect

from tests.e2e.lobby_helpers import use_guest_name

BASE_URL = "http://localhost:8000"
BANNER = ".server-shutdown-banner.is-canvas-blocked"
CHIP = '.room-notice-chip[data-notice="canvas-blocked"]'


async def create_room(page):
    await page.click('button:has-text("Create room")')
    await page.click('button:has-text("Create room")')
    await page.wait_for_selector('[data-testid="room-header"]')


async def test_a_scrambled_canvas_is_named_in_the_lobby_and_in_the_room():
    async with async_playwright() as p:
        browser = await p.firefox.launch(
            headless=True,
            firefox_user_prefs={"privacy.resistFingerprinting": True, "media.volume_scale": "0.0"},
        )
        try:
            page = await (await browser.new_context()).new_page()
            await page.goto(BASE_URL)
            await use_guest_name(page, f"Scrambled{uuid4().hex[:6]}")

            banner = page.locator(BANNER)
            await expect(banner).to_be_visible()
            await expect(banner).to_contain_text("privacy.resistFingerprinting")
            # Looking again changes nothing while the setting is still on.
            await banner.get_by_role("button", name="Check again").click()
            await expect(banner).to_be_visible()
            await banner.get_by_role("button", name="Dismiss").click()
            await expect(banner).to_have_count(0)

            # Closing the lobby's banner is not closing the room's chip: in a
            # room the notice is about the canvas in front of them.
            await create_room(page)
            chip = page.locator(CHIP)
            await expect(chip).to_be_visible()
            await chip.click()
            popover = page.locator('.room-notice-popover[data-notice="canvas-blocked"]')
            await expect(popover).to_contain_text("about:config")
            await expect(popover.get_by_role("button", name="Check again")).to_be_visible()
        finally:
            await browser.close()


async def test_a_browser_that_reads_back_true_is_told_nothing():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        try:
            page = await (await browser.new_context()).new_page()
            await page.goto(BASE_URL)
            await use_guest_name(page, f"Clear{uuid4().hex[:6]}")
            # The check runs on arrival, before the lobby can be used.
            assert await page.evaluate("() => document.readyState") == "complete"
            await expect(page.locator(BANNER)).to_have_count(0)
            await create_room(page)
            await expect(page.locator(CHIP)).to_have_count(0)
        finally:
            await browser.close()
