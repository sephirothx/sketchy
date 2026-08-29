"""Highlights live on their own screen, reachable from both sides of game over."""
import asyncio

import pytest
from playwright.async_api import Page, async_playwright
from tests.e2e.lobby_helpers import close_room_settings, open_room_settings, room_code, use_guest_name

BASE_URL = "http://localhost:8000"


async def choose_prompt(pages: list[Page]):
    for _ in range(400):
        for page in pages:
            if await page.locator(".prompt-choices").count():
                drawer = page
                choice = drawer.locator(".prompt-choices button").first
                prompt = (await choice.inner_text()).strip()
                await choice.click()
                await drawer.locator(".prompt-choices").wait_for(state="detached")
                await drawer.locator("canvas.drawing-canvas").wait_for()
                return drawer, prompt
        await asyncio.sleep(0.1)
    raise AssertionError("no drawer was offered prompt choices")


@pytest.mark.asyncio
async def test_highlights_open_from_game_over_and_close_when_a_rematch_starts():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host = await host_context.new_page()
        guest = await guest_context.new_page()

        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "HighHost")
            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.locator('[data-testid="waiting-room"]').wait_for()

            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "HighGuest")
            await guest.fill('input[placeholder="ABC123"]', code)
            await guest.click('button:has-text("Join by code")')
            await guest.locator('[data-testid="waiting-room"]').wait_for()

            await open_room_settings(host)
            await host.locator(".room-settings-editor details").click()
            await host.locator("#custom-prompts").fill("apple\ntree")
            await host.get_by_label("Only use custom prompts").check()
            # Settings save themselves; the guest seeing them is the signal.
            await guest.get_by_text("Custom prompts only (2)").wait_for()
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await close_room_settings(host)
            await host.get_by_role("button", name="Start game").click()

            # Both players guess every turn, so the game has something to say.
            pages = [host, guest]
            for _ in range(2):
                drawer, prompt = await choose_prompt(pages)
                for page in pages:
                    if page is drawer:
                        continue
                    await page.fill(".chat-input input", prompt)
                    await page.keyboard.press("Enter")

            overlay = host.locator('[data-testid="game-end-overlay"]')
            await overlay.wait_for(timeout=15_000)

            # The end screen offers the way in without carrying the list itself.
            assert await overlay.locator(".game-highlights-list").count() == 0
            await host.get_by_role("button", name="View highlights").click()

            panel = host.locator(".game-highlights")
            await panel.wait_for()
            assert await panel.get_by_text("Fastest guess").count() == 1

            # Closing lands in the waiting room, where they are still reachable.
            await host.get_by_role("button", name="Back").click()
            await host.locator('[data-testid="waiting-room"]').wait_for()
            await host.get_by_role("button", name="View highlights").click()
            await panel.wait_for()
            assert await panel.get_by_text("Fastest guess").count() == 1
            await host.get_by_role("button", name="Back").click()
            await host.locator('[data-testid="waiting-room"]').wait_for()

            # A player reading the highlights when a rematch begins must be
            # handed the new game, not left on last game's screen. Only the
            # non-host can get here: the Rematch button is on the waiting room,
            # behind the panel.
            guest_panel = guest.locator(".game-highlights")
            await guest.get_by_role("button", name="View highlights").click()
            await guest_panel.wait_for()

            await host.get_by_role("button", name="Rematch").click()
            await guest_panel.wait_for(state="detached")
            # And the new game is what replaced it, not an empty room.
            await guest.locator(
                "canvas.drawing-canvas, .prompt-choices",
            ).first.wait_for(timeout=15_000)
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()
