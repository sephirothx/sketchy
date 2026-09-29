"""A spectator who comes back as a player mid-drawing sits that drawing out
(#1317), and its field says so rather than taking guesses that go nowhere."""
import asyncio
from uuid import uuid4

from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import (
    join_by_code,
    leave_room,
    open_new_room,
    room_code,
    use_guest_name,
)

BASE_URL = "http://localhost:8000"


async def test_a_spectator_back_as_a_player_mid_drawing_is_told_it_guesses_next_turn():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context() for _ in range(3)]
        host, player, watcher = [await context.new_page() for context in contexts]
        try:
            tag = uuid4().hex[:5]
            await host.goto(BASE_URL)
            await use_guest_name(host, f"Host{tag}")
            await open_new_room(host)
            code = await room_code(host)
            await player.goto(BASE_URL)
            await use_guest_name(player, f"Play{tag}")
            await join_by_code(player, code)
            await player.locator('[data-testid="waiting-room"]').wait_for()
            await watcher.goto(BASE_URL)
            await use_guest_name(watcher, f"Watch{tag}")
            await join_by_code(watcher, code, spectate=True)
            await watcher.locator('[data-testid="waiting-room"]').wait_for()

            await host.get_by_role("button", name="Start game").click()
            drawer = None
            for _ in range(100):
                for page in (host, player):
                    if await page.locator(".prompt-choices button").count():
                        drawer = page
                if drawer:
                    break
                await asyncio.sleep(0.1)
            await drawer.locator(".prompt-choices button").first.click()
            await watcher.locator(".prompt-masked, .prompt-reveal").first.wait_for()

            # Out, and back in as a player while the same drawing runs.
            await leave_room(watcher)
            confirm = watcher.locator('[role="alertdialog"]')
            if await confirm.count():
                await confirm.get_by_role("button", name="Leave", exact=False).last.click()
            await watcher.get_by_role("button", name="Join by code").first.wait_for(timeout=10_000)
            await join_by_code(watcher, code)
            field = watcher.locator(".chat-input input")
            await field.wait_for()
            await expect(field).to_have_attribute("placeholder", "Chat for now: you guess from the next turn")
        finally:
            for context in contexts:
                await context.close()
            await browser.close()
