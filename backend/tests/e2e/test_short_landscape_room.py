"""A large phone held sideways, and a short desktop window, get a canvas.

Above 900px wide and at most 520px tall the room chose its desktop DOM while
the phone's landscape stylesheet, which has no upper width, laid itself over
it: the empty dock took a track of the desktop grid, the stage fell into the
chat's column and the canvas came out 0 x 0 for the drawer and the guessers
alike - iPhone Pro Max and Plus, Pixel-class phones sideways, a 1180 x 520
window (#1261). Those viewports are phones to the room now, in the components
and the stylesheets by one rule (`PHONE_ROOM_QUERY`, lib/roomLayout.ts).
"""
from uuid import uuid4

from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import join_by_code, open_create_room, room_code, use_guest_name

BASE_URL = "http://localhost:8000"

CANVAS_BOX = """
() => {
  const box = document.querySelector('canvas.drawing-canvas').getBoundingClientRect();
  return { width: box.width, height: box.height };
}
"""
INK = """
() => {
  const canvas = document.querySelector('canvas.drawing-canvas');
  const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
  let ink = 0;
  for (let index = 0; index < data.length; index += 4) if (data[index] !== 255) ink += 1;
  return ink;
}
"""


async def _start_turn(host_page, player_page):
    await host_page.goto(BASE_URL)
    await use_guest_name(host_page, f"WideHost{uuid4().hex[:6]}")
    await open_create_room(host_page)
    await host_page.click('[role="group"][aria-label="Visibility"] button:has-text("Private")')
    await host_page.click('button:has-text("Create room")')
    await host_page.wait_for_selector('[data-testid="waiting-room"]')
    code = await room_code(host_page)
    await player_page.goto(BASE_URL)
    await use_guest_name(player_page, f"WideView{uuid4().hex[:6]}")
    await join_by_code(player_page, code)
    await player_page.wait_for_selector('[data-testid="waiting-room"]')
    await host_page.click('.waiting-start-button')
    await host_page.wait_for_selector('.prompt-choices, [data-testid="choosing-prompt-status"]')
    drawing = host_page if await host_page.query_selector('.prompt-choices') else player_page
    viewing = player_page if drawing is host_page else host_page
    await drawing.click('.prompt-choices button:first-child')
    await drawing.wait_for_selector('canvas.drawing-canvas.drawable')
    await viewing.wait_for_selector('canvas.drawing-canvas')
    return drawing, viewing


async def test_a_large_phone_sideways_draws_and_watches_on_a_real_canvas():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        phone = {"viewport": {"width": 932, "height": 430}}
        contexts = [await browser.new_context(**phone), await browser.new_context(**phone)]
        host_page, player_page = [await context.new_page() for context in contexts]
        try:
            drawing, viewing = await _start_turn(host_page, player_page)
            ink = 0
            for row, size in enumerate((
                {"width": 932, "height": 430},
                {"width": 915, "height": 412},
                {"width": 956, "height": 440},
                {"width": 1180, "height": 520},
            )):
                for page in (drawing, viewing):
                    await page.set_viewport_size(size)
                for page in (drawing, viewing):
                    # The phone's room: its bar, and the tools docked as a rail.
                    await page.locator(".game-header-mobile").wait_for(state="visible")
                    box = await page.evaluate(CANVAS_BOX)
                    assert box["width"] >= 400 and box["height"] >= 300, (size, box)
                    # Nothing past the right edge: the page does not scroll sideways.
                    assert await page.evaluate(
                        "() => document.documentElement.scrollWidth <= window.innerWidth"
                    ), size
                await drawing.locator("#room-shell-dock .toolbar-mobile").wait_for(state="visible")

                # And the drawer can draw there: the guesser receives the
                # stroke. A row of its own each time, so it is new ink.
                canvas = await drawing.query_selector("canvas.drawing-canvas")
                box = await canvas.bounding_box()
                y = box["y"] + box["height"] * (0.2 + row * 0.2)
                await drawing.mouse.move(box["x"] + box["width"] * 0.2, y)
                await drawing.mouse.down()
                for step in range(1, 11):
                    await drawing.mouse.move(box["x"] + box["width"] * (0.2 + step * 0.05), y, steps=2)
                await drawing.mouse.up()
                await viewing.wait_for_function(f"(before) => ({INK})() > before", arg=ink)
                ink = await viewing.evaluate(INK)

            # The room's sheets rise from the bottom as a phone's do.
            await viewing.get_by_test_id("open-room-menu").click()
            sheet = viewing.get_by_test_id("room-menu-sheet")
            await sheet.wait_for()
            await viewing.locator(".game-room .bottom-sheet-grab").wait_for(state="visible")
        finally:
            for context in contexts:
                await context.close()
            await browser.close()
