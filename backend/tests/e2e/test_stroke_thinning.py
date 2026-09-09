"""The drawer's canvas and a viewer's are one raster (#560).

The client thins a brush stroke's pointer samples before sending them, and
paints its own canvas from the samples it kept rather than from the raw
pointer. So after a stroke, the drawer's canvas and the viewer's must agree
pixel for pixel: both were rasterized from the same polyline. That is the
guarantee a flood fill depends on - an edge in one place on the drawer's
screen and half a pixel away on a viewer's would let a fill leak on one and
not the other - and it is what this checks, with a wavy stroke of many
samples so that the thinner has something to drop.
"""
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import join_by_code, room_code, use_guest_name

BASE_URL = "http://localhost:8000"

CANVAS_PNG = """
() => document.querySelector('canvas.drawing-canvas').toDataURL()
"""

HAS_INK = """
() => {
  const canvas = document.querySelector('canvas.drawing-canvas');
  const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
  for (let index = 0; index < data.length; index += 4) {
    if (data[index] !== 255 || data[index + 1] !== 255 || data[index + 2] !== 255) return true;
  }
  return false;
}
"""

PREVIEW_IS_CLEAR = """
() => {
  const canvas = document.querySelector('canvas.preview-canvas');
  if (!canvas) return true;
  const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
  for (let index = 3; index < data.length; index += 4) if (data[index] !== 0) return false;
  return true;
}
"""


async def test_the_drawer_and_a_viewer_rasterize_the_same_thinned_stroke():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        host_page = await host_context.new_page()
        player_page = await player_context.new_page()
        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "ThinHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.click(
                '[role="group"][aria-label="Visibility"] button:has-text("Private")'
            )
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host_page)

            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "ThinViewer")
            await join_by_code(player_page, code)
            await player_page.wait_for_selector('[data-testid="waiting-room"]')

            await host_page.click('.waiting-start-button')
            await host_page.wait_for_selector(
                '.prompt-choices, [data-testid="choosing-prompt-status"]'
            )
            drawing = host_page if await host_page.query_selector('.prompt-choices') else player_page
            viewing = player_page if drawing is host_page else host_page
            await drawing.click('.prompt-choices button:first-child')
            await drawing.wait_for_selector('canvas.drawing-canvas')
            await viewing.wait_for_selector('canvas.drawing-canvas')

            canvas = await drawing.query_selector('canvas.drawing-canvas')
            box = await canvas.bounding_box()
            assert box is not None

            # A slow wave, sampled densely: straight runs the thinner drops,
            # bends it keeps, and a hairpin back along the same line.
            await drawing.mouse.move(box["x"] + 40, box["y"] + 100)
            await drawing.mouse.down()
            for step in range(1, 121):
                x = 40 + step * 3
                y = 100 + (60 if (step // 30) % 2 else -60) * ((step % 30) / 30)
                await drawing.mouse.move(box["x"] + x, box["y"] + y, steps=2)
            await drawing.mouse.move(box["x"] + 200, box["y"] + 100, steps=40)
            await drawing.mouse.move(box["x"] + 60, box["y"] + 100, steps=40)
            await drawing.mouse.up()

            await viewing.wait_for_function(HAS_INK)
            # The preview segment under the pen is gone once the stroke ends:
            # what is left on the drawer's screen is the kept polyline alone.
            await drawing.wait_for_function(PREVIEW_IS_CLEAR)
            # Whatever the viewer has, it has to converge on the drawer's
            # canvas; polled rather than sampled once, since the last frame
            # may still be in flight.
            drawer_png = await drawing.evaluate(CANVAS_PNG)
            await viewing.wait_for_function(
                "expected => document.querySelector('canvas.drawing-canvas').toDataURL() === expected",
                arg=drawer_png,
            )
        finally:
            await browser.close()
