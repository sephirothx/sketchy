"""The browser's Back in a room (R-UX-15).

Back used to be the router's: it drew the page before the room and unmounted
the room without `leave_room`, so the seat stayed live for as long as the tab
did. Now a room keeps history entries of its own - a guard over the entry it
was entered on, and one per open sheet - so Back closes what is open, and
Back on the room itself is the room's Leave.

`page.go_back()` is the same `popstate` a phone's back gesture makes. Between
steps the tests wait for the room's own history to settle (the mark it keeps
in `history.state`), because a sheet closing takes its entry back with an
asynchronous `history.go`, and a Back pressed mid-traversal would be measured
from an entry the page is about to leave.
"""
import random

from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import (
    join_by_code,
    open_player_settings,
    room_code,
    use_guest_name,
)


BASE_URL = "http://localhost:8000"

ALERT = '[role="alertdialog"]'


async def room_history_at(page, depth: int) -> None:
    """Wait until the current entry is the room's own at `depth`: 0 the guard,
    1 the first open sheet."""
    await page.wait_for_function(
        "(depth) => window.history.state?.sketchyRoomEntry?.depth === depth", arg=depth
    )


def seat(page, name: str):
    """A player's row in the room's roster, whichever stage the room is at."""
    return page.locator(".player-list .player-name .colored-player-name", has_text=name)


async def test_back_in_the_waiting_room_leaves_at_once_and_gives_up_the_seat():
    """No confirmation in the waiting room, the same as the Leave row - and the
    seat goes, which is the whole point: before this the host stayed in the
    guest's roster after pressing Back."""
    tag = random.randint(1000, 9999)
    host_name, guest_name = f"BackHost{tag}", f"BackGuest{tag}"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host = await host_context.new_page()
        guest = await guest_context.new_page()
        host.set_default_timeout(10000)
        guest.set_default_timeout(10000)

        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, host_name)
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector(".create-room-page")
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host)
            await room_history_at(host, 0)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, guest_name)
            await join_by_code(guest, code)
            await guest.wait_for_selector('[data-testid="waiting-room"]')
            await expect(seat(guest, host_name)).to_be_visible()
            await expect(seat(host, guest_name)).to_be_visible()

            # The guest leaves by Back, then goes Forward onto the room's old
            # entry and joins again from the invite screen there. That seat is
            # a new one on an entry the old seat marked, and the entry below it
            # is the lobby now: Back has to be Leave for it too, not a walk out
            # to the lobby with the seat still held.
            await guest.go_back()
            await guest.wait_for_url(f"{BASE_URL}/")
            await expect(seat(host, guest_name)).to_have_count(0)
            await guest.go_forward()
            await guest.wait_for_url(f"{BASE_URL}/room/{code}")
            await guest.get_by_role("button", name="Join", exact=True).click()
            await guest.wait_for_selector('[data-testid="waiting-room"]')
            await expect(seat(host, guest_name)).to_be_visible()
            await room_history_at(guest, 0)
            await guest.go_back()
            await guest.wait_for_url(f"{BASE_URL}/")
            await expect(guest.locator('[data-testid="room-header"]')).to_have_count(0)
            await expect(seat(host, guest_name)).to_have_count(0)

            # The host, the same way: Back leaves the waiting room at once.
            await guest.goto(f"{BASE_URL}/room/{code}")
            await guest.get_by_role("button", name="Join", exact=True).click()
            await guest.wait_for_selector('[data-testid="waiting-room"]')
            await expect(seat(guest, host_name)).to_be_visible()

            await host.go_back()
            await host.wait_for_url(f"{BASE_URL}/")
            await expect(host.locator('[data-testid="room-header"]')).to_have_count(0)
            await expect(host.locator(ALERT)).to_have_count(0)
            await expect(seat(guest, host_name)).to_have_count(0)

            # The lobby took the place of the room's entry, so Back from it goes
            # where the host came from - the create form - not into the room.
            await host.go_back()
            await host.wait_for_url(f"{BASE_URL}/create")
            await host.wait_for_selector(".create-room-page")
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()


async def test_back_during_a_game_closes_sheets_then_asks_before_leaving():
    """On a phone, where Back is a gesture: the Room menu's sheet closes, the
    Settings overlay (opened from the identity chip) closes, and only then is
    Back the Leave -
    which asks during a game, and is answered "stay" by Back again."""
    tag = random.randint(1000, 9999)
    host_name, phone_name = f"GameHost{tag}", f"PhoneBack{tag}"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        phone_context = await browser.new_context(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
        )
        host = await host_context.new_page()
        phone = await phone_context.new_page()
        host.set_default_timeout(10000)
        phone.set_default_timeout(10000)

        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, host_name)
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector(".create-room-page")
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host)

            await phone.goto(BASE_URL)
            await use_guest_name(phone, phone_name)
            await join_by_code(phone, code)
            await phone.wait_for_selector('[data-testid="waiting-room"]')
            room_url = phone.url

            await host.wait_for_selector(".waiting-start-button:not([disabled])")
            await host.click(".waiting-start-button")
            await host.wait_for_selector(".game-layout")
            await phone.wait_for_selector(".game-layout")
            await expect(seat(host, phone_name)).to_be_visible()
            await room_history_at(phone, 0)

            # A sheet: Back closes it and nothing else.
            await phone.get_by_test_id("open-room-menu").click()
            sheet = phone.get_by_test_id("room-menu-sheet")
            await sheet.wait_for()
            await room_history_at(phone, 1)
            await phone.go_back()
            await expect(sheet).to_have_count(0)
            await room_history_at(phone, 0)
            await expect(phone.locator(ALERT)).to_have_count(0)
            assert phone.url == room_url

            # Settings, opened from the identity chip's menu (the Room menu has
            # no Settings row): an overlay route of its own, which Back closes
            # without asking anything.
            await open_player_settings(phone)
            overlay = phone.locator(".settings-overlay")
            await overlay.wait_for()
            await phone.go_back()
            await expect(overlay).to_have_count(0)
            await room_history_at(phone, 0)
            await expect(phone.locator(ALERT)).to_have_count(0)
            assert phone.url == room_url

            # Nothing open: Back is Leave, and during a game Leave asks.
            await phone.go_back()
            dialog = phone.locator(ALERT)
            await expect(dialog).to_be_visible()
            await expect(dialog).to_contain_text("Leave")
            await room_history_at(phone, 1)
            assert phone.url == room_url

            # Back again is "stay": the dialog goes, the game is still there.
            await phone.go_back()
            await expect(dialog).to_have_count(0)
            await room_history_at(phone, 0)
            await expect(phone.locator(".game-layout")).to_be_visible()
            await expect(seat(host, phone_name)).to_be_visible()

            # And confirmed, it leaves - seat and all.
            await phone.go_back()
            await expect(dialog).to_be_visible()
            await dialog.locator('button:has-text("Leave game")').click()
            await phone.wait_for_url(f"{BASE_URL}/")
            await expect(seat(host, phone_name)).to_have_count(0)

            # No room entry is left behind the lobby to walk back into.
            await phone.go_back()
            await phone.wait_for_url(f"{BASE_URL}/")
            await expect(phone.locator('[data-testid="room-header"]')).to_have_count(0)
            await expect(phone.locator("#invite-name")).to_have_count(0)
        finally:
            await host_context.close()
            await phone_context.close()
            await browser.close()
