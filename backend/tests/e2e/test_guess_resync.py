"""A correct guess survives a reload and a tab coming back into view (#870).

`correct_guess` and `you_guessed_correctly` are one-shot, and every return to a
visible tab resyncs through `sync_game`. Before #870 that resync cleared every
seat's pips and, after a reload, re-opened a correct guesser's input while the
masked prompt showed the answer.
"""
import asyncio

from playwright.async_api import Page, async_playwright
from tests.e2e.lobby_helpers import (
    join_by_code,
    open_room_settings,
    open_settings_section,
    room_code,
    save_room_settings,
    use_guest_name,
)


BASE_URL = "http://localhost:8000"


async def choose_prompt(pages: list[Page]) -> tuple[Page, list[Page], str]:
    for _ in range(120):
        for page in pages:
            if await page.locator(".prompt-choices").count():
                choice = page.locator(".prompt-choices button").first
                prompt = (await choice.inner_text()).strip()
                await choice.click()
                await page.locator(".prompt-choices").wait_for(state="detached")
                return page, [other for other in pages if other is not page], prompt
        await asyncio.sleep(0.1)
    raise AssertionError("No drawer received prompt choices within 12 seconds")


async def assert_guess_restored(guesser: Page, watcher: Page) -> None:
    await guesser.get_by_test_id("guess-verdict-hit").wait_for()
    assert await guesser.locator(".chat-input.has-guessed").count() == 1
    # The desktop player list; phones show the same state as pips.
    for page in (guesser, watcher):
        await page.locator(".player-row.has-guessed").wait_for()
        assert await page.locator(".player-row.has-guessed").count() == 1


def count_syncs(page: Page) -> list[int]:
    """How many `sync_game` frames this page has received, kept current."""
    seen = [0]

    def on_frame(payload) -> None:
        if isinstance(payload, str) and '"sync_game"' in payload:
            seen[0] += 1

    page.on("websocket", lambda ws: ws.on("framereceived", on_frame))
    return seen


async def show_tab_again(page: Page, syncs: list[int]) -> None:
    """What alt-tabbing back does: the page reports visible and says so, and
    the room answers with a fresh `sync_game`."""
    before = syncs[0]
    await page.evaluate(
        """() => {
          Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
          document.dispatchEvent(new Event('visibilitychange'));
        }"""
    )
    for _ in range(100):
        if syncs[0] > before:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("Showing the tab again did not resync the game")


async def test_a_correct_guess_survives_a_reload_and_a_soft_resync():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context() for _ in range(3)]
        host, second, third = [await context.new_page() for context in contexts]
        syncs = {page: count_syncs(page) for page in (host, second, third)}

        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "ResyncHost")
            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.locator('[data-testid="waiting-room"]').wait_for()
            code = await room_code(host)
            for page, name in ((second, "ResyncTwo"), (third, "ResyncThree")):
                await page.goto(BASE_URL)
                await use_guest_name(page, name)
                await join_by_code(page, code)
                await page.locator('[data-testid="waiting-room"]').wait_for()

            await open_room_settings(host)
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("elephant")
            await host.get_by_label("Only use custom prompts").check()
            await save_room_settings(host)
            await host.get_by_role("button", name="Start game").click()

            _drawer, (guesser, watcher), prompt = await choose_prompt([host, second, third])
            await guesser.fill(".chat-input input", prompt)
            await guesser.keyboard.press("Enter")
            await assert_guess_restored(guesser, watcher)

            # Soft: both seats resync on the same socket.
            await show_tab_again(guesser, syncs[guesser])
            await show_tab_again(watcher, syncs[watcher])
            await assert_guess_restored(guesser, watcher)

            # Hard: a fresh page has no memory of either one-shot event.
            await guesser.reload()
            await guesser.locator("canvas.drawing-canvas").wait_for()
            await assert_guess_restored(guesser, watcher)
            breakdown = guesser.locator(".guess-verdict-hit-points")
            assert (await breakdown.inner_text()).strip().startswith("+")
        finally:
            await browser.close()
