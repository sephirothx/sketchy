"""A finished game reaches the profile page: stats, history, and round detail."""
import asyncio

import pytest
from playwright.async_api import Page, async_playwright
from tests.e2e.lobby_helpers import use_guest_name

BASE_URL = "http://localhost:8000"


async def choose_word(pages: list[Page]) -> tuple[Page, Page, str]:
    """Wait for whichever page is drawing, pick its first word, and return both."""
    for _ in range(120):
        for page in pages:
            if await page.locator(".word-choices").count():
                drawer = page
                guesser = pages[1] if page is pages[0] else pages[0]
                choice = drawer.locator(".word-choices button").first
                word = (await choice.inner_text()).strip()
                await choice.click()
                await drawer.locator(".word-choices").wait_for(state="detached")
                return drawer, guesser, word
        await asyncio.sleep(0.1)
    raise AssertionError("No drawer received word choices within 12 seconds")


@pytest.mark.asyncio
async def test_finished_game_shows_up_on_the_profile_page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host = await host_context.new_page()
        guest = await guest_context.new_page()

        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "ProfileHost")
            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.locator('[data-testid="waiting-room"]').wait_for()

            code_text = await host.locator(".room-copy-button").inner_text()
            code = code_text.split("Code:")[1].strip()

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "ProfileGuest")
            await guest.fill('input[placeholder="ABC123"]', code)
            await guest.click('button:has-text("Join by code")')
            await guest.locator('[data-testid="waiting-room"]').wait_for()

            # One round of two players is two turns: each drives one, and each
            # guesses the other's word, so both sides of the stats are covered.
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await host.locator(".room-settings-editor details").click()
            await host.locator("#custom-words").fill("apple\ntree")
            await host.get_by_label("Only use custom words").check()
            await host.get_by_role("button", name="Save settings").click()
            await host.get_by_role("button", name="Start game").click()

            pages = [host, guest]
            _, first_guesser, first_word = await choose_word(pages)
            await first_guesser.fill(".chat-input input", first_word)
            await first_guesser.keyboard.press("Enter")

            _, second_guesser, second_word = await choose_word(pages)
            await second_guesser.fill(".chat-input input", second_word)
            await second_guesser.keyboard.press("Enter")

            # The recap button is the signal that the game has ended, and the
            # history write happens just before it is emitted.
            await host.get_by_role(
                "button", name="View drawings", exact=True
            ).wait_for(timeout=12_000)

            # A separate tab in the same context: same session cookie, same
            # account, but outside the room - which is where the profile link
            # lives, since navigating out of a live game gives up the seat.
            lobby = await host_context.new_page()
            await lobby.goto(BASE_URL)
            await lobby.locator(".identity-chip").click()
            await lobby.get_by_role("menuitem", name="My profile").click()

            await lobby.wait_for_url("**/profile")
            await lobby.locator(".profile-stat").first.wait_for()

            games_played = lobby.locator(".profile-stat").filter(
                has_text="Games played"
            )
            assert (
                await games_played.locator(".profile-stat-value").inner_text()
            ) == "1"
            drawings_made = lobby.locator(".profile-stat").filter(
                has_text="Drawings made"
            )
            assert (
                await drawings_made.locator(".profile-stat-value").inner_text()
            ) == "1"

            # The history lists the finished game, and opening it fetches the
            # rounds - which only a participant is allowed to read.
            game_row = lobby.locator(".profile-game").first
            await game_row.wait_for()
            await game_row.locator(".profile-game-header").click()
            await lobby.locator(".profile-rounds").wait_for()

            words = await lobby.locator(".profile-round-word").all_inner_texts()
            assert sorted(words) == sorted([first_word, second_word])
            assert await lobby.get_by_text("ProfileGuest").first.is_visible()

            # A guest's own profile offers the claim funnel.
            assert await lobby.get_by_role(
                "heading", name="Claim your account"
            ).is_visible()
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()
