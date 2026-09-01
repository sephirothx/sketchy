"""The lobby's online list, over a real socket.

Deliberately asserts on *this test's own players* rather than on counts: the
suite runs its workers against one server, so every other test's browser is
online at the same time and any exact total would be a coin flip.
"""
import re

import pytest
from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import use_guest_name

BASE_URL = "http://localhost:8000"

# The broadcast is a fixed one-second tick, so every assertion here is about
# a state that arrives shortly rather than immediately.
SETTLE_MS = 8000


def row_for(page, name: str):
    return page.locator(
        f'[data-testid="online-players-list"] li:has(.online-player-name:text-is("{name}"))'
    )


@pytest.mark.asyncio
async def test_the_lobby_shows_who_else_is_online_and_what_they_are_doing():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        watcher_context = await browser.new_context()
        subject_context = await browser.new_context()
        watcher = await watcher_context.new_page()
        subject = await subject_context.new_page()

        try:
            await watcher.goto(BASE_URL)
            await use_guest_name(watcher, "PresenceWatcher")
            await subject.goto(BASE_URL)
            await use_guest_name(subject, "PresenceSubject")

            # The other player turns up in the list without a reload, and
            # without anything having to be opened to see them.
            await expect(row_for(watcher, "PresenceSubject")).to_be_visible(
                timeout=SETTLE_MS
            )
            await expect(
                row_for(watcher, "PresenceSubject").locator(".online-player-status")
            ).to_have_text("In the lobby", timeout=SETTLE_MS)

            # Taking a seat flips the status, and nothing about the room they
            # took it in appears anywhere in the list.
            await subject.click('button:has-text("Create room")')
            await subject.click('button:has-text("Create room")')
            await subject.wait_for_selector(".room-copy-button")
            await expect(
                row_for(watcher, "PresenceSubject").locator(".online-player-status")
            ).to_have_text("In a game", timeout=SETTLE_MS)

            # Closing the tab takes them out of the list: presence follows the
            # socket, not the seat, so this does not wait out the reconnect
            # grace their seat is still inside.
            await subject_context.close()
            await expect(row_for(watcher, "PresenceSubject")).to_have_count(
                0, timeout=SETTLE_MS
            )
        finally:
            await watcher_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_the_viewer_can_find_themselves_in_the_list():
    """Marked in place rather than moved to the top, so the order is one order."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "PresenceSelf")
            mine = row_for(page, "PresenceSelf")
            await expect(mine).to_be_visible(timeout=SETTLE_MS)
            await expect(mine).to_have_class(re.compile(r"\bis-me\b"))
            # A guest, so grey italics rather than an account colour (R-ACCT-05).
            await expect(mine.locator(".online-player-name")).to_have_class(
                re.compile(r"\bis-guest\b")
            )
        finally:
            await context.close()
            await browser.close()
