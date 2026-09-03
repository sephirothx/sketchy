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
async def test_settings_apply_as_they_change_without_a_save():
    """Preferences are not a transaction: each row lands as it is changed.

    Also completes the pre-rename cursor migration, which used to depend on a
    Save press and now happens on the change itself.
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
            assert migrated_cursor == "circle", "the legacy value should survive the read"
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

            await page.wait_for_selector('button.header-settings-button')
            await page.click('button.header-settings-button')
            dialog = page.locator('.settings-modal-card')
            await dialog.wait_for(state="visible")
            # A route, not a flag: it can be linked to and it survives a reload.
            assert "/settings/" in page.url

            # The canvas cursor is an appearance preference, with the rest of
            # what the player looks at.
            await dialog.get_by_role("tab", name="Appearance").click()
            cursor = dialog.get_by_role("group", name="Brush cursor style")
            await cursor.get_by_role("button", name="Outline").click()

            # No Save anywhere on the pane.
            assert await dialog.get_by_role("button", name="Save").count() == 0
            stored_cursor = await page.evaluate(
                "() => localStorage.getItem('sketchy_brushcursor')"
            )
            assert stored_cursor == "circle"
            # The pre-rename key is seeded above, so this is the migration
            # completing: once the new key is written the old one is gone and
            # cannot be resurrected if the new one is ever cleared.
            legacy_cursor = await page.evaluate(
                "() => localStorage.getItem('sketchy_pencursor')"
            )
            assert legacy_cursor is None

            # A colour from the account palette, picked rather than typed
            # (#571: the swatches are the only way to choose one).
            await dialog.get_by_role("tab", name="Account").click()
            await dialog.get_by_role("button", name="Teal").click()
            stored_name_color = await page.evaluate(
                "() => localStorage.getItem('sketchy_namecolor')"
            )
            assert stored_name_color == "#0d9488"

            # And it reaches the room without a save and without reconnecting.
            await page.wait_for_function(
                """() => {
                    const name = document.querySelector('.player-name .colored-player-name');
                    return name && getComputedStyle(name).color === 'rgb(13, 148, 136)';
                }"""
            )

            # Closing goes back to the page it was opened over, with the room
            # still mounted underneath it.
            await dialog.get_by_role("button", name="Close settings").click()
            await dialog.wait_for(state="hidden")
            assert "/room/" in page.url
            assert await page.is_visible('[data-testid="waiting-room"]')
        finally:
            await context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_settings_url_opens_over_the_lobby_for_a_direct_visit():
    """The URL is real: typed straight in, it draws over the lobby."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--mute-audio'])
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "DeepLinker")
            await page.goto(f"{BASE_URL}/settings/sound")
            dialog = page.locator('.settings-modal-card')
            await dialog.wait_for(state="visible")
            assert await dialog.get_by_role("tab", name="Sound & effects").get_attribute(
                "aria-selected"
            ) == "true"
            # The lobby is what a direct visitor gets behind it, so closing has
            # somewhere to land.
            assert await page.is_visible(".lobby-rooms-panel")
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
            await dialog.get_by_role("tab", name="Appearance").click()
            theme = dialog.get_by_role("group", name="Theme")
            await theme.get_by_role("button", name="Dark").click()
            await dialog.get_by_role(
                "switch", name="I have trouble telling colors apart"
            ).check()
            await dialog.get_by_role("group", name="Time format").get_by_role(
                "button", name="24-hour"
            ).click()
            cursor = dialog.get_by_role("group", name="Brush cursor style")
            # Immediately-applied rows are merged into one write, so waiting for
            # the request the last change triggers is waiting for all four.
            async with first_page.expect_response(
                lambda response: "/api/users/me/settings" in response.url
                and response.request.method == "PATCH"
            ):
                await cursor.get_by_role("button", name="Outline").click()
            await dialog.get_by_role("button", name="Close settings").click()
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
                        clock: localStorage.getItem('sketchy_timeformat'),
                    })"""
                )
                assert stored == {
                    "theme": "dark",
                    "cursor": "circle",
                    "colors": "true",
                    "clock": "24h",
                }
                # Retired settings leave no key behind to be resurrected.
                retired = await fresh_page.evaluate(
                    """() => [
                        localStorage.getItem('sketchy_autoclearchatonguess'),
                        localStorage.getItem('sketchy_custombrushpresets'),
                    ]"""
                )
                assert retired == [None, None]

                await fresh_page.click("button.header-settings-button")
                fresh_dialog = fresh_page.locator(".settings-modal-card")
                await fresh_dialog.wait_for(state="visible")
                await fresh_dialog.get_by_role("tab", name="Appearance").click()
                assert await fresh_dialog.get_by_role(
                    "switch", name="I have trouble telling colors apart"
                ).is_checked()
                cursor_synced = fresh_dialog.get_by_role(
                    "group", name="Brush cursor style"
                )
                assert await cursor_synced.get_by_role(
                    "button", name="Outline"
                ).get_attribute("aria-pressed") == "true"
                clock_synced = fresh_dialog.get_by_role("group", name="Time format")
                assert await clock_synced.get_by_role(
                    "button", name="24-hour"
                ).get_attribute("aria-pressed") == "true"
            finally:
                await fresh_device.close()
        finally:
            await first_device.close()
            await browser.close()


@pytest.mark.asyncio
async def test_the_email_row_masks_the_address_and_shows_where_it_stands():
    """Settings is opened with other people looking at the screen."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "MaskedMail")
            # The claim dialog takes an optional address as its third field.
            await page.click(".identity-chip")
            await page.get_by_role("menuitem", name="Create account").click()
            claim = page.locator(".modal-card").filter(has_text="Password")
            await claim.wait_for(state="visible")
            inputs = claim.locator("input")
            await inputs.nth(0).fill("MaskedMail")
            await inputs.nth(1).fill("a-good-password")
            await inputs.nth(2).fill("masked@example.com")
            await claim.locator('button[type="submit"]').click()
            await claim.wait_for(state="hidden")

            await page.click("button.header-settings-button")
            dialog = page.locator(".settings-modal-card")
            await dialog.wait_for(state="visible")

            shown = await dialog.locator(".settings-email").inner_text()
            assert "masked" not in shown, f"the local part is still readable in {shown!r}"
            assert "example" not in shown, f"the domain label is still readable in {shown!r}"
            assert shown.endswith(".com"), shown
            assert "\u2022" in shown, shown
            # One dot per hidden letter: the shape and length survive.
            assert len(shown) == len("masked@example.com"), shown
            # An address nobody has verified cannot recover the account, and
            # the row says so as a symbol and two words, not only a sentence.
            status = dialog.locator(".settings-email-status")
            assert "is-unverified" in (await status.get_attribute("class") or "")
            assert (await status.inner_text()).strip() == "Not verified"
            # Masking is presentation only: the reveal control shows it whole
            # for somebody who needs to read it back, and hides it again.
            await dialog.get_by_role("button", name="Show the full address").click()
            assert await dialog.locator(".settings-email").inner_text() == "masked@example.com"
            await dialog.get_by_role("button", name="Hide the full address").click()
            assert "\u2022" in await dialog.locator(".settings-email").inner_text()
        finally:
            await context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_changing_the_password_from_settings_signs_other_devices_out():
    username = "SettingsRekey"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        owner = await browser.new_context()
        other = await browser.new_context()
        page, elsewhere = await owner.new_page(), await other.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, username)
            await register_account(page, username)

            # A second signed-in device, to prove the change evicts it.
            await elsewhere.goto(BASE_URL)
            await elsewhere.click(".first-run-login")
            login = elsewhere.get_by_role("dialog", name="Log in")
            await login.get_by_label("Username").fill(username)
            await login.get_by_label("Password").fill("a-good-password")
            await login.get_by_role("button", name="Log in", exact=True).click()
            await login.wait_for(state="hidden")

            await page.click("button.header-settings-button")
            await page.wait_for_selector('[data-testid="settings"]')
            await page.get_by_role("button", name="Change password").click()
            change = page.get_by_role("dialog", name="Change your password")
            await change.wait_for(state="visible")
            # The mailed route needs a verified address to arrive at, and this
            # account has none, so the link is not offered rather than dead.
            assert await change.get_by_text("Email me a link instead").count() == 0
            await change.get_by_label("Current password").fill("a-good-password")
            await change.get_by_label("New password", exact=True).fill("a-better-password")
            await change.get_by_label("New password again").fill("a-better-password")
            await change.get_by_role("button", name="Change password").click()
            await change.wait_for(state="hidden")

            # This device keeps its session; the other one is out.
            assert await page.evaluate(
                "async () => (await (await fetch('/api/auth/me')).json())?.username"
            ) == username
            await elsewhere.reload()
            assert await elsewhere.evaluate(
                "async () => (await (await fetch('/api/auth/me')).json())"
            ) is None
        finally:
            await owner.close()
            await other.close()
            await browser.close()
