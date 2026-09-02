"""The public room list arriving on the socket, over a real one.

What #462 replaced was a four-second poll, so the property worth proving end to
end is the one the poll gave for free and a feed has to earn: a lobby nobody
touches keeps up with rooms opening and closing. Both halves matter and only
one of them is obvious — a card that appears is a `mark_dirty` somebody
remembered, while a card that *goes* is the diff noticing an absence.

Asserts on this test's own room. The suite's workers share one server, so
every other test's rooms are in the same list.
"""
import pytest
from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import use_guest_name

BASE_URL = "http://localhost:8000"

# The broadcast is a fixed one-second tick, so every assertion here is about a
# state that arrives shortly rather than immediately.
SETTLE_MS = 8000


@pytest.mark.asyncio
async def test_a_room_opening_and_closing_reaches_a_lobby_nobody_touched():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        watcher_context = await browser.new_context()
        host = await host_context.new_page()
        watcher = await watcher_context.new_page()
        try:
            # The watcher is here first, and never reloads or clicks again.
            # Anything it learns after this point was pushed to it.
            await watcher.goto(BASE_URL)
            await use_guest_name(watcher, "FeedWatcher")
            await watcher.wait_for_selector(".lobby-rooms-panel")

            await host.goto(BASE_URL)
            await use_guest_name(host, "FeedHost")
            await host.click('button:has-text("Create room")')
            await host.fill(
                'input[placeholder="Leave blank for a random name!"]', "Feed room"
            )
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector('[data-testid="waiting-room"]')

            card = watcher.locator(
                '[data-testid="public-room-card"]', has_text="Feed room"
            )
            await expect(card).to_be_visible(timeout=SETTLE_MS)

            # A room with nobody in it is gone, and the absence has to be
            # noticed by the diff - there is no event that says "room closed".
            # The host *leaves* rather than closing the browser: a dropped
            # socket keeps its seat for the R-CONN-01 grace, so the room would
            # still be there, correctly, for another half minute.
            await host.click(".game-header-leave-button")
            await host.wait_for_selector(".lobby-rooms-panel")
            await expect(card).to_have_count(0, timeout=SETTLE_MS)
        finally:
            await watcher_context.close()
            await browser.close()
