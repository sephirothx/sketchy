import asyncio

import pytest
from playwright.async_api import Page, async_playwright
from tests.e2e.lobby_helpers import use_guest_name


BASE_URL = "http://localhost:8000"


async def choose_word(pages: list[Page]) -> tuple[Page, Page, str]:
    for _ in range(120):
        for page in pages:
            if await page.locator(".prompt-choices").count():
                drawer = page
                guesser = pages[1] if page is pages[0] else pages[0]
                choice = drawer.locator(".prompt-choices button").first
                word = (await choice.inner_text()).strip()
                await choice.click()
                await drawer.locator(".prompt-choices").wait_for(state="detached")
                await drawer.locator("canvas.drawing-canvas").wait_for()
                return drawer, guesser, word
        await asyncio.sleep(0.1)
    raise AssertionError("No drawer received word choices within 12 seconds")


@pytest.mark.asyncio
async def test_post_game_drawing_recap_includes_drawn_and_empty_turns():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host = await host_context.new_page()
        guest = await guest_context.new_page()

        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "RecapHost")
            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.locator('[data-testid="waiting-room"]').wait_for()

            code_text = await host.locator(".room-copy-button").inner_text()
            code = code_text.split("Code:")[1].strip()

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "RecapGuest")
            await guest.fill('input[placeholder="ABC123"]', code)
            await guest.click('button:has-text("Join by code")')
            await guest.locator('[data-testid="waiting-room"]').wait_for()

            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await host.locator(".room-settings-editor details").click()
            await host.locator("#custom-prompts").fill("apple\ntree")
            await host.get_by_label("Only use custom prompts").check()
            await host.get_by_role("button", name="Save settings").click()
            await host.get_by_role("button", name="Start game").click()

            pages = [host, guest]
            first_drawer, first_guesser, first_word = await choose_word(pages)
            canvas = first_drawer.locator("canvas.drawing-canvas")
            box = await canvas.bounding_box()
            assert box is not None
            await first_drawer.mouse.move(box["x"] + 100, box["y"] + 100)
            await first_drawer.mouse.down()
            await first_drawer.mouse.move(box["x"] + 220, box["y"] + 210)
            await first_drawer.mouse.up()

            await first_guesser.wait_for_function(
                """() => {
                  const canvas = document.querySelector('canvas.drawing-canvas');
                  const pixels = canvas.getContext('2d').getImageData(
                    0, 0, canvas.width, canvas.height
                  ).data;
                  for (let index = 0; index < pixels.length; index += 4) {
                    if (pixels[index] !== 255 || pixels[index + 1] !== 255
                        || pixels[index + 2] !== 255) return true;
                  }
                  return false;
                }"""
            )
            await first_guesser.fill(".chat-input input", first_word)
            await first_guesser.keyboard.press("Enter")

            second_drawer, second_guesser, second_word = await choose_word(pages)
            await second_guesser.fill(".chat-input input", second_word)
            await second_guesser.keyboard.press("Enter")

            view_drawings = host.get_by_role("button", name="View drawings", exact=True)
            await view_drawings.wait_for(timeout=12_000)
            continue_to_waiting = host.get_by_role(
                "button",
                name="Continue to waiting room · 10s",
                exact=True,
            )
            await continue_to_waiting.wait_for()
            await view_drawings.click()

            assert await host.get_by_text("1 of 2", exact=True).is_visible()
            assert await host.get_by_role("heading", name=first_word).is_visible()
            assert not await host.get_by_text(
                "No drawing was captured for this turn.",
                exact=True,
            ).is_visible()
            async with host.expect_download() as first_download_info:
                await host.get_by_role("button", name="Download drawing").click()
            first_download = await first_download_info.value
            assert first_word in first_download.suggested_filename

            await host.get_by_role("button", name="Next").click()
            assert await host.get_by_text("2 of 2", exact=True).is_visible()
            assert await host.get_by_role("heading", name=second_word).is_visible()
            empty_notice = host.get_by_text(
                "No drawing was captured for this turn.",
                exact=True,
            )
            await empty_notice.wait_for()
            assert await empty_notice.is_visible()
            async with host.expect_download() as second_download_info:
                await host.get_by_role("button", name="Download drawing").click()
            second_download = await second_download_info.value
            assert second_word in second_download.suggested_filename

            await host.get_by_role("button", name="Previous").click()
            assert await host.get_by_text("1 of 2", exact=True).is_visible()
            await host.get_by_role("button", name="Close").click()
            await host.locator('[data-testid="waiting-room"]').wait_for()
            assert not await host.get_by_text("Previous game", exact=True).is_visible()
            assert await host.get_by_text("Final standings", exact=True).is_visible()
            assert await host.locator(".room-players-panel .player-role-placement").count() == 2
            assert await host.locator(".room-players-panel .player-score").count() == 2
            assert await host.get_by_role(
                "button",
                name="View drawings",
                exact=True,
            ).is_visible()
            assert not await host.get_by_role(
                "button",
                name="Save last drawing",
            ).is_visible()
            assert not await host.get_by_role(
                "button",
                name="Back to lobby",
            ).is_visible()

            # A non-host viewing the previous recap when the host starts a
            # rematch must not reopen the gallery when that rematch ends.
            await guest.get_by_role(
                "button",
                name="View drawings",
                exact=True,
            ).click()
            await guest.get_by_text("Drawing recap", exact=True).wait_for()

            await host.get_by_role("button", name="Play again").click()
            await guest.get_by_text("Drawing recap", exact=True).wait_for(
                state="detached",
            )

            for _ in range(2):
                _, guesser, word = await choose_word(pages)
                await guesser.fill(".chat-input input", word)
                await guesser.keyboard.press("Enter")

            await guest.get_by_text("Game complete", exact=True).wait_for(
                timeout=12_000,
            )
            assert not await guest.get_by_text(
                "Drawing recap",
                exact=True,
            ).is_visible()
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()
