import pytest
from playwright.async_api import async_playwright

BASE_URL = "http://localhost:8000"

@pytest.mark.asyncio
async def test_settings_dialog_pen_cursor_scenario():
    """
    Scenario 2: Settings Dialog & In-Game Preferences E2E Test
    1. Opens Lobby page, creates a room.
    2. Opens Settings dialog via header button.
    3. Navigates to 'Game' tab.
    4. Selects 'Circular Outline (matching brush size)' option.
    5. Clicks Save.
    6. Verifies localStorage persists 'sketchy_pencursor' == 'circle'.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto(BASE_URL)
            await page.fill('input[placeholder="Your name"]', "SettingsTester")
            await page.click('button:has-text("Create room")')

            # Open Settings Modal
            await page.wait_for_selector('button.header-settings-button')
            await page.click('button.header-settings-button')

            # Verify Settings modal opened
            await page.wait_for_selector('.settings-modal-card')
            assert await page.is_visible('text=Settings')

            # Click Game tab
            await page.click('button[role="tab"]:has-text("Game")')

            # Select Pen Cursor Style option
            select_el = await page.wait_for_selector('select#pen-cursor-style')
            await select_el.select_option('circle')

            # Save settings
            await page.click('button:has-text("Save")')

            # Verify modal closed
            await page.wait_for_selector('.settings-modal-card', state='hidden')

            # Verify localStorage
            stored_cursor = await page.evaluate("() => localStorage.getItem('sketchy_pencursor')")
            assert stored_cursor == "circle"

        finally:
            await context.close()
            await browser.close()
