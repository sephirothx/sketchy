"""A pen's pressure reaches every screen as the same line (#828).

The drawer's browser turns pressure into widths, thins the samples keeping
the points two widths share, paints its own canvas from what it kept and
sends the changes inside the frames it was sending anyway; a viewer plays
them out over time, and a client that joins late replays them from the
history. All three have to be one raster - a fill depends on it - and the
line has to actually be thinner where the hand was lighter.

The pen is Chromium's own: `Input.dispatchMouseEvent` takes a `pointerType`
and a `force`, so these are trusted pointer events with a real `pressure`,
not synthetic ones the capture call would refuse.
"""
from uuid import uuid4

from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import join_by_code, room_code, use_guest_name

BASE_URL = "http://localhost:8000"

CANVAS_PNG = "() => document.querySelector('canvas.drawing-canvas').toDataURL()"

# How many pixels of ink the column at canvas x holds: the line's thickness
# there, since the stroke is horizontal.
INK_IN_COLUMN = """
(x) => {
  const canvas = document.querySelector('canvas.drawing-canvas');
  const data = canvas.getContext('2d').getImageData(x, 0, 1, canvas.height).data;
  let ink = 0;
  for (let index = 0; index < data.length; index += 4) if (data[index] !== 255) ink += 1;
  return ink;
}
"""


async def _pen(cdp, kind: str, x: float, y: float, force: float) -> None:
    await cdp.send("Input.dispatchMouseEvent", {
        "type": kind, "x": x, "y": y, "button": "left",
        "buttons": 0 if kind == "mouseReleased" else 1,
        "clickCount": 1, "pointerType": "pen", "force": force,
    })


async def test_a_pen_stroke_is_one_raster_on_the_drawer_a_viewer_and_a_replay():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_page = await (await browser.new_context()).new_page()
        player_page = await (await browser.new_context()).new_page()
        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, f"PenHost{uuid4().hex[:6]}")
            await host_page.click('button:has-text("Create room")')
            await host_page.click('[role="group"][aria-label="Visibility"] button:has-text("Private")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host_page)

            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, f"PenView{uuid4().hex[:6]}")
            await join_by_code(player_page, code)
            await player_page.wait_for_selector('[data-testid="waiting-room"]')

            await host_page.click('.waiting-start-button')
            await host_page.wait_for_selector('.prompt-choices, [data-testid="choosing-prompt-status"]')
            drawing = host_page if await host_page.query_selector('.prompt-choices') else player_page
            viewing = player_page if drawing is host_page else host_page
            await drawing.click('.prompt-choices button:first-child')
            await drawing.wait_for_selector('canvas.drawing-canvas')
            await viewing.wait_for_selector('canvas.drawing-canvas')

            canvas = await drawing.query_selector('canvas.drawing-canvas')
            box = await canvas.bounding_box()
            assert box is not None
            scale = box["width"] / 800
            cdp = await drawing.context.new_cdp_session(drawing)

            # One straight line, left to right: the hand lands lightly, leans
            # in all the way, and eases off again. Straight, so every point
            # the thinner keeps is kept for its width.
            y = box["y"] + 300 * scale
            await _pen(cdp, "mousePressed", box["x"] + 100 * scale, y, 0.02)
            for step in range(1, 241):
                lean = step / 120 if step <= 120 else (240 - step) / 120
                await _pen(cdp, "mouseMoved", box["x"] + (100 + step * 2.5) * scale, y, max(0.02, lean))
            await _pen(cdp, "mouseReleased", box["x"] + 700 * scale, y, 0)

            light, heavy, easing = [
                await drawing.evaluate(INK_IN_COLUMN, x) for x in (110, 400, 690)
            ]
            assert heavy == 6, f"full pressure is the selected size, got {heavy}"
            assert light <= 3 and easing <= 3, f"a light hand is thinner: {light}, {easing}"

            drawer_png = await drawing.evaluate(CANVAS_PNG)
            await viewing.wait_for_function(
                "expected => document.querySelector('canvas.drawing-canvas').toDataURL() === expected",
                arg=drawer_png,
            )
            # The eraser does not thin: a light pass still removes its full width.
            # By its shortcut: which toolbar arrangement is showing depends on
            # the column's width, and the key does not.
            await drawing.keyboard.press("e")
            await _pen(cdp, "mousePressed", box["x"] + 400 * scale, box["y"] + 250 * scale, 0.05)
            for step in range(1, 21):
                await _pen(cdp, "mouseMoved", box["x"] + 400 * scale, box["y"] + (250 + step * 5) * scale, 0.05)
            await _pen(cdp, "mouseReleased", box["x"] + 400 * scale, box["y"] + 350 * scale, 0)
            # 24 px wide, so eight pixels off its centre is gone; at the
            # quarter a light hand would have thinned it to, it would not be.
            assert await drawing.evaluate(INK_IN_COLUMN, 392) == 0
            assert await drawing.evaluate(INK_IN_COLUMN, 380) == 6
            erased_png = await drawing.evaluate(CANVAS_PNG)
            await viewing.wait_for_function(
                "expected => document.querySelector('canvas.drawing-canvas').toDataURL() === expected",
                arg=erased_png,
            )
            # And from the history alone: somebody who joins now was sent none of
            # the frames, and replays both paths whole. A third seat rather
            # than a reload of the second: a two-seat room that sees a seat
            # leave resets the turn and wipes the canvas on every screen, so
            # whether a reload found the drawing depended on how fast it was.
            late_page = await (await browser.new_context()).new_page()
            await late_page.goto(BASE_URL)
            await use_guest_name(late_page, f"PenLate{uuid4().hex[:6]}")
            await join_by_code(late_page, viewing.url.rstrip("/").split("/")[-1])
            await late_page.wait_for_selector('canvas.drawing-canvas')
            await late_page.wait_for_function(
                "expected => document.querySelector('canvas.drawing-canvas').toDataURL() === expected",
                arg=erased_png,
            )
        finally:
            await browser.close()
