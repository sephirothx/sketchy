"""The scratch pad (#829, #591): something to draw on while the connection is down, and while a room waits for players."""

from playwright.async_api import Page, async_playwright
from tests.e2e.lobby_helpers import use_guest_name


BASE_URL = "http://localhost:8000"

INKED_PIXELS = """(canvas) => {
  const { data } = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height);
  let inked = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i] < 200 || data[i + 1] < 200 || data[i + 2] < 200) inked += 1;
  }
  return inked;
}"""


CLEAR = ".clear-button, .toolbar-mobile-clear"
UNDO = ".undo-button, .toolbar-mobile-chip[aria-label='Undo last stroke']"


async def scribble(page: Page, pad_selector: str) -> None:
    canvas = page.locator(f"{pad_selector} .drawing-canvas")
    box = await canvas.bounding_box()
    assert box is not None
    await page.mouse.move(box["x"] + box["width"] * 0.2, box["y"] + box["height"] * 0.3)
    await page.mouse.down()
    await page.mouse.move(box["x"] + box["width"] * 0.7, box["y"] + box["height"] * 0.6, steps=12)
    await page.mouse.up()


async def inked(page: Page, pad_selector: str) -> int:
    return await page.locator(f"{pad_selector} .drawing-canvas").evaluate(INKED_PIXELS)


async def test_the_lobby_offers_the_pad_while_offline_and_keeps_it_when_the_connection_returns():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "PadLobby")
            await page.wait_for_selector(".lobby-rooms-panel")
            assert await page.locator('[data-testid="open-scratch-pad"]').count() == 0

            await context.set_offline(True)
            await page.click('.connection-status-banner [data-testid="open-scratch-pad"]')
            pad = '.scratch-pad-dialog [data-testid="scratch-pad"]'
            await page.wait_for_selector(pad)
            assert await inked(page, pad) == 0
            await scribble(page, pad)
            drawn = await inked(page, pad)
            assert drawn > 100

            # The connection coming back takes the banner away, not the drawing.
            await context.set_offline(False)
            await page.wait_for_selector(".connection-status-banner", state="hidden", timeout=10000)
            assert await inked(page, pad) == drawn

            # The game's own toolbar: a clear, then an undo that takes it back.
            await page.locator(pad).locator(CLEAR).click()
            assert await inked(page, pad) == 0
            await page.locator(pad).locator(UNDO).click()
            assert await inked(page, pad) == drawn
            await page.click('.scratch-pad-dialog button:has-text("Close")')
            await page.wait_for_selector(".scratch-pad-dialog", state="detached")
        finally:
            await context.close()
            await browser.close()


async def test_a_paused_room_carries_the_pad_and_the_tab_keeps_the_drawing():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "PadRoom")
            await page.click('button:has-text("Create room")')
            await page.wait_for_selector(".create-room-page")
            await page.click('button:has-text("Create room")')
            await page.wait_for_selector('[data-testid="waiting-room"]')

            await context.set_offline(True)
            pad = '[data-testid="room-stage-paused"] [data-testid="scratch-pad"]'
            await page.wait_for_selector(pad, timeout=5000)
            # Inside the card, outside the inert stage: it takes the pointer.
            await scribble(page, pad)
            drawn = await inked(page, pad)
            assert drawn > 100

            await context.set_offline(False)
            await page.wait_for_selector('[data-testid="room-stage-paused"]', state="detached", timeout=10000)

            # A second outage finds the first drawing where it was left.
            await context.set_offline(True)
            await page.wait_for_selector(pad, timeout=5000)
            assert await inked(page, pad) == drawn
            await context.set_offline(False)
            await page.wait_for_selector('[data-testid="room-stage-paused"]', state="detached", timeout=10000)
        finally:
            await context.close()
            await browser.close()


async def test_a_host_alone_in_a_new_room_has_the_pad_and_an_outage_carries_it_over():
    """#591: the waiting room offered a disabled Start and nothing else. The pad
    takes the column from one button in view, fits it without scrolling, and
    gives it back. And two pads can be on screen at once - the room's, and the
    paused card's over it - so what is drawn on one is what the other shows."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "PadHost")
            await page.click('button:has-text("Create room")')
            await page.wait_for_selector(".create-room-page")
            await page.click('button:has-text("Create room")')
            await page.wait_for_selector('[data-testid="waiting-room"]')

            await page.click('[data-testid="open-waiting-pad"]')
            room_pad = '.waiting-room.is-drawing [data-testid="scratch-pad"]'
            await page.wait_for_selector(room_pad)
            assert await page.locator(".waiting-rules-card").count() == 0
            assert await page.evaluate("document.activeElement?.dataset.testid") == "close-waiting-pad"
            # Start stays one press away, and nothing of the pad is below the fold.
            assert await page.locator(".waiting-pad-strip .waiting-start-button").count() == 1
            bottom = await page.evaluate(
                "document.querySelector('.waiting-room.is-drawing .scratch-pad').getBoundingClientRect().bottom"
            )
            assert bottom <= 800, f"the pad runs to {bottom}px on an 800px window"
            canvas_box = await page.locator(f"{room_pad} .drawing-canvas").bounding_box()
            assert canvas_box is not None and canvas_box["width"] >= 600

            await scribble(page, room_pad)
            first = await inked(page, room_pad)
            assert first > 100

            await context.set_offline(True)
            paused_pad = '[data-testid="room-stage-paused"] [data-testid="scratch-pad"]'
            await page.wait_for_selector(paused_pad, timeout=5000)
            assert await inked(page, paused_pad) == first
            await page.locator(paused_pad).locator(CLEAR).click()
            assert await inked(page, paused_pad) == 0

            await context.set_offline(False)
            await page.wait_for_selector('[data-testid="room-stage-paused"]', state="detached", timeout=10000)
            # Cleared on the card, so cleared in the room: the room's pad must not
            # keep the older sheet it was showing underneath.
            assert await inked(page, room_pad) == 0

            await page.click('[data-testid="close-waiting-pad"]')
            await page.wait_for_selector(".waiting-rules-card")
            assert await page.evaluate("document.activeElement?.dataset.testid") == "open-waiting-pad"
        finally:
            await context.close()
            await browser.close()
