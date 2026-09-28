"""A phone keeps the final standings after game over.

The game-over card continues by itself after ten seconds. A desktop then keeps
a "Final standings" panel beside the waiting room, but a phone hides that panel
there - its roster grid says who is here - and the grid showed faces without
scores, so a phone player who looked away had lost the result (#1270). The
roster carries each seat's place and final score now, until the next game.
"""
import asyncio
from uuid import uuid4

import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import (
    join_by_code,
    open_new_room,
    open_room_settings,
    open_settings_section,
    room_code,
    save_room_settings,
    use_guest_name,
)

BASE_URL = "http://localhost:8000"


async def _choose(pages):
    for _ in range(200):
        for page in pages:
            if await page.locator(".prompt-choices").count():
                choice = page.locator(".prompt-choices button").first
                prompt = (await choice.inner_text()).strip()
                await choice.click()
                await page.locator(".prompt-choices").wait_for(state="detached")
                return page, prompt
        await asyncio.sleep(0.1)
    raise AssertionError("no drawer was offered prompt choices")


@pytest.mark.parametrize(
    "size", [{"width": 390, "height": 844}, {"width": 844, "height": 390}], ids=["portrait", "landscape"]
)
async def test_a_phone_keeps_the_final_standings_after_game_over(size):
    phone = {"viewport": size, "is_mobile": True, "has_touch": True}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context(**phone) for _ in range(2)]
        host, guest = [await context.new_page() for context in contexts]
        try:
            tag = uuid4().hex[:5]
            await host.goto(BASE_URL)
            await use_guest_name(host, f"StandHost{tag}")
            await open_new_room(host)
            code = await room_code(host)
            await guest.goto(BASE_URL)
            await use_guest_name(guest, f"StandGuest{tag}")
            await join_by_code(guest, code)
            await guest.wait_for_selector('[data-testid="waiting-room"]')
            await open_room_settings(host)
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("apple\ntree")
            await host.get_by_label("Only use custom prompts").check()
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await save_room_settings(host)
            await host.get_by_role("button", name="Start game").click()

            pages = [host, guest]
            for _ in range(2):
                drawer, prompt = await _choose(pages)
                for page in pages:
                    if page is not drawer:
                        await page.fill(".chat-input input", prompt)
                        await page.keyboard.press("Enter")
            for page in pages:
                await page.locator('[data-testid="game-end-overlay"]').wait_for(timeout=20_000)
            await guest.get_by_role("button", name="Continue").click()
            await guest.locator('[data-testid="waiting-room"]').wait_for()

            roster = guest.locator(".waiting-roster")
            standings = roster.get_by_test_id("roster-standing")
            await standings.first.wait_for()
            assert await standings.count() == 2
            texts = [await standings.nth(index).inner_text() for index in range(2)]
            # Places first, in order, each with its score.
            assert all("·" in text for text in texts), texts
            assert texts[0].startswith("1"), texts
            assert await roster.get_by_text("Final standings").count() == 1

            # Still there after a while, and gone once the rematch starts.
            await guest.wait_for_timeout(1000)
            assert await standings.count() == 2
            await host.get_by_role("button", name="Continue").click()
            await host.get_by_role("button", name="Rematch").click()
            await guest.locator(".prompt-choices, canvas.drawing-canvas").first.wait_for(timeout=15_000)
            assert await guest.get_by_test_id("roster-standing").count() == 0
        finally:
            for context in contexts:
                await context.close()
            await browser.close()
