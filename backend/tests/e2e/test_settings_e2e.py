import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import register_account, use_guest_name

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
async def test_settings_dialog_brush_cursor_scenario():
    """
    Scenario 2: Settings Dialog & In-Game Preferences E2E Test
    1. Opens Lobby page, creates a room.
    2. Opens Settings dialog via header button.
    3. Navigates to 'Game' tab.
    4. Selects 'Outline' brush cursor option.
    5. Clicks Save.
    6. Verifies localStorage persists 'sketchy_brushcursor' == 'circle' and
       that saving clears the pre-rename 'sketchy_pencursor' key.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--mute-audio'])
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto(BASE_URL)
            # Stand in for a player who set a cursor before the tool was renamed.
            # Without this the storage starts clean and the migration assertions
            # below would hold whether or not the migration exists.
            await page.evaluate(
                "() => localStorage.setItem('sketchy_pencursor', 'circle')"
            )
            await page.reload()
            migrated_cursor = await page.evaluate(
                "() => localStorage.getItem('sketchy_pencursor')"
            )
            assert migrated_cursor == "circle", "the legacy value should survive until a save"
            await use_guest_name(page, "SettingsTester")
            await page.click('button:has-text("Create room")')
            await page.click('button:has-text("Create room")')
            # Wait for the room before claiming the account. The create-room
            # page carries an identity chip of its own, so registering while
            # the room is still in flight opens the menu on that page and the
            # navigation unmounts it mid-click.
            await page.wait_for_selector('[data-testid="waiting-room"]')

            # Name colours belong to registered players: a guest is pinned to
            # the grey that marks their name as unclaimed, so claim the account
            # before exercising the colour picker.
            await register_account(page, "SettingsTester")

            # Open Settings Modal
            await page.wait_for_selector('button.header-settings-button')
            await page.click('button.header-settings-button')

            # Verify Settings modal opened
            await page.wait_for_selector('.settings-modal-card')
            assert await page.is_visible('text=Settings')

            # Choose a player name color in General settings.
            await page.locator("#name-color-input").fill("#22aa66")

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
            stored_cursor = await page.evaluate(
                "() => localStorage.getItem('sketchy_brushcursor')"
            )
            assert stored_cursor == "circle"
            # The pre-rename key is seeded above, so this is the migration
            # completing: once a save writes the new key, the old one is gone
            # and cannot be resurrected if the new one is ever cleared.
            legacy_cursor = await page.evaluate(
                "() => localStorage.getItem('sketchy_pencursor')"
            )
            assert legacy_cursor is None
            stored_name_color = await page.evaluate("() => localStorage.getItem('sketchy_namecolor')")
            assert stored_name_color == "#22aa66"

            # Saving settings updates the shared room state without reconnecting.
            await page.wait_for_function(
                """() => {
                    const name = document.querySelector('.player-name .colored-player-name');
                    return name && getComputedStyle(name).color === 'rgb(34, 170, 102)';
                }"""
            )

        finally:
            await context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_registered_player_settings_follow_login_to_a_fresh_device():
    """Account settings override a fresh browser's local defaults after login."""
    username = "CrossDeviceSettings"
    password = "a-good-password"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        first_device = await browser.new_context(color_scheme="light")
        first_page = await first_device.new_page()

        try:
            await first_page.goto(BASE_URL)
            await register_account(first_page, username, password)
            await first_page.click("button.header-settings-button")

            dialog = first_page.locator(".settings-modal-card")
            await dialog.wait_for(state="visible")
            theme = dialog.get_by_role("group", name="Theme")
            await theme.get_by_role("button", name="Dark").click()
            await dialog.get_by_role(
                "switch", name="Prefer colorblind-safe colors"
            ).check()
            await dialog.get_by_role("tab", name="Game").click()
            cursor = dialog.get_by_role("group", name="Brush cursor style")
            await cursor.get_by_role("button", name="Outline").click()
            await dialog.get_by_role(
                "switch", name="Clear guesses after sending"
            ).uncheck()
            await dialog.get_by_role("button", name="Save").click()
            await dialog.wait_for(state="hidden")

            fresh_device = await browser.new_context(color_scheme="light")
            fresh_page = await fresh_device.new_page()
            try:
                await fresh_page.goto(BASE_URL)
                await fresh_page.click(".first-run-login")
                login = fresh_page.get_by_role("dialog", name="Log in")
                await login.get_by_label("Username").fill(username)
                await login.get_by_label("Password").fill(password)
                await login.get_by_role("button", name="Log in", exact=True).click()
                await login.wait_for(state="hidden")

                await fresh_page.wait_for_function(
                    "() => document.documentElement.dataset.theme === 'dark'"
                )
                stored = await fresh_page.evaluate(
                    """() => ({
                        theme: localStorage.getItem('sketchy_theme'),
                        cursor: localStorage.getItem('sketchy_brushcursor'),
                        colors: localStorage.getItem('sketchy_colorblindsafecolors'),
                        clearGuess: localStorage.getItem('sketchy_autoclearchatonguess'),
                    })"""
                )
                assert stored == {
                    "theme": "dark",
                    "cursor": "circle",
                    "colors": "true",
                    "clearGuess": "false",
                }

                await fresh_page.click("button.header-settings-button")
                fresh_dialog = fresh_page.locator(".settings-modal-card")
                await fresh_dialog.wait_for(state="visible")
                assert await fresh_dialog.get_by_role(
                    "switch", name="Prefer colorblind-safe colors"
                ).is_checked()
                await fresh_dialog.get_by_role("tab", name="Game").click()
                assert not await fresh_dialog.get_by_role(
                    "switch", name="Clear guesses after sending"
                ).is_checked()
            finally:
                await fresh_device.close()
        finally:
            await first_device.close()
            await browser.close()
