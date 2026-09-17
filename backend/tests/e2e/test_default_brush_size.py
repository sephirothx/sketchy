"""The brush starts a turn at the player's own default size, and the size
control shows where that is and goes back to it in one tap.

Every turn resets the toolbar, so a player who always draws at another size
was reaching for the slider at the start of every turn. On a phone the size
panel is as wide as the screen, so the slider lies along it.
"""
from uuid import uuid4

from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import join_by_code, room_code, use_guest_name

BASE_URL = "http://localhost:8000"

SLIDER_BOX = """
() => {
  const box = document.querySelector('.vertical-brush-slider').getBoundingClientRect();
  return { width: box.width, height: box.height };
}
"""

# How far the default's mark is from the slider's thumb, along the slider,
# when the size *is* the default: the mark has to be where the thumb lands.
MARK_TO_THUMB = """
() => {
  const slider = document.querySelector('.vertical-brush-slider').getBoundingClientRect();
  const mark = document.querySelector('.slider-stop.is-default').getBoundingClientRect();
  const input = document.querySelector('.vertical-brush-slider');
  const fraction = Number(input.value) / Number(input.max);
  const thumb = parseFloat(getComputedStyle(document.querySelector('.slider-track-wrapper')).getPropertyValue('--thumb'));
  const horizontal = slider.width > slider.height;
  const length = horizontal ? slider.width : slider.height;
  const along = thumb / 2 + fraction * (length - thumb);
  const expected = horizontal ? slider.left + along : slider.bottom - along;
  const actual = horizontal ? mark.left + mark.width / 2 : mark.top + mark.height / 2;
  return Math.abs(expected - actual);
}
"""


async def test_a_turn_starts_at_the_players_default_size_and_the_slider_goes_back_to_it():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context(), await browser.new_context()]
        for context in contexts:
            # A guest's copy lives in the browser, where the client reads it on load.
            # The smallest size, at the slider's very end: where a mark laid out
            # without the thumb's width in mind is furthest from the thumb.
            await context.add_init_script("localStorage.setItem('sketchy_defaultbrushsize', '2')")
        host_page, player_page = [await context.new_page() for context in contexts]
        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, f"SizeHost{uuid4().hex[:6]}")
            await host_page.click('button:has-text("Create room")')
            await host_page.click('[role="group"][aria-label="Visibility"] button:has-text("Private")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host_page)
            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, f"SizeView{uuid4().hex[:6]}")
            await join_by_code(player_page, code)
            await player_page.wait_for_selector('[data-testid="waiting-room"]')
            await host_page.click('.waiting-start-button')
            await host_page.wait_for_selector('.prompt-choices, [data-testid="choosing-prompt-status"]')
            drawing = host_page if await host_page.query_selector('.prompt-choices') else player_page
            await drawing.click('.prompt-choices button:first-child')
            await drawing.wait_for_selector('canvas.drawing-canvas')

            size = drawing.get_by_role("button", name="Brush size 2px")
            await size.wait_for()

            # Away from the default by its shortcut, then back by the button.
            await drawing.keyboard.press("]")
            await drawing.keyboard.press("]")
            await drawing.get_by_role("button", name="Brush size 6px").click()
            back = drawing.get_by_role("button", name="Default size, 2px")
            assert await back.get_attribute("aria-pressed") == "false"
            await back.click()
            assert await back.get_attribute("aria-pressed") == "true"
            await drawing.get_by_role("button", name="Brush size 2px").wait_for()
            assert await drawing.evaluate(MARK_TO_THUMB) <= 1.5

            # The eraser's default is its own, and not the setting.
            await drawing.keyboard.press("e")
            await drawing.get_by_role("button", name="Default size, 24px").wait_for()
            await drawing.keyboard.press("p")

            # On a phone the panel spans the screen, and the slider lies along it.
            await drawing.set_viewport_size({"width": 390, "height": 844})
            await drawing.wait_for_selector('.toolbar-mobile-strip')
            await drawing.get_by_role("button", name="Brush size 2px").click()
            await drawing.wait_for_selector('.toolbar-mobile-size-popover')
            phone = await drawing.evaluate(SLIDER_BOX)
            assert phone["width"] > 200 and phone["width"] > phone["height"] * 4, phone
            assert await drawing.evaluate(MARK_TO_THUMB) <= 1.5
            await drawing.locator('.vertical-brush-slider').fill("7")
            await drawing.get_by_role("button", name="Default size, 2px").click()
            assert await drawing.locator('.preview-readout').inner_text() == "2px"
        finally:
            await browser.close()
