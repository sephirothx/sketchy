import pytest
from playwright.async_api import async_playwright

from tests.e2e.guest_nickname import submit_guest_nickname

BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("color_scheme", "stored_theme", "expected_theme"),
    [
        ("dark", None, "dark"),
        ("light", None, "light"),
        ("dark", "system", "dark"),
        ("light", "system", "light"),
        ("dark", "light", "light"),
        ("light", "dark", "dark"),
    ],
)
async def test_theme_defaults_to_system_preference_unless_saved(
    color_scheme, stored_theme, expected_theme
):
    """Fresh visitors follow their device; saved choices take precedence."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--mute-audio'])
        context = await browser.new_context(color_scheme=color_scheme)
        if stored_theme:
            await context.add_init_script(
                f"localStorage.setItem('sketchy_theme', '{stored_theme}')"
            )
        page = await context.new_page()

        try:
            await page.goto(BASE_URL)
            theme = await page.evaluate("() => document.documentElement.dataset.theme")
            assert theme == expected_theme
        finally:
            await context.close()
            await browser.close()

@pytest.mark.asyncio
async def test_settings_dialog_pen_cursor_scenario():
    """
    Scenario 2: Settings Dialog & In-Game Preferences E2E Test
    1. Opens Lobby page, creates a room.
    2. Opens Settings dialog via header button.
    3. Navigates to 'Game' tab.
    4. Selects 'Outline' brush cursor option.
    5. Clicks Save.
    6. Verifies localStorage persists 'sketchy_pencursor' == 'circle'.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--mute-audio'])
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto(BASE_URL)
            await page.click('button:has-text("Create room")')
            await submit_guest_nickname(page, "SettingsTester")
            await page.click('button:has-text("Create room")')

            # Open Settings Modal
            await page.wait_for_selector('button.header-settings-button')
            await page.click('button.header-settings-button')

            # Verify Settings modal opened
            await page.wait_for_selector('.settings-modal-card')
            assert await page.is_visible('text=Settings')

            # Guests cannot customize name color; the control is hidden.
            assert await page.locator("#name-color-input").count() == 0
            assert await page.is_visible("text=Guest names stay gray")

            # Click Game tab
            await page.click('button[role="tab"]:has-text("Game")')

            # Select Outline brush cursor style
            brush_cursor = page.get_by_role("group", name="Brush cursor style")
            await brush_cursor.get_by_role("button", name="Outline").click()

            # Save settings
            await page.click('.settings-modal-footer button:has-text("Save")')

            # Verify modal closed
            await page.wait_for_selector('.settings-modal-card', state='hidden')

            # Verify localStorage
            stored_cursor = await page.evaluate("() => localStorage.getItem('sketchy_pencursor')")
            assert stored_cursor == "circle"

            # Guest names stay gray in the waiting-room player list.
            await page.wait_for_function(
                """() => {
                    const name = document.querySelector('.player-name .colored-player-name');
                    return name && getComputedStyle(name).color === 'rgb(136, 136, 136)';
                }"""
            )

        finally:
            await context.close()
            await browser.close()
