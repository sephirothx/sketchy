"""Quick play (#589): one press from the lobby into a room.

Quick play only takes rooms in the player's prompt language, and the suite
shares one server. So each test here runs in a language no other test uses -
Dutch, Portuguese - and what it presses is decided by what it opened itself,
not by whichever English room another test left waiting.
"""

import random

from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import room_code, use_guest_name


BASE_URL = "http://localhost:8000"


async def open_public_room(page, name: str) -> tuple[str, str]:
    """A host in a public room, waiting for players. Returns its code and name.

    The lobby's cards do not print the code (it is the Room menu's, #580), so
    the name is what finds this room in the list.
    """
    await page.goto(BASE_URL)
    await use_guest_name(page, name)
    await page.click(".lobby-rooms-actions .btn-primary")
    await page.wait_for_selector(".create-room-page")
    await page.click(".create-room-submit")
    await page.wait_for_selector('[data-testid="waiting-room"]')
    return await room_code(page), (await page.locator(".waiting-room-head h1").inner_text()).strip()


async def test_quick_play_takes_the_room_that_is_waiting():
    tag = random.randint(1000, 9999)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context(viewport={"width": 1280, "height": 900}, locale="nl-NL")
        guest_context = await browser.new_context(viewport={"width": 1280, "height": 900}, locale="nl-NL")
        host = await host_context.new_page()
        guest = await guest_context.new_page()
        try:
            code, room_name = await open_public_room(host, f"QpHost{tag}")

            await guest.goto(BASE_URL)
            await use_guest_name(guest, f"QpGuest{tag}")
            # The room has to have reached the lobby's list before the press.
            await guest.wait_for_selector(f'[data-testid="public-room-card"]:has-text("{room_name}")')
            await guest.click('[data-testid="quick-play"]')

            # In the host's room, not in one of its own.
            await guest.wait_for_selector('[data-testid="waiting-room"]')
            assert await room_code(guest) == code
            await host.wait_for_selector(f'[data-testid="room-players-region"]:has-text("QpGuest{tag}")')
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()


async def test_quick_play_opens_a_public_room_when_none_is_waiting():
    tag = random.randint(1000, 9999)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 1280, "height": 900}, locale="pt-PT")
        watcher_context = await browser.new_context(viewport={"width": 1280, "height": 900}, locale="pt-PT")
        page = await context.new_page()
        watcher = await watcher_context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, f"QpAlone{tag}")
            await page.wait_for_selector(".lobby-rooms-panel")
            await page.click('[data-testid="quick-play"]')

            await page.wait_for_selector('[data-testid="waiting-room"]')
            room_name = (await page.locator(".waiting-room-head h1").inner_text()).strip()
            # Public and on the standard rules, so the next visitor's Quick
            # play finds it: it is in the lobby's list, for somebody else.
            await watcher.goto(BASE_URL)
            await use_guest_name(watcher, f"QpWatch{tag}")
            await watcher.wait_for_selector(f'[data-testid="public-room-card"]:has-text("{room_name}")')
            # Its own room, on the standard rules, in the language being read.
            assert await page.locator(".waiting-rules-edit").count() == 1, "not the host of it"
            facts = await page.locator('[data-testid="waiting-facts"]').inner_text()
            assert "90s" in facts and "3" in facts, facts
            assert "portugu" in facts.lower(), facts
        finally:
            await context.close()
            await watcher_context.close()
            await browser.close()


async def test_one_press_names_a_first_time_visitor_and_plays():
    """The first press used to stop after saving the name: naming reconnects the
    socket, the reconnect marks the room list stale, and Quick play gave up on
    the stale list instead of waiting for the new one. And while it was in
    flight, Join by code and Create room stayed live beside it."""
    tag = random.randint(1000, 9999)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        # Italian: nobody else's, so the room this opens is this test's alone.
        context = await browser.new_context(viewport={"width": 1280, "height": 900}, locale="it-IT")
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await page.wait_for_selector(".first-run")
            await page.wait_for_selector('[data-testid="quick-play"]:not([disabled])')
            # A name typed on the tag, never stuck on: Quick play is the press.
            await page.fill(".first-run-guest-row input", f"QpFirst{tag}")
            # Pressed and read in one go, a frame apart: naming and the
            # reconnect after it keep the press in flight for far longer, and
            # while it is, no other way into a room may start (a second entry
            # would release this one's seat and race it for the route).
            in_flight = await page.evaluate(
                """async () => {
                  document.querySelector('[data-testid="quick-play"]').click();
                  await new Promise((resolve) => requestAnimationFrame(() => resolve()));
                  return [...document.querySelectorAll('.lobby-rooms-actions button')]
                    .map((button) => button.disabled);
                }"""
            )
            assert len(in_flight) == 3 and all(in_flight), in_flight

            await page.wait_for_selector('[data-testid="waiting-room"]', timeout=15000)
            await page.wait_for_selector(f'[data-testid="room-players-region"]:has-text("QpFirst{tag}")')
        finally:
            await context.close()
            await browser.close()

