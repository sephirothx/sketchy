"""Buying a hint costs nothing up front; the debt is settled by the guess."""
import asyncio

import pytest
from playwright.async_api import Page, async_playwright
from tests.e2e.lobby_helpers import close_room_settings, open_room_settings, room_code, use_guest_name


BASE_URL = "http://localhost:8000"


async def choose_prompt(pages: list[Page]) -> tuple[Page, Page, str]:
    for _ in range(120):
        for page in pages:
            if await page.locator(".prompt-choices").count():
                drawer = page
                guesser = pages[1] if page is pages[0] else pages[0]
                choice = drawer.locator(".prompt-choices button").first
                prompt = (await choice.inner_text()).strip()
                await choice.click()
                await drawer.locator(".prompt-choices").wait_for(state="detached")
                await drawer.locator("canvas.drawing-canvas").wait_for()
                return drawer, guesser, prompt
        await asyncio.sleep(0.1)
    raise AssertionError("No drawer received prompt choices within 12 seconds")


@pytest.mark.asyncio
async def test_a_bought_hint_is_only_paid_for_by_a_correct_guess():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host = await host_context.new_page()
        guest = await guest_context.new_page()

        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "HintHost")
            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.locator('[data-testid="waiting-room"]').wait_for()

            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "HintGuest")
            await guest.fill('input[placeholder="ABC123"]', code)
            await guest.click('button:has-text("Join by code")')
            await guest.locator('[data-testid="waiting-room"]').wait_for()

            await open_room_settings(host)
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await host.locator(".room-settings-editor details").click()
            await host.locator('[aria-label="Hints"] button:has-text("Buy letters")').click()
            await host.locator("#custom-prompts").fill("elephant")
            await host.get_by_label("Only use custom prompts").check()
            await guest.get_by_text("Custom prompts only (1)").wait_for()
            await guest.get_by_text("Buy letters", exact=True).wait_for()
            await close_room_settings(host)
            await host.get_by_role("button", name="Start game").click()

            drawer, guesser, prompt = await choose_prompt([host, guest])
            assert prompt == "elephant"

            my_score = guesser.locator(".player-row.is-self .player-score")
            assert (await my_score.inner_text()).strip() == "0"

            # Buying is charged to the turn, not to the balance: the score must
            # not move, and the running debt is shown instead.
            await guesser.locator(".hint-blank").first.click()
            spend_line = guesser.locator(".hint-spend-total")
            await spend_line.wait_for()
            assert (await spend_line.inner_text()).strip() == "Total: 12"
            assert (await my_score.inner_text()).strip() == "0"

            await guesser.fill(".chat-input input", prompt)
            await guesser.keyboard.press("Enter")

            personal = guesser.locator(".turn-results-personal")
            await personal.wait_for(timeout=12_000)
            breakdown = (await personal.inner_text()).strip()
            assert "-12 hints" in breakdown, breakdown

            # "Your turn: +300 -12 hints = 288 points · now #1"
            gross = int(breakdown.split("+")[1].split()[0])
            net = int(breakdown.split("=")[1].split()[0])
            assert net == gross - 12
            await guesser.wait_for_function(
                "expected => document.querySelector('.player-row.is-self .player-score')"
                "?.textContent.trim() === expected",
                arg=str(net),
            )
        finally:
            await browser.close()
