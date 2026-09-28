"""A phone held sideways keeps its canvas in a Wheel of Fortune room, and the
feed column takes the width the canvas leaves.

Sideways the wheel's 26 keys sat above the canvas and left a guesser 18% of the
drawing - 170 x 126 at 844 x 390 - while the feed column was a fixed 180px
beside a canvas bound by the height, so the guess field read "Type your g"
with 262px unused in the main column (#1267). The keys now wait behind "Buy a
letter", over the canvas, and the column is sized from the slack (180-320px).
"""
from uuid import uuid4

from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import (
    join_by_code,
    open_new_room,
    open_room_settings,
    open_settings_section,
    room_code,
    save_room_settings,
    use_guest_name,
)

BASE_URL = "http://localhost:8000"

LAYOUT = """
() => {
  const box = (selector) => {
    const element = document.querySelector(selector);
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    return { width: rect.width, height: rect.height };
  };
  const input = document.querySelector('.chat-input input');
  const style = input && getComputedStyle(input);
  return {
    canvas: box('canvas.drawing-canvas'),
    feed: box('.room-shell-chat'),
    text: input ? input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) : null,
    sideways: document.documentElement.scrollWidth > window.innerWidth,
  };
}
"""


async def test_a_sideways_wheel_room_keeps_the_canvas_and_widens_the_feed():
    phone = {"viewport": {"width": 844, "height": 390}, "is_mobile": True, "has_touch": True}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context(**phone) for _ in range(2)]
        host, guest = [await context.new_page() for context in contexts]
        try:
            tag = uuid4().hex[:5]
            await host.goto(BASE_URL)
            await use_guest_name(host, f"WheelHost{tag}")
            await open_new_room(host)
            code = await room_code(host)
            await guest.goto(BASE_URL)
            await use_guest_name(guest, f"WheelGuest{tag}")
            await join_by_code(guest, code)
            await guest.wait_for_selector('[data-testid="waiting-room"]')
            await open_room_settings(host)
            await open_settings_section(host, "Scoring and hints")
            await host.locator('[aria-label="Hints"] button:has-text("Wheel of Fortune")').click()
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("umbrella\nlighthouse")
            await host.get_by_label("Only use custom prompts").check()
            await save_room_settings(host)
            await host.get_by_role("button", name="Start game").click()
            await host.wait_for_selector('.prompt-choices, [data-testid="choosing-prompt-status"]')
            drawer = host if await host.query_selector(".prompt-choices") else guest
            guesser = guest if drawer is host else host
            await drawer.click(".prompt-choices button:first-child")
            await drawer.wait_for_selector("canvas.drawing-canvas.drawable")

            toggle = guesser.get_by_role("button", name="Buy a letter")
            for size in ({"width": 844, "height": 390}, {"width": 740, "height": 360}):
                for page in (drawer, guesser):
                    await page.set_viewport_size(size)
                await toggle.wait_for()
                await guesser.wait_for_timeout(300)
                guessing = await guesser.evaluate(LAYOUT)
                drawing = await drawer.evaluate(LAYOUT)
                # The keys are behind the toggle, not above the canvas.
                assert await guesser.locator(".wheel-hint-panel").count() == 0
                # The guesser's canvas is a drawer's, less the one tile row.
                assert guessing["canvas"]["height"] >= drawing["canvas"]["height"] - 16, (size, guessing, drawing)
                # The column is wider than the old 180px, and the field shows
                # its placeholder whole.
                assert guessing["feed"]["width"] > 250 and guessing["text"] >= 200, (size, guessing)
                assert not guessing["sideways"] and not drawing["sideways"]

            # One tap opens the keys over the canvas; buying one closes them.
            spent_before = await guesser.locator(".hint-spend-total").count()
            await toggle.click()
            keys = guesser.get_by_test_id("wheel-hint-popover")
            await keys.wait_for()
            await keys.locator(".wheel-letter-btn:not(:disabled)").first.click()
            await keys.wait_for(state="detached")
            assert spent_before == 0
            await guesser.locator(".hint-spend-total").wait_for()

            # A short phone gives the drawer no slack: the column keeps 180px
            # and the canvas is what it was.
            for page in (drawer, guesser):
                await page.set_viewport_size({"width": 667, "height": 375})
            await drawer.wait_for_timeout(300)
            drawing = await drawer.evaluate(LAYOUT)
            assert drawing["canvas"]["width"] >= 380 and drawing["canvas"]["height"] >= 285, drawing
        finally:
            for context in contexts:
                await context.close()
            await browser.close()
