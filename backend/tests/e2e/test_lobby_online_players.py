"""The lobby's online list, over a real socket.

Deliberately asserts on *this test's own players* rather than on counts: the
suite runs its workers against one server, so every other test's browser is
online at the same time and any exact total would be a coin flip.
"""
import re

import pytest
from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import open_new_room, use_guest_name

BASE_URL = "http://localhost:8000"

# The broadcast is a fixed one-second tick, so every assertion here is about
# a state that arrives shortly rather than immediately.
SETTLE_MS = 8000


def row_for(page, name: str):
    return page.locator(
        f'[data-testid="online-players-list"] li:has(.online-player-name:text-is("{name}"))'
    )


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
            await open_new_room(subject)
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


@pytest.mark.parametrize("registered", [False, True], ids=["guest", "registered"])
async def test_one_wide_name_online_does_not_push_a_phone_lobby_sideways(registered):
    """#1271: at 720px and below the lobby's people column was a bare `1fr`,
    whose minimum is its content's, so one player online with a wide name
    widened every phone viewer's lobby - by 114px at 320px. A registered
    player's row, whose name is the button that opens its menu, also ran its
    name over the row's status and past the panel."""
    import random
    import string

    from tests.e2e.lobby_helpers import register_account

    # Sixteen letters, the most a name may have, nearly all of them the widest;
    # starting with A so the 100-row list never cuts it off.
    wide = "A" + "W" * 11 + "".join(random.choice(string.ascii_uppercase) for _ in range(4))
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        owner = await browser.new_context()
        viewer_context = await browser.new_context(
            viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True
        )
        try:
            online = await owner.new_page()
            if registered:
                await online.goto(BASE_URL)
                await register_account(online, wide)
            else:
                await use_guest_name(online, wide)
                await online.goto(BASE_URL)
            viewer = await viewer_context.new_page()
            await use_guest_name(viewer, f"Narrow{random.randint(1000, 9999)}")
            await viewer.goto(BASE_URL)
            name = viewer.locator(".online-player-name", has_text=wide).first
            await name.wait_for()
            for width in (320, 375, 390):
                await viewer.set_viewport_size({"width": width, "height": 812})
                await viewer.wait_for_timeout(200)
                assert await viewer.evaluate(
                    "() => document.documentElement.scrollWidth === document.documentElement.clientWidth"
                ), width
                # The name gives way instead: cut with an ellipsis, inside its panel.
                assert await name.evaluate(
                    "(el) => el.scrollWidth > el.clientWidth"
                    " && el.getBoundingClientRect().right <= el.closest('.panel').getBoundingClientRect().right"
                ), width
        finally:
            await owner.close()
            await viewer_context.close()
            await browser.close()
