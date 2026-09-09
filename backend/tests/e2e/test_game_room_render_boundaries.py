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

            for page in pages:
                await page.evaluate(RESET_COUNTS)
            await drawer.locator(".prompt-choices button").first.click()
            for page in pages:
                await page.wait_for_selector("canvas.drawing-canvas")
            # A phase change reaches gameplay on every page, and the canvas on
            # the one page it means something to: the drawer's, whose pointer
            # input the turn has just enabled. A guesser's canvas is handed the
            # same props it already had, and drawing arrives through the
            # protocol rather than through a render.
            assert (await guesser.evaluate(READ_COUNTS)).get("gameplay", 0) > 0
            drawer_phase_counts = await drawer.evaluate(READ_COUNTS)
            assert drawer_phase_counts.get("gameplay", 0) > 0
            assert drawer_phase_counts.get("canvas", 0) > 0

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


async def test_a_timed_hint_reveal_stops_at_the_prompt_it_changes():
    """A revealed letter re-renders the prompt, not the canvas beneath it (R-ENG-16).

    `hint_revealed` hands every guesser a new masked prompt, which the gameplay
    region owns and must redraw. The canvas has no interest in it, and used to
    be redrawn anyway - once per reveal, two or three times a turn, for every
    guesser - because the overlay it was passed was rebuilt on every gameplay
    render and defeated its `memo`.
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context() for _ in range(2)]
        host, guest = [await context.new_page() for context in contexts]
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "HintEdgeHost")
            await host.get_by_role("button", name="Create room", exact=True).click()
            await host.get_by_role("button", name="Create room", exact=True).click()
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "HintEdgeGuest")
            await join_by_code(guest, code)
            await guest.wait_for_selector('[data-testid="waiting-room"]')

            # A thirteen-letter prompt earns five checkpoints, and the shortest
            # turn the room offers spreads them one every 2.5s - so the reveal
            # this test is about arrives in seconds rather than in half a
            # minute of default settings. Both are ordinary room settings; the
            # server's own timer is what fires, unbent (R-ENG-10).
            await open_room_settings(host)
            await host.get_by_role("spinbutton", name="Drawing time").fill("15")
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("extraordinary")
            await host.get_by_label("Only use custom prompts").check()
            await save_room_settings(host)

            await host.get_by_role("button", name="Start game", exact=True).click()
            for page in (host, guest):
                await page.wait_for_selector(".game-layout")
                if not await page.evaluate(
                    "Boolean(window.__SKETCHY_RENDER_DIAGNOSTICS__)"
                ):
                    pytest.skip("requires VITE_RENDER_DIAGNOSTICS=true")

            drawer = None
            for _ in range(50):
                for page in (host, guest):
                    if await page.locator(".prompt-choices").count():
                        drawer = page
                        break
                if drawer is not None:
                    break
                await host.wait_for_timeout(100)
            assert drawer is not None
            guesser = guest if drawer is host else host

            await drawer.locator(".prompt-choices button").first.click()
            await guesser.wait_for_selector("canvas.drawing-canvas")
            assert await guesser.locator(".masked-tile.is-revealed").count() == 0

            await guesser.evaluate(RESET_COUNTS)
            # Waited for by the letter itself, so the measurement window opens
            # and closes on the reveal rather than on a guess at when it lands.
            await guesser.locator(".masked-tile.is-revealed").first.wait_for()

            counts = await guesser.evaluate(READ_COUNTS)
            assert counts.get("gameplay", 0) > 0, f"the prompt was not redrawn: {counts}"
            assert counts.get("canvas", 0) == 0, f"canvas rendered: {counts}"
        finally:
            for context in contexts:
                await context.close()
            await browser.close()
