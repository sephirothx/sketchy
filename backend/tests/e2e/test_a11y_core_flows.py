import pytest
from playwright.async_api import Page, async_playwright

from tests.e2e.a11y import assert_no_axe_violations
from tests.e2e.lobby_helpers import room_code, use_guest_name

BASE_URL = "http://localhost:8000"


async def _open_chromium(color_scheme="light", theme=None):
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
    context_kwargs = {"color_scheme": color_scheme}
    context = await browser.new_context(**context_kwargs)
    if theme:
        await context.add_init_script(f"localStorage.setItem('sketchy_theme', '{theme}')")
    page = await context.new_page()
    page.set_default_timeout(15000)
    return playwright, browser, context, page


async def _close(playwright, browser, context):
    await context.close()
    await browser.close()
    await playwright.stop()


async def _create_waiting_room(page: Page, nickname="A11yHost", *, rounds=None):
    await page.goto(BASE_URL)
    await use_guest_name(page, nickname)
    await page.click('button:has-text("Create room")')
    if rounds is not None:
        current = int(await page.get_by_label("Rounds", exact=True).input_value())
        while current > rounds:
            await page.get_by_role("button", name="Decrease Rounds").click()
            current -= 1
    await page.click('button:has-text("Create room")')
    await page.wait_for_selector('[data-testid="waiting-room"]')
    return await room_code(page)


async def _join_by_code(page: Page, code: str, nickname: str):
    await page.goto(BASE_URL)
    await use_guest_name(page, nickname)
    await page.fill('input[placeholder="ABC123"]', code)
    await page.click('button:has-text("Join by code")')
    await page.wait_for_selector('[data-testid="waiting-room"]')


async def _start_drawing_round(host_page: Page, guest_page: Page):
    await host_page.click('button:has-text("Start game")')
    await host_page.wait_for_selector(".game-layout")
    await guest_page.wait_for_selector(".game-layout")
    drawer_page = host_page if await host_page.query_selector(".prompt-choices") else guest_page
    guesser_page = guest_page if drawer_page is host_page else host_page
    if await drawer_page.query_selector(".prompt-choices button"):
        await drawer_page.click(".prompt-choices button:first-child")
    await drawer_page.wait_for_selector("canvas.drawing-canvas")
    await guesser_page.wait_for_selector("canvas.drawing-canvas")
    return drawer_page, guesser_page


@pytest.mark.asyncio
@pytest.mark.parametrize("color_scheme,theme", [("light", "light"), ("dark", "dark")])
async def test_lobby_and_settings_axe_and_keyboard(color_scheme, theme):
    playwright, browser, context, page = await _open_chromium(color_scheme, theme)
    try:
        await page.goto(BASE_URL)
        await page.wait_for_selector('button:has-text("Create room")')
        await assert_no_axe_violations(page, f"lobby {theme}")

        settings_button = page.get_by_role("button", name="Player settings")
        await settings_button.click()
        dialog = page.get_by_role("dialog", name="Settings")
        await dialog.wait_for()
        assert await dialog.get_attribute("aria-modal") == "true"
        assert await page.evaluate(
            "() => document.activeElement?.getAttribute('aria-label')"
        ) == "Close settings"

        await page.keyboard.press("Tab")
        assert await page.evaluate(
            """() => {
              const dialog = document.querySelector('[role="dialog"][aria-modal="true"]');
              return dialog.contains(document.activeElement);
            }"""
        )
        await page.keyboard.press("Shift+Tab")
        assert await page.evaluate(
            "() => document.activeElement?.getAttribute('aria-label')"
        ) == "Close settings"

        await page.keyboard.press("Escape")
        await dialog.wait_for(state="hidden")
        assert await page.evaluate(
            "() => document.activeElement?.classList.contains('header-settings-button')"
        )
        await assert_no_axe_violations(page, f"lobby after settings {theme}")
    finally:
        await _close(playwright, browser, context)


@pytest.mark.asyncio
async def test_create_room_and_invite_axe():
    playwright, browser, context, page = await _open_chromium()
    try:
        await page.goto(BASE_URL)
        await use_guest_name(page, "A11yCreator")
        await page.click('button:has-text("Create room")')
        await page.wait_for_selector("text=Create a room")
        await assert_no_axe_violations(page, "create room")

        await page.click('button:has-text("Create room")')
        await page.wait_for_selector('[data-testid="waiting-room"]')
        await assert_no_axe_violations(page, "host waiting room")

        code = await room_code(page)
    finally:
        await _close(playwright, browser, context)

    playwright, browser, context, page = await _open_chromium()
    try:
        await page.goto(f"{BASE_URL}/room/{code}")
        await page.wait_for_selector(".invite-join-form")
        await assert_no_axe_violations(page, "invite entry")
    finally:
        await _close(playwright, browser, context)


@pytest.mark.asyncio
async def test_settings_confirmation_drawer_and_moderation_keyboard():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
    host_context = await browser.new_context()
    guest_context = await browser.new_context()
    host_page = await host_context.new_page()
    guest_page = await guest_context.new_page()
    host_page.set_default_timeout(15000)
    guest_page.set_default_timeout(15000)
    try:
        code = await _create_waiting_room(host_page, "A11yHost", rounds=1)
        await _join_by_code(guest_page, code, "A11yGuest")
        drawer_page, guesser_page = await _start_drawing_round(host_page, guest_page)

        canvas = drawer_page.locator("canvas.drawing-canvas").first
        assert "drawing" in (await canvas.get_attribute("aria-label") or "").lower()
        preview = drawer_page.locator("canvas.preview-canvas")
        assert await preview.get_attribute("aria-hidden") == "true"

        await assert_no_axe_violations(drawer_page, "drawing")
        await assert_no_axe_violations(guesser_page, "guessing")

        await drawer_page.click(".game-header-leave-button")
        dialog = drawer_page.locator('[role="alertdialog"]')
        await dialog.wait_for()
        await assert_no_axe_violations(drawer_page, "leave confirmation")
        await drawer_page.keyboard.press("Escape")
        await dialog.wait_for(state="hidden")

        await host_page.set_viewport_size({"width": 800, "height": 900})
        open_drawer = host_page.get_by_test_id("open-players-drawer")
        await open_drawer.click()
        drawer = host_page.get_by_test_id("players-drawer")
        await drawer.wait_for()
        assert await drawer.get_attribute("aria-modal") == "true"
        assert await host_page.evaluate(
            "() => document.activeElement?.getAttribute('aria-label')"
        ) == "Close players"
        await host_page.keyboard.press("Tab")
        assert await host_page.evaluate(
            """() => document.querySelector('[data-testid="players-drawer"]').contains(document.activeElement)"""
        )
        await assert_no_axe_violations(host_page, "players drawer")

        menu_button = drawer.get_by_role("button", name="Moderation for A11yGuest")
        if await menu_button.count() == 0:
            menu_button = drawer.get_by_role("button", name="Moderation for A11yHost")
        await menu_button.focus()
        await host_page.keyboard.press("Enter")
        menu = drawer.get_by_role("menu")
        await menu.wait_for()
        assert await host_page.evaluate(
            "() => document.activeElement?.getAttribute('role')"
        ) == "menuitem"
        await host_page.keyboard.press("Escape")
        await menu.wait_for(state="hidden")
        assert await host_page.evaluate(
            "() => document.activeElement?.getAttribute('aria-label')?.startsWith('Moderation for')"
        )
        await host_page.keyboard.press("Escape")
        await drawer.wait_for(state="hidden")
        assert await host_page.evaluate(
            "() => document.activeElement?.getAttribute('data-testid') === 'open-players-drawer'"
        )

        await host_page.set_viewport_size({"width": 1280, "height": 720})
        prompt = await drawer_page.locator(".prompt-reveal").inner_text()
        await guesser_page.locator(".chat-input input").fill(prompt)
        await guesser_page.locator(".chat-input input").press("Enter")
        await guesser_page.wait_for_selector('[data-testid="turn-results-overlay"]')
        await assert_no_axe_violations(guesser_page, "turn results")

        await guesser_page.wait_for_selector('[data-testid="turn-results-overlay"]', state="detached")
        next_drawer = host_page if await host_page.query_selector(".prompt-choices") else guest_page
        next_guesser = guest_page if next_drawer is host_page else host_page
        if await next_drawer.query_selector(".prompt-choices button"):
            await next_drawer.click(".prompt-choices button:first-child")
        await next_drawer.wait_for_selector(".prompt-reveal")
        next_word = await next_drawer.locator(".prompt-reveal").inner_text()
        await next_guesser.locator(".chat-input input").fill(next_word)
        await next_guesser.locator(".chat-input input").press("Enter")
        await next_guesser.wait_for_selector('[data-testid="game-end-overlay"]')
        await assert_no_axe_violations(next_guesser, "game end")
    finally:
        await host_context.close()
        await guest_context.close()
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_guest_waiting_room_axe():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
    host_context = await browser.new_context()
    guest_context = await browser.new_context()
    host_page = await host_context.new_page()
    guest_page = await guest_context.new_page()
    try:
        code = await _create_waiting_room(host_page, "WaitHost")
        await _join_by_code(guest_page, code, "WaitGuest")
        await assert_no_axe_violations(guest_page, "guest waiting room")
    finally:
        await host_context.close()
        await guest_context.close()
        await browser.close()
        await playwright.stop()
