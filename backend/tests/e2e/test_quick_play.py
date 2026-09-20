"""Quick play (#589): one press from the lobby into a room.

Quick play only takes rooms in the player's prompt language, and the suite
shares one server. So each test here runs in a language no other test uses -
Dutch, Portuguese - and what it presses is decided by what it opened itself,
not by whichever English room another test left waiting.
"""

import random

from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import room_code, use_guest_name
from tests.e2e.test_friends import SETTLE_MS, make_friends, sign_up, unique

# Holds every outgoing room entry - `join_room`, `create_room`,
# `join_friend_room` - for a second and a half before it reaches the socket,
# so a test can look at the page while an entry is still in flight. Nothing
# else is touched: presence, the room list and invitations flow as ever.
HOLD_ROOM_ENTRIES = """
(() => {
  const send = WebSocket.prototype.send;
  WebSocket.prototype.send = function (data) {
    if (typeof data === "string" && /\\["(join_room|create_room|join_friend_room|quick_play)"/.test(data)) {
      setTimeout(() => send.call(this, data), 1500);
      return;
    }
    return send.call(this, data);
  };
})();
"""


# Drops this page's `watch_lobby`, so no room list ever arrives. Quick play is
# the server's decision since #931 and must not wait for one.
BLOCK_THE_LOBBY_FEED = """
(() => {
  const send = WebSocket.prototype.send;
  WebSocket.prototype.send = function (data) {
    if (typeof data === "string" && /\\["watch_lobby"/.test(data)) return;
    return send.call(this, data);
  };
})();
"""


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



async def test_a_friend_s_invitation_waits_while_quick_play_is_in_flight():
    """The notice is mounted above every page, so the lobby's own lock could
    not see it: accepting an invitation while Quick play was still walking its
    rooms raced it for the one seat a socket holds, and either could release
    the other's."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host, guest = await host_context.new_page(), await guest_context.new_page()
        host_name, guest_name = unique("QpHost"), unique("QpPal")
        try:
            await sign_up(host, host_name)
            await sign_up(guest, guest_name)
            await make_friends(host, guest, host_name, guest_name)

            await host.click(".lobby-rooms-actions .btn-primary")
            await host.click(".create-room-submit")
            await host.wait_for_selector('[data-testid="waiting-room"]')
            invite = host.locator(
                f'[data-testid="invite-friends"] li:has-text("{guest_name}")'
            ).get_by_role("button", name="Invite")
            await expect(invite).to_be_visible(timeout=SETTLE_MS)
            await invite.click()
            notice = guest.locator('[data-testid="friend-invite"]')
            await expect(notice).to_be_visible(timeout=SETTLE_MS)

            # From here the guest's room entries are held on the wire.
            await guest.evaluate(HOLD_ROOM_ENTRIES)
            await guest.click('[data-testid="quick-play"]')
            await expect(notice.get_by_role("button", name="Join")).to_be_disabled()
            await expect(guest.locator(".lobby-rooms-actions .btn-primary")).to_be_disabled()

            await guest.wait_for_selector('[data-testid="waiting-room"]', timeout=SETTLE_MS)
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()


async def test_an_invite_link_waits_while_another_way_in_is_in_flight():
    """The invite page took the lock only after its own screen had moved to
    "joining", and a busy lock came back as a refusal the room never gave -
    "Could not join this room" - while its buttons stayed live."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        friend_context = await browser.new_context()
        guest_context = await browser.new_context()
        other_context = await browser.new_context()
        friend, guest = await friend_context.new_page(), await guest_context.new_page()
        other = await other_context.new_page()
        friend_name, guest_name = unique("QlHost"), unique("QlPal")
        try:
            await sign_up(friend, friend_name)
            await sign_up(guest, guest_name)
            await make_friends(friend, guest, friend_name, guest_name)

            # Somebody else's room, whose invite link the guest is looking at.
            other_code, _ = await open_public_room(other, unique("QlOther"))
            await guest.goto(f"{BASE_URL}/room/{other_code}")
            await guest.wait_for_selector(".invite-primary-button:not([disabled])")

            # The friend's invitation arrives on top of that page.
            await friend.click(".lobby-rooms-actions .btn-primary")
            await friend.click(".create-room-submit")
            await friend.wait_for_selector('[data-testid="waiting-room"]')
            invite = friend.locator(
                f'[data-testid="invite-friends"] li:has-text("{guest_name}")'
            ).get_by_role("button", name="Invite")
            await expect(invite).to_be_visible(timeout=SETTLE_MS)
            await invite.click()
            notice = guest.locator('[data-testid="friend-invite"]')
            await expect(notice).to_be_visible(timeout=SETTLE_MS)

            await guest.evaluate(HOLD_ROOM_ENTRIES)
            await notice.get_by_role("button", name="Join").click()
            # While it is in flight the invite page waits: nothing to press, and
            # no refusal the room never gave.
            await expect(guest.locator(".invite-primary-button")).to_be_disabled()
            await expect(guest.locator(".invite-secondary-button")).to_be_disabled()
            assert await guest.locator("#invite-entry-error").count() == 0

            await guest.wait_for_selector('[data-testid="waiting-room"]', timeout=SETTLE_MS)
            assert await guest.locator("#invite-entry-error").count() == 0
        finally:
            await friend_context.close()
            await guest_context.close()
            await other_context.close()
            await browser.close()


async def test_quick_play_needs_no_room_list():
    """#931: the press used to be decided from the lobby's list, so it waited
    for one - up to ten seconds after naming a first-time visitor, whose
    naming reconnects the socket. The server decides it now."""
    tag = random.randint(1000, 9999)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context(viewport={"width": 1280, "height": 900}, locale="de-DE")
        blind_context = await browser.new_context(viewport={"width": 1280, "height": 900}, locale="de-DE")
        host = await host_context.new_page()
        blind = await blind_context.new_page()
        try:
            code, _ = await open_public_room(host, f"QpDeHost{tag}")

            await blind.add_init_script(BLOCK_THE_LOBBY_FEED)
            await blind.goto(BASE_URL)
            await use_guest_name(blind, f"QpBlind{tag}")
            await blind.wait_for_selector(".lobby-rooms-panel")
            # No list: the panel is still loading, and the button is live.
            assert await blind.locator('[data-testid="public-room-card"]').count() == 0
            await expect(blind.locator('[data-testid="quick-play"]')).to_be_enabled()
            await blind.click('[data-testid="quick-play"]')

            # And it lands in the room the server knows is waiting.
            await blind.wait_for_selector('[data-testid="waiting-room"]')
            assert await room_code(blind) == code
        finally:
            await host_context.close()
            await blind_context.close()
            await browser.close()
