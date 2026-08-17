import pytest
from playwright.async_api import Page, async_playwright

BASE_URL = "http://localhost:8000"
CANVAS_CAPS = "globalThis.SKETCHY_MAX_WINDOW_WORK = 400;"
HAS_INK = """
() => {
  const canvas = document.querySelector("canvas.drawing-canvas");
  if (!canvas) return false;
  const data = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
  for (let index = 0; index < data.length; index += 4) {
    if (data[index] !== 255 || data[index + 1] !== 255 || data[index + 2] !== 255) {
      return true;
    }
  }
  return false;
}
"""
PIXEL_HASH = """
() => {
  const canvas = document.querySelector("canvas.drawing-canvas");
  if (!canvas) return null;
  const data = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
  let hash = 2166136261;
  for (let index = 0; index < data.length; index += 31) {
    hash ^= data[index];
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}
"""


async def _wait_for_hash(page: Page, expected: int) -> None:
    for _ in range(50):
        current = await page.evaluate(PIXEL_HASH)
        if current == expected:
            return
        await page.wait_for_timeout(100)
    actual = await page.evaluate(PIXEL_HASH)
    raise AssertionError(f"canvas hash {actual} did not match {expected}")


async def _stable_hash(page: Page) -> int:
    previous = None
    for _ in range(30):
        current = await page.evaluate(PIXEL_HASH)
        if current is not None and current == previous:
            return current
        previous = current
        await page.wait_for_timeout(100)
    raise AssertionError("canvas pixel hash did not stabilize")


async def _create_waiting_room(page: Page, nickname: str) -> str:
    await page.goto(BASE_URL)
    await page.fill('input[placeholder="Your name"]', nickname)
    await page.click('button:has-text("Create room")')
    await page.click('button:has-text("Create room")')
    await page.wait_for_selector('[data-testid="waiting-room"]')
    code_text = await page.inner_text(".room-copy-button")
    return code_text.split("Code:")[1].strip()


async def _join_by_code(page: Page, code: str, nickname: str) -> None:
    await page.goto(BASE_URL)
    await page.fill('input[placeholder="Your name"]', nickname)
    await page.fill('input[placeholder="ABC123"]', code)
    await page.click('button:has-text("Join by code")')
    await page.wait_for_selector('[data-testid="waiting-room"]')


async def _start_drawing_round(host_page: Page, guest_page: Page) -> tuple[Page, Page]:
    await host_page.click('button:has-text("Start game")')
    await host_page.wait_for_selector(".game-layout")
    await guest_page.wait_for_selector(".game-layout")
    drawer_page = host_page if await host_page.query_selector(".word-choices") else guest_page
    guesser_page = guest_page if drawer_page is host_page else host_page
    if await drawer_page.query_selector(".word-choices button"):
        await drawer_page.click(".word-choices button:first-child")
    await drawer_page.wait_for_selector("canvas.drawing-canvas")
    await guesser_page.wait_for_selector("canvas.drawing-canvas")
    return drawer_page, guesser_page


async def _click_canvas_center(page: Page) -> None:
    canvas = page.locator("canvas.drawing-canvas").first
    box = await canvas.bounding_box()
    assert box
    await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


async def _fill_with_color(drawer: Page, observer: Page, color: str) -> None:
    await drawer.locator(f'.toolbar-colors [aria-label="color {color}"]').click()
    await _click_canvas_center(drawer)
    await drawer.wait_for_function(HAS_INK)
    await observer.wait_for_function(HAS_INK)


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["chromium", "firefox"])
async def test_late_join_reconnect_and_undo_after_checkpoint(engine):
    async with async_playwright() as playwright:
        browser_type = getattr(playwright, engine)
        launch_kwargs = {"headless": True}
        if engine == "chromium":
            launch_kwargs["args"] = ["--mute-audio"]
        else:
            launch_kwargs["firefox_user_prefs"] = {"media.volume_scale": "0.0"}
        browser = await browser_type.launch(**launch_kwargs)
        host_context = await browser.new_context(viewport={"width": 1280, "height": 720})
        guest_context = await browser.new_context(viewport={"width": 1280, "height": 720})
        await host_context.add_init_script(CANVAS_CAPS)
        await guest_context.add_init_script(CANVAS_CAPS)
        host_page = await host_context.new_page()
        guest_page = await guest_context.new_page()
        host_page.set_default_timeout(20000)
        guest_page.set_default_timeout(20000)
        late_context = None
        try:
            code = await _create_waiting_room(host_page, "CheckHost")
            await _join_by_code(guest_page, code, "CheckGuest")
            drawer_page, guesser_page = await _start_drawing_round(host_page, guest_page)

            await drawer_page.locator('.toolbar-tools [aria-label^="Fill"]').click()
            # Two fills hit the lowered 400-work window; the third forces compact.
            await _fill_with_color(drawer_page, guesser_page, "#000000")
            await _fill_with_color(drawer_page, guesser_page, "#ed1c24")
            await _fill_with_color(drawer_page, guesser_page, "#3f48cc")
            drawer_hash = await _stable_hash(drawer_page)
            await _wait_for_hash(guesser_page, drawer_hash)

            late_context = await browser.new_context(viewport={"width": 1280, "height": 720})
            await late_context.add_init_script(CANVAS_CAPS)
            late_page = await late_context.new_page()
            late_page.set_default_timeout(20000)
            await late_page.goto(BASE_URL)
            await late_page.fill('input[placeholder="Your name"]', "LateJoiner")
            await late_page.fill('input[placeholder="ABC123"]', code)
            await late_page.click('button:has-text("Join by code")')
            await late_page.wait_for_selector("canvas.drawing-canvas")
            await late_page.wait_for_function(HAS_INK)
            await _wait_for_hash(late_page, drawer_hash)

            await guesser_page.reload()
            await guesser_page.wait_for_selector("canvas.drawing-canvas")
            await guesser_page.wait_for_function(HAS_INK)
            await _wait_for_hash(guesser_page, drawer_hash)

            await drawer_page.locator("button.undo-button").click()
            undone_hash = await _stable_hash(drawer_page)
            assert undone_hash != drawer_hash
            await _wait_for_hash(guesser_page, undone_hash)
            await _wait_for_hash(late_page, undone_hash)
            assert await drawer_page.evaluate(HAS_INK)
        finally:
            if late_context is not None:
                await late_context.close()
            await host_context.close()
            await guest_context.close()
            await browser.close()
