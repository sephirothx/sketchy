"""The host's tool and color rules, from the lobby through to the canvas."""
import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import (
    open_room_settings,
    open_settings_section,
    room_code,
    save_room_settings,
    use_guest_name,
)


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_the_rules_the_host_sets_reach_the_lobby_and_then_the_toolbar():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        host_page = await host_context.new_page()
        player_page = await player_context.new_page()
        try:
            # The host picks the rules while creating the room.
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "RulesHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.fill(
                'input[placeholder="Leave blank for a random name!"]', "Freehand studio"
            )
            # Private: this room is reached by code, and a public one would sit
            # in the lobby list every other test is reading.
            await host_page.click('[role="group"][aria-label="Visibility"] button:has-text("Private")')
            await host_page.click('summary:has-text("Drawing")')
            await host_page.click('fieldset:has(legend:text-is("Allowed tools")) button:has-text("Fill")')
            await host_page.click('fieldset:has(legend:text-is("Colors")) button:has-text("Black and white")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')

            code = await room_code(host_page)

            # Everyone else reads them off the waiting-room rules.
            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "RulesPlayer")
            await player_page.fill('input[placeholder="ABC123"]', code)
            await player_page.click('button:has-text("Join by code")')
            await player_page.wait_for_selector('[data-testid="waiting-room"]')
            await player_page.wait_for_selector('text=Brush and Shapes, black and white')

            # ...and they follow the host's edits, like every other setting.
            await open_room_settings(host_page)
            await open_settings_section(host_page, "Drawing")
            await host_page.click(
                '.room-settings-editor fieldset:has(legend:text-is("Allowed tools")) button:has-text("Shapes")'
            )

            # The last of brush and shapes cannot be turned off: fill alone
            # would leave the room with nothing to draw with. The chip knows
            # that before anything is saved.
            brush_chip = host_page.locator(
                '.room-settings-editor fieldset:has(legend:text-is("Allowed tools")) button:has-text("Brush")'
            )
            assert await brush_chip.is_disabled()

            await save_room_settings(host_page)
            await player_page.wait_for_selector('text=Brush only, black and white')

            # In the game, the toolbar offers only what the room allows.
            # The drawer has to be identified while the choosing phase is still
            # up: waiting for the canvas first lets that phase time out, and
            # then neither page is holding the prompt choices any more.
            await host_page.click('.waiting-start-button')
            await host_page.wait_for_selector('.prompt-choices, [data-testid="choosing-prompt-status"]')
            drawer_page = (
                host_page if await host_page.query_selector('.prompt-choices') else player_page
            )
            await drawer_page.click('.prompt-choices button:first-child')
            await drawer_page.wait_for_selector('canvas.drawing-canvas')
            await drawer_page.wait_for_selector('.toolbar-tools')

            tools = await drawer_page.eval_on_selector_all(
                '.toolbar-tools .tool-button',
                "buttons => buttons.map(button => button.getAttribute('aria-label'))",
            )
            assert [tool.split(' (')[0] for tool in tools] == ["Brush", "Eraser"]

            # Black and white leaves two swatches and no custom color picker.
            swatches = await drawer_page.eval_on_selector_all(
                '.toolbar-colors .color-swatch',
                "swatches => swatches.map(swatch => swatch.getAttribute('aria-label'))",
            )
            assert swatches == ["color #000000", "color #ffffff"]
            assert not await drawer_page.is_visible('.toolbar-colors .color-swatch-custom')

            # A palette that is not built from light/dark pairs is laid out
            # flat, so no swatch is left dangling in a second row.
            assert await drawer_page.eval_on_selector(
                '.toolbar-colors',
                "palette => getComputedStyle(palette).gridTemplateRows.split(' ').length",
            ) == 1
        finally:
            await browser.close()
