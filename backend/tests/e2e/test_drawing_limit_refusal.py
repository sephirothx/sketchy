"""When the turn's drawing limit refuses a frame, the drawer's canvas goes back
to what the room has.

The client paints a stroke as it is drawn and sends it in frames; a frame that
does not fit what is left of the limit is refused whole. Its points were ink
on the drawer's canvas already, and used to stay there: the room had the
stroke up to the last frame that went, the drawer saw more, and a fill on the
drawer's screen could flood a region nobody else had. A pen makes this easy
to reach - a width keyframe is an entry of its own, so a single point can be
refused with one entry left, and the limit still reads as open.

The limit is 25,000 entries, which no test should draw. The client's copy of
it is lowered in the bundle as it is served - the client is the stricter of
the two by design (R-DRAW-08), so the server never sees a frame it would
refuse - and the test fails loudly if the constant is no longer where it was.
"""
import math
import re
from uuid import uuid4

from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import join_by_code, room_code, use_guest_name

BASE_URL = "http://localhost:8000"
CLIENT_LIMIT = 60

CANVAS_PNG = "() => document.querySelector('canvas.drawing-canvas').toDataURL()"
INK = """
() => {
  const canvas = document.querySelector('canvas.drawing-canvas');
  const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
  let ink = 0;
  for (let index = 0; index < data.length; index += 4) if (data[index] !== 255) ink += 1;
  return ink;
}
"""


async def _lower_the_clients_limit(context, patched: list[int]) -> None:
    """Lower the limit wherever the bundle carries it.

    Every script chunk is searched rather than the entry one: the drawing code
    is fetched with the room since #475, and which chunk holds the constant is
    the bundler's business. `patched` gets one total per context, counted once
    per chunk however often the browser fetches it (a preload and the import
    are two requests), so the assertion below still says it was found exactly
    once."""
    found: dict[str, int] = {}
    patched.append(0)
    slot = len(patched) - 1

    async def handle(route):
        response = await route.fetch()
        body = await response.text()
        body, count = re.subn(r"\b25e3\b", str(CLIENT_LIMIT), body)
        found[route.request.url] = count
        patched[slot] = sum(found.values())
        await route.fulfill(response=response, body=body)

    await context.route(re.compile(r".*/assets/[^/]*\.js$"), handle)


async def _start_turn(host_page, player_page):
    await host_page.goto(BASE_URL)
    await use_guest_name(host_page, f"LimitHost{uuid4().hex[:6]}")
    await host_page.click('button:has-text("Create room")')
    await host_page.click('[role="group"][aria-label="Visibility"] button:has-text("Private")')
    await host_page.click('button:has-text("Create room")')
    await host_page.wait_for_selector('[data-testid="waiting-room"]')
    code = await room_code(host_page)
    await player_page.goto(BASE_URL)
    await use_guest_name(player_page, f"LimitView{uuid4().hex[:6]}")
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


async def _zigzag(cdp, box, *, pointer: str) -> None:
    """A stroke of far more kept points than the lowered limit allows: every
    sample a corner, so the thinner keeps them all, and - for a pen - a
    pressure that never settles, so keyframes keep coming."""
    scale = box["width"] / 800

    async def event(kind, x, y, force):
        await cdp.send("Input.dispatchMouseEvent", {
            "type": kind, "x": box["x"] + x * scale, "y": box["y"] + y * scale, "button": "left",
            "buttons": 0 if kind == "mouseReleased" else 1, "clickCount": 1,
            "pointerType": pointer, "force": force,
        })

    await event("mousePressed", 100, 300, 0.1)
    for step in range(1, 201):
        force = 0.1 + 0.6 * abs(math.sin(step / 9))
        await event("mouseMoved", 100 + step * 3, 300 + (40 if step % 2 else -40), force)
    await event("mouseReleased", 700, 300, 0)


async def _refused_ink_is_painted_out(pointer: str) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context(), await browser.new_context()]
        patched: list[int] = []
        for context in contexts:
            await _lower_the_clients_limit(context, patched)
        host_page, player_page = [await context.new_page() for context in contexts]
        try:
            drawing, viewing = await _start_turn(host_page, player_page)
            assert patched and all(count == 1 for count in patched), (
                f"the client's drawing limit is no longer `25e3` in the bundle ({patched}); "
                "this test lowers it there and means nothing without that"
            )
            canvas = await drawing.query_selector('canvas.drawing-canvas')
            box = await canvas.bounding_box()
            assert box is not None
            cdp = await drawing.context.new_cdp_session(drawing)
            await _zigzag(cdp, box, pointer=pointer)

            # The stroke ran far past the limit, so most of it was refused: what
            # is left on the drawer's canvas is what the room has, and no more.
            await viewing.wait_for_function(f"({INK})() > 0")
            drawer_png = await drawing.evaluate(CANVAS_PNG)
            await viewing.wait_for_function(
                "expected => document.querySelector('canvas.drawing-canvas').toDataURL() === expected",
                arg=drawer_png,
            )
            # And it really was cut short: a zigzag across 600 px of canvas
            # would reach x = 700, and this one stops well before.
            right_edge = await drawing.evaluate("""() => {
              const canvas = document.querySelector('canvas.drawing-canvas');
              const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
              let right = 0;
              for (let y = 0; y < canvas.height; y += 1) for (let x = canvas.width - 1; x > right; x -= 1) {
                if (data[(y * canvas.width + x) * 4] !== 255) { right = x; break; }
              }
              return right;
            }""")
            assert 100 < right_edge < 400, right_edge
        finally:
            await browser.close()


async def test_a_pen_stroke_refused_at_the_limit_leaves_no_ink_the_room_does_not_have():
    await _refused_ink_is_painted_out("pen")


async def test_a_mouse_stroke_refused_at_the_limit_leaves_no_ink_the_room_does_not_have():
    await _refused_ink_is_painted_out("mouse")
