import pytest
from playwright.async_api import async_playwright

from tests.e2e.guest_nickname import submit_guest_nickname


BASE_URL = "http://localhost:8000"

RESET_COUNTS = """
() => {
  const diagnostics = window.__SKETCHY_RENDER_DIAGNOSTICS__;
  if (!diagnostics) throw new Error("Render diagnostics are not enabled");
  diagnostics.counts = {};
}
"""

READ_COUNTS = """
() => ({ ...window.__SKETCHY_RENDER_DIAGNOSTICS__?.counts })
"""

ISOLATED_REGIONS = ("activeGameRoom", "roomShell", "gameplay", "canvas")


async def assert_regions_unchanged(page, regions=ISOLATED_REGIONS):
    counts = await page.evaluate(READ_COUNTS)
    for region in regions:
        assert counts.get(region, 0) == 0, f"{region} rendered: {counts}"
    return counts


@pytest.mark.asyncio
async def test_chat_score_and_drawing_updates_stop_at_their_render_boundaries():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context() for _ in range(3)]
        pages = [await context.new_page() for context in contexts]
        host, guest_one, guest_two = pages
        try:
            await host.goto(BASE_URL)
            await host.get_by_role("button", name="Create room", exact=True).click()
            await submit_guest_nickname(host, "BoundaryHost")
            await host.get_by_role("button", name="Create room", exact=True).click()
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = (await host.inner_text(".room-copy-button")).split("Code:")[1].strip()

            for page, nickname in (
                (guest_one, "BoundaryGuestOne"),
                (guest_two, "BoundaryGuestTwo"),
            ):
                await page.goto(BASE_URL)
                await page.fill('input[placeholder="ABC123"]', code)
                await page.get_by_role("button", name="Join by code", exact=True).click()
                await submit_guest_nickname(page, nickname)
                await page.wait_for_selector('[data-testid="waiting-room"]')

            await host.get_by_role("button", name="Start game", exact=True).click()
            for page in pages:
                await page.wait_for_selector(".game-layout")
                if not await page.evaluate(
                    "Boolean(window.__SKETCHY_RENDER_DIAGNOSTICS__)"
                ):
                    pytest.skip("requires VITE_RENDER_DIAGNOSTICS=true")

            drawer = None
            for _ in range(50):
                for page in pages:
                    if await page.locator(".word-choices").count():
                        drawer = page
                        break
                if drawer is not None:
                    break
                await host.wait_for_timeout(100)
            assert drawer is not None
            guessers = [page for page in pages if page is not drawer]
            observer = guessers[0]

            await observer.evaluate(RESET_COUNTS)
            await drawer.locator(".word-choices button").first.click()
            for page in pages:
                await page.wait_for_selector("canvas.drawing-canvas")
            phase_counts = await observer.evaluate(READ_COUNTS)
            assert phase_counts.get("gameplay", 0) > 0
            assert phase_counts.get("canvas", 0) > 0

            sender = guessers[0]
            await sender.fill(".chat-input input", "ordinary boundary message")
            await drawer.evaluate(RESET_COUNTS)
            await sender.keyboard.press("Enter")
            await drawer.wait_for_function(
                "window.__SKETCHY_RENDER_DIAGNOSTICS__?.counts.chat > 0"
            )
            chat_counts = await assert_regions_unchanged(drawer)
            assert chat_counts.get("chat", 0) > 0
            assert chat_counts.get("players", 0) == 0

            await observer.evaluate(RESET_COUNTS)
            canvas = drawer.locator("canvas.drawing-canvas")
            box = await canvas.bounding_box()
            assert box is not None
            await drawer.mouse.move(box["x"] + 80, box["y"] + 80)
            await drawer.mouse.down()
            await drawer.mouse.move(box["x"] + 160, box["y"] + 160)
            await drawer.mouse.up()
            await observer.wait_for_timeout(200)
            drawing_counts = await assert_regions_unchanged(observer)
            assert drawing_counts.get("players", 0) == 0

            word = (await drawer.locator(".word-reveal").inner_text()).strip()
            scorer = guessers[0]
            await scorer.fill(".chat-input input", word)
            await drawer.evaluate(RESET_COUNTS)
            await scorer.keyboard.press("Enter")
            await drawer.locator(".chat-message.correct", has_text=word).wait_for()
            score_counts = await assert_regions_unchanged(drawer)
            assert score_counts.get("players", 0) > 0
            assert score_counts.get("chat", 0) > 0
        finally:
            for context in contexts:
                await context.close()
            await browser.close()
