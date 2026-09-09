import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import (
    join_by_code,
    open_room_settings,
    open_settings_section,
    room_code,
    save_room_settings,
    use_guest_name,
)


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
            await use_guest_name(host, "BoundaryHost")
            await host.get_by_role("button", name="Create room", exact=True).click()
            await host.get_by_role("button", name="Create room", exact=True).click()
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host)

            for page, nickname in (
                (guest_one, "BoundaryGuestOne"),
                (guest_two, "BoundaryGuestTwo"),
            ):
                await page.goto(BASE_URL)
                await use_guest_name(page, nickname)
                await join_by_code(page, code)
                await page.wait_for_selector('[data-testid="waiting-room"]')

            # Timed hints off, so nothing but this test touches the gameplay
            # region once drawing starts. A checkpoint reveal changes every
            # guesser's masked prompt, which re-renders gameplay and the canvas
            # under it - both regions asserted below to be unchanged. Left on,
            # the room fires two or three of those across a 90s turn, and
            # whether one lands inside a measurement window is decided by how
            # wide the window is, which on a loaded runner is not a constant.
            # That is what made this test fail on CI and pass on re-run (#724).
            await open_room_settings(host)
            await open_settings_section(host, "Scoring and hints")
            await host.locator('[aria-label="Hints"] button:has-text("No hints")').click()
            await save_room_settings(host)

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
                    if await page.locator(".prompt-choices").count():
                        drawer = page
                        break
                if drawer is not None:
                    break
                await host.wait_for_timeout(100)
            assert drawer is not None
            guessers = [page for page in pages if page is not drawer]
            guesser = guessers[0]

            await guesser.evaluate(RESET_COUNTS)
            await drawer.locator(".prompt-choices button").first.click()
            for page in pages:
                await page.wait_for_selector("canvas.drawing-canvas")
            phase_counts = await guesser.evaluate(READ_COUNTS)
            assert phase_counts.get("gameplay", 0) > 0
            assert phase_counts.get("canvas", 0) > 0

            sender = guessers[0]
            await sender.fill(".chat-input input", "ordinary boundary message")
            await drawer.evaluate(RESET_COUNTS)
            await sender.keyboard.press("Enter")
            # A function, not a bare expression: Playwright evaluates the
            # latter as a string, which the page's CSP refuses (#467).
            await drawer.wait_for_function(
                "() => window.__SKETCHY_RENDER_DIAGNOSTICS__?.counts.chat > 0"
            )
            chat_counts = await assert_regions_unchanged(drawer)
            assert chat_counts.get("chat", 0) > 0
            assert chat_counts.get("players", 0) == 0

            await guesser.evaluate(RESET_COUNTS)
            canvas = drawer.locator("canvas.drawing-canvas")
            box = await canvas.bounding_box()
            assert box is not None
            await drawer.mouse.move(box["x"] + 80, box["y"] + 80)
            await drawer.mouse.down()
            await drawer.mouse.move(box["x"] + 160, box["y"] + 160)
            await drawer.mouse.up()
            await guesser.wait_for_timeout(200)
            drawing_counts = await assert_regions_unchanged(guesser)
            assert drawing_counts.get("players", 0) == 0

            prompt = (await drawer.locator(".prompt-reveal").inner_text()).strip()
            scorer = guessers[0]
            await scorer.fill(".chat-input input", prompt)
            await drawer.evaluate(RESET_COUNTS)
            await scorer.keyboard.press("Enter")
            await drawer.locator(".chat-message.correct", has_text=prompt).wait_for()
            score_counts = await assert_regions_unchanged(drawer)
            assert score_counts.get("players", 0) > 0
            assert score_counts.get("chat", 0) > 0
        finally:
            for context in contexts:
                await context.close()
            await browser.close()
