"""A finished game reaches the profile page: stats, history, and round detail."""
import asyncio

import pytest
from playwright.async_api import Page, async_playwright
from tests.e2e.lobby_helpers import close_room_settings, open_room_settings, room_code, use_guest_name

BASE_URL = "http://localhost:8000"


async def choose_prompt(pages: list[Page]) -> tuple[Page, Page, str]:
    """Wait for whichever page is drawing, pick its first prompt, and return both."""
    for _ in range(120):
        for page in pages:
            if await page.locator(".prompt-choices").count():
                drawer = page
                guesser = pages[1] if page is pages[0] else pages[0]
                choice = drawer.locator(".prompt-choices button").first
                prompt = (await choice.inner_text()).strip()
                await choice.click()
                await drawer.locator(".prompt-choices").wait_for(state="detached")
                return drawer, guesser, prompt
        await asyncio.sleep(0.1)
    raise AssertionError("No drawer received prompt choices within 12 seconds")


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

            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "ProfileGuest")
            await guest.fill('input[placeholder="ABC123"]', code)
            await guest.click('button:has-text("Join by code")')
            await guest.locator('[data-testid="waiting-room"]').wait_for()

            # One round of two players is two turns: each drives one, and each
            # guesses the other's prompt, so both sides of the stats are covered.
            await open_room_settings(host)
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await host.locator(".room-settings-editor details").click()
            await host.locator("#custom-prompts").fill("apple\ntree")
            await host.get_by_label("Only use custom prompts").check()
            await guest.get_by_text("Custom prompts only (2)").wait_for()
            await close_room_settings(host)
            await host.get_by_role("button", name="Start game").click()

            pages = [host, guest]
            _, first_guesser, first_prompt = await choose_prompt(pages)
            await first_guesser.fill(".chat-input input", first_prompt)
            await first_guesser.keyboard.press("Enter")

            _, second_guesser, second_prompt = await choose_prompt(pages)
            await second_guesser.fill(".chat-input input", second_prompt)
            await second_guesser.keyboard.press("Enter")

            # The recap button is the signal that the game has ended, and the
            # history write happens just before it is emitted.
            await host.locator('[data-testid="game-end-overlay"]').get_by_role(
                "button", name="Drawings", exact=True
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
            await lobby.locator(".profile-turns").wait_for()

            prompts = await lobby.locator(".profile-turn-prompt").all_inner_texts()
            assert sorted(prompts) == sorted([first_prompt, second_prompt])
            assert await lobby.get_by_text("ProfileGuest").first.is_visible()

            # A guest's own profile offers the claim funnel.
            assert await lobby.get_by_role(
                "heading", name="Claim your account"
            ).is_visible()

            # The drawings survived the game. Opening one from history has to
            # reach the rest of the game's turns too, which is the whole point
            # of a gallery rather than a single-drawing view.
            await lobby.locator(".profile-drawing-button").first.click()
            await lobby.locator(".drawing-recap").wait_for()
            await lobby.get_by_text("1 of 2", exact=True).wait_for()

            next_button = lobby.get_by_role("button", name="Next", exact=True)
            previous_button = lobby.get_by_role(
                "button", name="Previous", exact=True
            )
            assert await next_button.is_enabled(), "a second turn is reachable"
            assert not await previous_button.is_enabled(), "nothing precedes the first"

            await next_button.click()
            await lobby.get_by_text("2 of 2", exact=True).wait_for()
            assert not await next_button.is_enabled(), "nothing follows the last"
            assert await previous_button.is_enabled()

            await previous_button.click()
            await lobby.get_by_text("1 of 2", exact=True).wait_for()
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()
