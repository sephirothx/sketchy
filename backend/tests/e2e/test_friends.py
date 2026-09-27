"""Friends, end to end: asking, answering, and getting into a private room.

Two accounts in two browser contexts, over a real socket and a real database.
The part worth proving here is the part unit tests cannot: that a friendship
made in the lobby is what lets somebody through a door they can never name.
"""
import re
import uuid

from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import join_by_code, leave_room, register_account, use_guest_name

BASE_URL = "http://localhost:8000"

# Presence is a fixed one-second tick, and a friendship is a round trip, so
# everything here is a state that arrives shortly rather than immediately.
SETTLE_MS = 10000


def unique(prefix: str) -> str:
    """A name no other worker in the suite is using."""
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def row_for(page, name: str):
    return page.locator(
        f'[data-testid="online-players-list"] li:has(.online-player-name:text-is("{name}"))'
    )


async def sign_up(page, username: str) -> None:
    await page.goto(BASE_URL)
    await use_guest_name(page, username)
    await register_account(page, username)


async def open_friends(page) -> None:
    """Reach the friends surface the way a player does, from the account menu."""
    await page.locator(".account-menu > button").first.click()
    await page.get_by_role("menuitem", name="Friends").click()
    await page.wait_for_selector('[data-testid="friends"]')


async def open_row_menu(page, name: str):
    """Open what a lobby row offers about the person on it.

    The row's name is its trigger, the way a seat's is in a room. A guest's
    row has no menu at all, and neither does your own.
    """
    row = row_for(page, name)
    await expect(row).to_be_visible(timeout=SETTLE_MS)
    await row.locator(".online-player-trigger").click()
    menu = page.locator('[data-testid="online-player-menu"]')
    await expect(menu).to_be_visible(timeout=SETTLE_MS)
    return menu


async def open_profile_from_lobby(page, name: str) -> None:
    menu = await open_row_menu(page, name)
    await menu.get_by_role("menuitem", name="Open player profile").click()
    await page.wait_for_selector(".profile-identity")


async def ask_from_profile(asker, target_name: str) -> None:
    """Send a request from the person's profile, reached from their row.

    The row offers the ask directly too (R-FRIEND-11); this goes the long way
    on purpose, because the profile is where a request can also be withdrawn
    and the tests below read that state.
    """
    await open_profile_from_lobby(asker, target_name)
    await asker.get_by_role("button", name="Add friend").click()
    await expect(asker.locator(".friend-button-status")).to_have_text(
        "Request sent", timeout=SETTLE_MS
    )
    await asker.goto(BASE_URL)


async def make_friends(asker, accepter, asker_name: str, accepter_name: str) -> None:
    """Ask from a profile, and answer it where requests are answered."""
    await ask_from_profile(asker, accepter_name)

    await open_friends(accepter)
    incoming = accepter.locator('[data-testid="friends-incoming"]').get_by_role(
        "button", name="Accept"
    )
    await expect(incoming).to_be_visible(timeout=SETTLE_MS)
    await incoming.click()
    await accepter.get_by_role("button", name="Close friends").click()
    # Both sides settle on a friendship: the lobby row offers a way into their
    # game, which only a friend gets.
    await expect(row_for(asker, accepter_name)).to_be_visible(timeout=SETTLE_MS)


async def test_friends_are_made_in_the_lobby_and_open_a_private_room():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        ada_context = await browser.new_context()
        bob_context = await browser.new_context()
        ada, bob = await ada_context.new_page(), await bob_context.new_page()
        ada_name, bob_name = unique("Ada"), unique("Bob")

        try:
            await sign_up(ada, ada_name)
            await sign_up(bob, bob_name)
            await make_friends(ada, bob, ada_name, bob_name)

            # Bob opens a private room. Nothing about it is discoverable: it is
            # not in the public list, and presence says only "In a game".
            await bob.click('button:has-text("Create room")')
            await bob.click('button:has-text("Private")')
            await bob.click('button:has-text("Create room")')
            await bob.wait_for_selector('[data-testid="room-header"]')
            code = await bob.locator('[data-testid="room-header"]').get_attribute(
                "data-room-code"
            )

            bobs_row = row_for(ada, bob_name)
            await expect(bobs_row).to_be_visible(timeout=SETTLE_MS)
            join = bobs_row.get_by_role("button", name="Join")
            await expect(join).to_be_visible(timeout=SETTLE_MS)
            # The code Ada is about to be let in with never reached her.
            assert code and code not in await ada.content()

            await join.click()
            await ada.wait_for_selector('[data-testid="waiting-room"]')
            assert f"/room/{code}" in ada.url
            # Two players in a room Ada could not have named.
            await expect(bob.locator(".player-row")).to_have_count(
                2, timeout=SETTLE_MS
            )
        finally:
            await ada_context.close()
            await bob_context.close()
            await browser.close()


async def test_an_invitation_reaches_a_friend_and_seats_them():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host, guest = await host_context.new_page(), await guest_context.new_page()
        host_name, guest_name = unique("Host"), unique("Pal")

        try:
            await sign_up(host, host_name)
            await sign_up(guest, guest_name)
            await make_friends(host, guest, host_name, guest_name)

            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector('[data-testid="room-header"]')

            # The invite card lists friends who are in the lobby.
            invite = host.locator(
                f'[data-testid="invite-friends"] li:has-text("{guest_name}")'
            ).get_by_role("button", name="Invite")
            await expect(invite).to_be_visible(timeout=SETTLE_MS)
            await invite.click()

            notice = guest.locator('[data-testid="friend-invite"]')
            await expect(notice).to_be_visible(timeout=SETTLE_MS)
            await expect(notice).to_contain_text(host_name)
            await notice.get_by_role("button", name="Join").click()

            await guest.wait_for_selector('[data-testid="waiting-room"]')
            await expect(host.locator(".player-row")).to_have_count(
                2, timeout=SETTLE_MS
            )
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()


async def test_in_a_phone_room_an_invitation_is_a_chip_in_the_room_bar():
    """#1176: the card sat on the phone room's chat feed and hid its latest
    lines. In a room the invitation is a chip in the bar instead, whose
    popover answers it with Join or Not now.

    The rooms here are waiting rooms, not games: the bar is one component for
    both, so what holds in one holds in the other, and a game would cost a
    second guest for nothing."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
        )
        host, guest = await host_context.new_page(), await guest_context.new_page()
        host_name, guest_name = unique("Host"), unique("Pal")
        card = guest.locator('[data-testid="friend-invite"]')
        chip = guest.locator(
            '[data-testid="room-header"] .room-notice-chip[data-notice="invite"]'
        )
        popover = guest.locator('.room-notice-popover[data-notice="invite"]')

        async def invite_guest() -> None:
            invite = host.locator(
                f'[data-testid="invite-friends"] li:has-text("{guest_name}")'
            ).get_by_role("button", name="Invite")
            await expect(invite).to_be_visible(timeout=SETTLE_MS)
            await invite.click()
            # In the lobby it is the card, as before.
            await expect(card).to_be_visible(timeout=SETTLE_MS)

        async def guest_opens_a_room() -> None:
            # The invitation outlives the lobby: in a room of the guest's own
            # it moves into the bar rather than floating over the room.
            await guest.click('button:has-text("Create room")')
            await guest.wait_for_selector(".create-room-page")
            await guest.click('button:has-text("Create room")')
            await guest.wait_for_selector('[data-testid="waiting-room"]')
            await expect(card).to_have_count(0)
            await expect(chip).to_be_visible()

        try:
            await sign_up(host, host_name)
            await sign_up(guest, guest_name)
            await make_friends(host, guest, host_name, guest_name)

            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector('[data-testid="waiting-room"]')
            await invite_guest()
            await guest_opens_a_room()

            # Named by the word it shows, then the sentence; said once from
            # outside the room, where a hidden bar cannot swallow it.
            await expect(chip).to_have_attribute(
                "aria-label", re.compile(rf"^Invitation: {host_name} ")
            )
            await expect(guest.get_by_test_id("friend-invite-announcer")).to_contain_text(
                host_name
            )
            box = await chip.bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390, box

            await chip.click()
            await expect(popover).to_contain_text(host_name)
            await popover.get_by_role("button", name="Not now").click()
            await expect(chip).to_have_count(0)
            await expect(card).to_have_count(0)

            # A second invitation, answered with Join from the chip. The host's
            # list marks the first as sent until it is drawn afresh.
            await leave_room(guest)
            await guest.wait_for_selector('[data-testid="quick-play"]')
            await host.reload()
            await host.wait_for_selector('[data-testid="waiting-room"]')
            await invite_guest()
            await guest_opens_a_room()
            await chip.click()
            await popover.get_by_role("button", name="Join").click()

            await expect(host.locator(".player-row")).to_have_count(
                2, timeout=SETTLE_MS
            )
            await expect(chip).to_have_count(0)
            # A waiting room is left at once, as its own Leave leaves it: no
            # question (#1198), and the guest is in the friend's room.
            await expect(guest.get_by_role("alertdialog")).to_have_count(0)
            host_code = await host.locator('[data-testid="room-header"]').get_attribute(
                "data-room-code"
            )
            await expect(guest.locator('[data-testid="room-header"]')).to_have_attribute(
                "data-room-code", host_code
            )
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()


async def test_joining_an_invitation_mid_game_asks_what_leave_asks():
    """#1198: Join on an invitation leaves the room the player is in, and in
    the middle of a game it skipped the question the room's own Leave asks.
    It asks the same one now, naming where the player is going: No keeps them
    in the game with the invitation still up, Yes leaves and joins."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        other_context = await browser.new_context()
        host = await host_context.new_page()
        guest = await guest_context.new_page()
        other = await other_context.new_page()
        host_name, guest_name, other_name = unique("Host"), unique("Pal"), unique("Other")
        chip = guest.locator(
            '[data-testid="room-header"] .room-notice-chip[data-notice="invite"]'
        )
        popover = guest.locator('.room-notice-popover[data-notice="invite"]')
        question = guest.get_by_role("alertdialog")

        try:
            await sign_up(host, host_name)
            await sign_up(guest, guest_name)
            await make_friends(host, guest, host_name, guest_name)

            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector('[data-testid="waiting-room"]')
            invite = host.locator(
                f'[data-testid="invite-friends"] li:has-text("{guest_name}")'
            ).get_by_role("button", name="Invite")
            await expect(invite).to_be_visible(timeout=SETTLE_MS)
            await invite.click()
            await expect(guest.locator('[data-testid="friend-invite"]')).to_be_visible(
                timeout=SETTLE_MS
            )

            # The invitee goes into a game of their own before answering.
            await guest.click('button:has-text("Create room")')
            await guest.wait_for_selector(".create-room-page")
            await guest.click('button:has-text("Create room")')
            await guest.wait_for_selector('[data-testid="waiting-room"]')
            code = await guest.locator('[data-testid="room-header"]').get_attribute(
                "data-room-code"
            )
            await other.goto(BASE_URL)
            await use_guest_name(other, other_name)
            await join_by_code(other, code)
            await other.wait_for_selector('[data-testid="waiting-room"]')
            await guest.get_by_role("button", name="Start game").click()
            await guest.wait_for_selector(".game-room-playing")

            await chip.click()
            await popover.get_by_role("button", name="Join").click()
            await expect(question).to_be_visible()
            await expect(question).to_contain_text(host_name)

            # No: still in the game, and the invitation is still there.
            await question.get_by_role("button", name="Cancel").click()
            await expect(question).to_have_count(0)
            await expect(guest.locator(".game-room-playing")).to_be_visible()
            await expect(chip).to_be_visible()
            await expect(host.locator(".player-row")).to_have_count(1)

            # Yes: out of the game, and into the friend's room.
            await chip.click()
            await popover.get_by_role("button", name="Join").click()
            await question.get_by_role("button", name="Leave and join").click()
            await expect(host.locator(".player-row")).to_have_count(
                2, timeout=SETTLE_MS
            )
            await guest.wait_for_selector('[data-testid="waiting-room"]')
            host_code = await host.locator('[data-testid="room-header"]').get_attribute(
                "data-room-code"
            )
            await expect(guest.locator('[data-testid="room-header"]')).to_have_attribute(
                "data-room-code", host_code
            )
            await expect(chip).to_have_count(0)

            # The game given up is gone from the history too (R-UX-15): Back
            # from the friend's room is that room's Leave, and lands on the
            # lobby rather than on the old room's code.
            await guest.go_back()
            await guest.wait_for_selector('[data-testid="quick-play"]')
            assert guest.url.rstrip("/") == BASE_URL, guest.url
            assert f"/room/{code}" not in guest.url, guest.url
        finally:
            await host_context.close()
            await guest_context.close()
            await other_context.close()
            await browser.close()


async def test_a_guest_is_not_offered_a_friendship_it_cannot_have():
    """A guest identity is a browser, not a person, and is purged after a month."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        guest_context = await browser.new_context()
        member_context = await browser.new_context()
        as_guest = await guest_context.new_page()
        as_member = await member_context.new_page()
        guest_name, member_name = unique("Wanderer"), unique("Member")

        try:
            await as_guest.goto(BASE_URL)
            await use_guest_name(as_guest, guest_name)
            await sign_up(as_member, member_name)

            # A guest has no profile worth opening, nothing to befriend and no
            # account to report, so their row offers no menu at all.
            guest_row = row_for(as_member, guest_name)
            await expect(guest_row).to_be_visible(timeout=SETTLE_MS)
            await expect(guest_row.locator(".online-player-trigger")).to_have_count(0)
            await expect(guest_row.locator(".online-player-status")).to_have_text(
                re.compile("In the lobby")
            )

            # And the guest reaches the member's profile, which offers them
            # nothing: a friendship needs an account on *both* sides.
            await open_profile_from_lobby(as_guest, member_name)
            await expect(
                as_guest.get_by_role("button", name="Add friend")
            ).to_have_count(0)
        finally:
            await guest_context.close()
            await member_context.close()
            await browser.close()


async def test_the_friends_surface_shows_a_request_from_somebody_offline():
    """The gap the surface exists to close (R-FRIEND-10).

    Everything the lobby offers is about who is online. A request from
    somebody who has since closed their tab, and a request you sent that you
    would like back, both live nowhere else - so this proves the surface holds
    them once the other browser is gone, and that cancelling a sent request
    works from there.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        asker_context = await browser.new_context()
        target_context = await browser.new_context()
        asker = await asker_context.new_page()
        target = await target_context.new_page()
        asker_name, target_name = unique("Asker"), unique("Target")

        try:
            await sign_up(asker, asker_name)
            await sign_up(target, target_name)

            # Settles before the target's browser stops mattering, so what
            # follows is about the surface rather than a race.
            await ask_from_profile(asker, target_name)

            # The target's own surface holds the request with the asker gone.
            await open_friends(target)
            incoming = target.locator('[data-testid="friends-incoming"]')
            await expect(incoming).to_contain_text(asker_name, timeout=SETTLE_MS)

            # And the asker can see and withdraw what they sent, which the
            # lobby only ever showed while the other person was online.
            await open_friends(asker)
            outgoing = asker.locator('[data-testid="friends-outgoing"]')
            await expect(outgoing).to_contain_text(target_name, timeout=SETTLE_MS)
            await outgoing.get_by_role("button", name="Cancel").click()
            await expect(asker.locator('[data-testid="friends-outgoing"]')).to_have_count(
                0, timeout=SETTLE_MS
            )

            # Cancelling deletes the row rather than leaving a refusal, so it
            # is gone from the other side too (R-FRIEND-05).
            await expect(
                target.locator('[data-testid="friends-incoming"]')
            ).to_have_count(0, timeout=SETTLE_MS)
        finally:
            await asker_context.close()
            await target_context.close()
            await browser.close()


async def test_the_friends_surface_draws_over_a_live_room():
    """Answering a request must not cost a seat (R-FRIEND-10, R-SET-06).

    The whole reason this is an overlay on a route rather than a page.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        name = unique("Seated")

        try:
            await sign_up(page, name)
            await page.click('button:has-text("Create room")')
            await page.click('button:has-text("Create room")')
            await page.wait_for_selector('[data-testid="waiting-room"]')
            room_url = page.url

            await open_friends(page)
            assert page.url.endswith("/friends")
            # The room is still mounted underneath, not unmounted and replaced.
            await expect(page.locator('[data-testid="waiting-room"]')).to_be_visible()

            await page.get_by_role("button", name="Close friends").click()
            await expect(page.locator('[data-testid="friends"]')).to_have_count(0)
            assert page.url == room_url
            await expect(page.locator('[data-testid="waiting-room"]')).to_be_visible()
        finally:
            await context.close()
            await browser.close()


async def test_the_online_panel_carries_no_friendship_state_at_all():
    """Who is online says who is around, and stops (R-FRIEND-11).

    Asking is on the profile every name links to; answering is on the friends
    surface. A row here comes and goes as people open and close tabs, which
    makes it the wrong home for either - an offer to ask was there one second
    and gone the next, and a request it reported could only be answered while
    its sender happened to still be standing there.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        asker_context = await browser.new_context()
        target_context = await browser.new_context()
        asker = await asker_context.new_page()
        target = await target_context.new_page()
        asker_name, target_name = unique("Asker"), unique("Target")

        try:
            await sign_up(asker, asker_name)
            await sign_up(target, target_name)

            panel = target.locator('[data-testid="online-players-list"]')
            await expect(row_for(target, asker_name)).to_be_visible(timeout=SETTLE_MS)

            await ask_from_profile(asker, target_name)

            # A request in flight changes nothing about either panel: no
            # answer offered on the recipient's, no "sent" on the sender's.
            await expect(
                target.locator('[data-testid="friend-request-badge"]')
            ).to_have_text("1", timeout=SETTLE_MS)
            await expect(panel.get_by_role("button", name="Accept")).to_have_count(0)
            await expect(panel.get_by_role("button", name="Decline")).to_have_count(0)
            await expect(panel).not_to_contain_text("Request sent")
            await expect(panel).not_to_contain_text("Wants to be friends")

            senders_panel = asker.locator('[data-testid="online-players-list"]')
            await expect(row_for(asker, target_name)).to_be_visible(timeout=SETTLE_MS)
            await expect(senders_panel).not_to_contain_text("Request sent")
            # The offer stands whether or not a request is outstanding: the row
            # must not reveal one by withdrawing it (R-FRIEND-11).
            sent_menu = await open_row_menu(asker, target_name)
            await expect(
                sent_menu.get_by_role("menuitem", name="Add as friend")
            ).to_be_visible()
        finally:
            await asker_context.close()
            await target_context.close()
            await browser.close()


async def test_a_profile_is_reachable_from_the_lobby_and_offers_a_friendship():
    """The other half of the gap: reaching one specific person (R-FRIEND-10).

    Before this, a friendship could only be offered by a lobby row or a seat
    in the same room - both of which need the other person to be there at that
    moment. A profile is linked from every game's participant list and from
    the lobby, and outlives both.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        ada_context = await browser.new_context()
        bob_context = await browser.new_context()
        ada, bob = await ada_context.new_page(), await bob_context.new_page()
        ada_name, bob_name = unique("Ada"), unique("Bob")

        try:
            await sign_up(ada, ada_name)
            await sign_up(bob, bob_name)

            # The row's menu is the way in. A guest's row has none, which the
            # existing guest test already pins from the other direction.
            await open_profile_from_lobby(ada, bob_name)
            assert "/profile/" in ada.url

            add = ada.get_by_role("button", name="Add friend")
            await expect(add).to_be_visible(timeout=SETTLE_MS)
            await add.click()
            # The profile settles into the state the request left behind.
            await expect(ada.locator(".friend-button-status")).to_have_text(
                "Request sent", timeout=SETTLE_MS
            )

            # And it arrived, which is what the surface on the other side is
            # for - Bob never had to be looking at the lobby.
            await open_friends(bob)
            await expect(
                bob.locator('[data-testid="friends-incoming"]')
            ).to_contain_text(ada_name, timeout=SETTLE_MS)
        finally:
            await ada_context.close()
            await bob_context.close()
            await browser.close()


async def test_your_own_profile_offers_you_no_friendship_with_yourself():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        name = unique("Solo")

        try:
            await sign_up(page, name)
            await page.goto(f"{BASE_URL}/profile")
            await page.wait_for_selector(".profile-identity")
            await expect(page.get_by_role("button", name="Add friend")).to_have_count(0)
        finally:
            await context.close()
            await browser.close()


async def test_a_profile_says_whether_you_are_already_friends():
    """A profile with no control on it is ambiguous.

    Blank reads the same whether these two are friends, whether the viewer is
    signed out, or whether the page has not finished loading - and a profile
    is the natural place to ask "are we friends?". The answer is the mark on
    the disc, which is the same shape the lobby uses.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        ada_context = await browser.new_context()
        bob_context = await browser.new_context()
        ada, bob = await ada_context.new_page(), await bob_context.new_page()
        ada_name, bob_name = unique("Ada"), unique("Bob")

        try:
            await sign_up(ada, ada_name)
            await sign_up(bob, bob_name)

            await open_profile_from_lobby(ada, bob_name)
            # Not friends yet: an offer, and no mark on the disc.
            await expect(ada.get_by_role("button", name="Add friend")).to_be_visible(
                timeout=SETTLE_MS
            )
            await expect(ada.locator(".profile-identity .avatar-friend")).to_have_count(0)

            await ada.goto(BASE_URL)
            await make_friends(ada, bob, ada_name, bob_name)

            await open_profile_from_lobby(ada, bob_name)
            # The disc says it, in the shape that says it everywhere else.
            await expect(
                ada.locator(".profile-identity .avatar-friend")
            ).to_have_count(1, timeout=SETTLE_MS)
            # Said, not offered: ending one is confirmed on the surface.
            await expect(ada.get_by_role("button", name="Remove")).to_have_count(0)
            await expect(ada.get_by_role("button", name="Add friend")).to_have_count(0)
        finally:
            await ada_context.close()
            await bob_context.close()


async def test_a_request_arriving_is_said_and_counted_from_inside_a_game():
    """Both halves of R-FRIEND-12, in the place they exist for.

    A request arriving used to be silent unless the recipient happened to be
    looking at the lobby's online panel. Here the recipient is in a room, and
    is told anyway - and the badge points at the surface that answers it.

    In a room it is a chip in the bar, not a toast: the toast stood on the
    phone's chat feed and the desktop drawer's palette (R-UX-07, #1197).
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        asker_context = await browser.new_context()
        target_context = await browser.new_context()
        asker = await asker_context.new_page()
        target = await target_context.new_page()
        asker_name, target_name = unique("Asker"), unique("Busy")
        chip = target.locator(
            '[data-testid="room-header"] .room-notice-chip[data-notice="friend-request"]'
        )
        popover = target.locator('.room-notice-popover[data-notice="friend-request"]')

        try:
            await sign_up(asker, asker_name)
            await sign_up(target, target_name)

            # The target goes into a room, where the lobby cannot be seen
            # at all - which is the whole point of the chip and the badge.
            await target.click('button:has-text("Create room")')
            await target.click('button:has-text("Create room")')
            await target.wait_for_selector('[data-testid="waiting-room"]')

            await ask_from_profile(asker, target_name)

            # Said, by name, in the bar rather than over the room - and once,
            # from outside it, where a hidden bar cannot swallow it.
            await expect(chip).to_be_visible(timeout=SETTLE_MS)
            await expect(chip).to_have_attribute(
                "aria-label", re.compile(rf"^Friend request: {asker_name} ")
            )
            await expect(target.get_by_test_id("friend-request-announcer")).to_contain_text(
                asker_name
            )
            await expect(target.locator(".app-toast")).to_have_count(0)
            # And counted, on the control that opens the way to answer it.
            await expect(
                target.locator('[data-testid="friend-request-badge"]')
            ).to_have_text("1", timeout=SETTLE_MS)

            # Declining is deliberately not on it: a refusal is kept, so it
            # belongs behind the confirmation the friends surface gives it.
            await chip.click()
            await expect(popover).to_contain_text(asker_name)
            await expect(popover.get_by_role("button", name="Decline")).to_have_count(0)

            # Answered from the chip itself - without opening the menu, the
            # surface, or leaving the room.
            await popover.get_by_role("button", name="Accept").click()

            # The asker is told, and this is checked first because it is the
            # only assertion here with a deadline: an acceptance is read
            # rather than acted on, so its toast keeps the ordinary five
            # seconds. Everything below is a settled state that waits.
            await expect(asker.locator(".app-toast").filter(
                has_text=target_name
            ).first).to_be_visible(timeout=SETTLE_MS)

            await expect(
                target.locator('[data-testid="friend-request-badge"]')
            ).to_have_count(0, timeout=SETTLE_MS)
            # The chip goes with the answer: a button that would now do
            # nothing is worse than no button.
            await expect(chip).to_have_count(0, timeout=SETTLE_MS)
            await expect(target.locator('[data-testid="waiting-room"]')).to_be_visible()
        finally:
            await asker_context.close()
            await target_context.close()
            await browser.close()


async def test_a_request_notice_goes_once_it_is_answered_anywhere():
    """#1197: the toast's Accept stood for the rest of its twelve seconds after
    the request had been accepted on the friends surface. Whatever shows a
    request - the toast outside a room, the chip in one - goes as soon as it
    stops waiting: answered in another tab, or withdrawn by the asker. The
    chip's Not now puts it away without telling anybody (R-FRIEND-05); leaving
    the room puts it away too, and a toast still up when a room opens moves
    into the bar rather than standing over the room."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        asker_context = await browser.new_context()
        target_context = await browser.new_context()
        asker = await asker_context.new_page()
        target = await target_context.new_page()
        asker_name, target_name = unique("Asker"), unique("Twotabs")
        toast = target.locator(".app-toast").filter(has_text=asker_name)
        chip = target.locator(
            '[data-testid="room-header"] .room-notice-chip[data-notice="friend-request"]'
        )
        any_chip = target.locator('.room-notice-chip[data-notice="friend-request"]')
        popover = target.locator('.room-notice-popover[data-notice="friend-request"]')
        announcer = target.get_by_test_id("friend-request-announcer")

        # Everything the target says to the server while `listening` holds:
        # HTTP writes to the friends API, and every Socket.IO event it emits.
        listening: list[bool] = []
        writes: list[str] = []
        emitted: list[str] = []

        def on_frame(payload) -> None:
            # "42" is an event, "45" a binary one. The health report is the
            # socket's own minute timer and says nothing about anybody.
            if (listening and isinstance(payload, str) and payload[:2] in ("42", "45")
                    and "client_health" not in payload):
                emitted.append(payload)

        target.on("websocket", lambda ws: ws.on("framesent", on_frame))
        target.on(
            "request",
            lambda request: writes.append(request.url)
            if listening and "/api/friends" in request.url and request.method != "GET"
            else None,
        )

        async def create_room() -> None:
            await target.click('button:has-text("Create room")')
            await target.click('button:has-text("Create room")')
            await target.wait_for_selector('[data-testid="waiting-room"]')

        async def withdraw() -> None:
            await open_friends(asker)
            outgoing = asker.locator('[data-testid="friends-outgoing"]')
            await expect(outgoing).to_contain_text(target_name, timeout=SETTLE_MS)
            await outgoing.get_by_role("button", name="Cancel").click()
            await expect(outgoing).to_have_count(0, timeout=SETTLE_MS)
            await asker.goto(BASE_URL)

        try:
            await sign_up(asker, asker_name)
            await sign_up(target, target_name)

            # In a room: put off with Not now, which sends nothing at all -
            # no request, no socket event - so nobody can learn of it.
            await create_room()
            await ask_from_profile(asker, target_name)
            await expect(chip).to_be_visible(timeout=SETTLE_MS)
            await chip.click()
            listening.append(True)
            await popover.get_by_role("button", name="Not now").click()
            await expect(chip).to_have_count(0)
            # Long enough for anything the click set off to have gone out.
            await target.wait_for_timeout(1000)
            listening.clear()
            assert writes == [], writes
            assert emitted == [], emitted
            # Still waiting, under its badge, where it is answered.
            await expect(
                target.locator('[data-testid="friend-request-badge"]')
            ).to_have_text("1")

            # Withdrawn by the asker, a request shown again takes its chip.
            await withdraw()
            await ask_from_profile(asker, target_name)
            await expect(chip).to_be_visible(timeout=SETTLE_MS)
            await withdraw()
            await expect(chip).to_have_count(0, timeout=SETTLE_MS)

            # Leaving the room with the chip up puts it away: the lobby gets
            # neither a chip nor a toast for it, only the badge's count.
            await ask_from_profile(asker, target_name)
            await expect(chip).to_be_visible(timeout=SETTLE_MS)
            await leave_room(target)
            await target.wait_for_selector('[data-testid="quick-play"]')
            # A toast would be raised on the way out, if at all; give it the
            # moment it would take.
            await target.wait_for_timeout(1000)
            await expect(toast).to_have_count(0)
            await expect(any_chip).to_have_count(0)
            await expect(
                target.locator('[data-testid="friend-request-badge"]')
            ).to_have_text("1")

            # Asked while in the lobby, it is a toast; opening a room moves it
            # into the bar, and it is not said a second time on the way in.
            await withdraw()
            await ask_from_profile(asker, target_name)
            await expect(toast).to_be_visible(timeout=SETTLE_MS)
            await create_room()
            await expect(chip).to_be_visible(timeout=SETTLE_MS)
            await expect(toast).to_have_count(0)
            await expect(announcer).to_have_text("")

            # Outside a room it is a toast, and accepting in another tab of
            # the same account takes it down well inside its twelve seconds.
            await leave_room(target)
            await target.wait_for_selector('[data-testid="quick-play"]')
            await withdraw()
            await ask_from_profile(asker, target_name)
            await expect(toast).to_be_visible(timeout=SETTLE_MS)
            second = await target_context.new_page()
            await second.goto(BASE_URL)
            await open_friends(second)
            accept = second.locator('[data-testid="friends-incoming"]').get_by_role(
                "button", name="Accept"
            )
            await expect(accept).to_be_visible(timeout=SETTLE_MS)
            await expect(toast).to_be_visible()
            await accept.click()
            await expect(toast).to_have_count(0, timeout=5000)
        finally:
            await asker_context.close()
            await target_context.close()
            await browser.close()


async def test_an_acceptance_mid_game_waits_for_the_lobby():
    """#1200: "X accepted your friend request" was a five-second toast, and in
    a phone room it stood on the chat feed's newest line. It has nothing to
    offer, so it is not a chip either: it is held while the room is up and
    said as the usual toast once the room is left - once, and recorded as told
    only then (R-FRIEND-14), so a reload in the lobby does not say it again.
    A reload mid-game is still in the room, though the bar is not drawn yet."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        asker_context = await browser.new_context(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
        )
        target_context = await browser.new_context()
        other_context = await browser.new_context()
        asker = await asker_context.new_page()
        target = await target_context.new_page()
        other = await other_context.new_page()
        asker_name, target_name, other_name = unique("Asker"), unique("Yes"), unique("Other")
        accepted = asker.locator(".app-toast").filter(has_text="accepted your friend request")

        # The asker's own reads of its lists, so the test knows the acceptance
        # reached the room rather than guessing at a delay.
        reads = []
        asker.on(
            "response",
            lambda response: reads.append(response)
            if response.url.endswith("/api/users/me/friends")
            and response.request.method == "GET"
            else None,
        )

        # Recorded as told (R-FRIEND-14): a toast that flashed and was taken
        # down again as the room drew its bar leaves this behind.
        told: list[str] = []
        asker.on(
            "request",
            lambda request: told.append(asker.url)
            if request.method == "POST" and request.url.endswith("/friends/announced")
            else None,
        )

        async def a_read_names_the_acceptance() -> None:
            checked = 0
            for _ in range(SETTLE_MS // 100):
                while checked < len(reads):
                    body = await reads[checked].json()
                    checked += 1
                    if any(row.get("displayName") == target_name for row in body.get("announce", [])):
                        return
                await asker.wait_for_timeout(100)
            raise AssertionError("the asker never read the acceptance")

        try:
            await sign_up(target, target_name)
            await sign_up(asker, asker_name)
            await ask_from_profile(asker, target_name)

            # The asker goes into a game before the answer comes.
            await asker.click('button:has-text("Create room")')
            await asker.wait_for_selector(".create-room-page")
            await asker.click('button:has-text("Create room")')
            await asker.wait_for_selector('[data-testid="waiting-room"]')
            code = await asker.locator('[data-testid="room-header"]').get_attribute(
                "data-room-code"
            )
            await other.goto(BASE_URL)
            await use_guest_name(other, other_name)
            await join_by_code(other, code)
            await other.wait_for_selector('[data-testid="waiting-room"]')
            await asker.get_by_role("button", name="Start game").click()
            await asker.wait_for_selector(".game-room-playing")

            reads.clear()
            await open_friends(target)
            accept = target.locator('[data-testid="friends-incoming"]').get_by_role(
                "button", name="Accept"
            )
            await expect(accept).to_be_visible(timeout=SETTLE_MS)
            await accept.click()

            # Heard in the room, and not said there: the toast would have been
            # raised by the render that follows the read. Counted directly
            # rather than with expect, which would wait out a toast's five
            # seconds and pass.
            await a_read_names_the_acceptance()
            for _ in range(15):
                assert await accepted.count() == 0, "an acceptance was said mid-game"
                await asker.wait_for_timeout(100)

            # Nor on a reload mid-game, whose first read can land before the
            # room has drawn its bar again: still owed, so still named.
            reads.clear()
            await asker.reload()
            await asker.wait_for_selector(".game-room-playing")
            await a_read_names_the_acceptance()
            for _ in range(15):
                assert await accepted.count() == 0, "an acceptance was said on a reload mid-game"
                await asker.wait_for_timeout(100)
            assert told == [], told

            await leave_room(asker)
            question = asker.get_by_role("alertdialog")
            await question.get_by_role("button", name="Leave game").click()
            await asker.wait_for_selector('[data-testid="quick-play"]')
            await expect(accepted).to_have_count(1, timeout=SETTLE_MS)
            await expect(accepted).to_contain_text(target_name)
            assert told, "the acceptance was never recorded as told"

            # Told, and recorded as told: the next visit does not say it again.
            await expect(accepted).to_have_count(0, timeout=SETTLE_MS)
            reads.clear()
            await asker.reload()
            await asker.wait_for_selector('[data-testid="quick-play"]')
            for _ in range(SETTLE_MS // 100):
                if reads:
                    break
                await asker.wait_for_timeout(100)
            assert reads, "the reloaded lobby never read its lists"
            for _ in range(15):
                assert await accepted.count() == 0, "an acceptance was said twice"
                await asker.wait_for_timeout(100)
        finally:
            await asker_context.close()
            await target_context.close()
            await other_context.close()
            await browser.close()


async def test_the_roster_marks_a_friend_and_only_for_the_one_reading():
    """The mark in a room, and the thing that makes it safe (R-FRIEND-13).

    Two friends and a stranger sit in one room. Each of the three sees the
    same game and a different set of marks, because the mark says something
    about the reader rather than about the game - which is why it is resolved
    per socket and named by seat, and why no account id enters a room payload
    to make it work (R-ROOM-07).
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context() for _ in range(3)]
        ada, bob, cat = [await c.new_page() for c in contexts]
        ada_name, bob_name, cat_name = unique("Ada"), unique("Bob"), unique("Cat")

        def seat(page, name):
            return page.locator(
                f'.player-row:has(.player-name:has-text("{name}"))'
            )

        try:
            await sign_up(ada, ada_name)
            await sign_up(bob, bob_name)
            await sign_up(cat, cat_name)
            await make_friends(ada, bob, ada_name, bob_name)

            # Cat hosts, so nobody's friendship decides who may be here.
            await cat.click('button:has-text("Create room")')
            await cat.click('button:has-text("Public")')
            await cat.click('button:has-text("Create room")')
            await cat.wait_for_selector('[data-testid="room-header"]')
            code = await cat.locator('[data-testid="room-header"]').get_attribute(
                "data-room-code"
            )
            for page in (ada, bob):
                await join_by_code(page, code)
                await page.wait_for_selector('[data-testid="waiting-room"]')

            for page in (ada, bob, cat):
                await expect(page.locator(".player-row")).to_have_count(
                    3, timeout=SETTLE_MS
                )

            # Ada sees Bob marked, and nobody else - not Cat, not herself.
            await expect(
                seat(ada, bob_name).locator(".avatar-friend")
            ).to_have_count(1, timeout=SETTLE_MS)
            await expect(seat(ada, cat_name).locator(".avatar-friend")).to_have_count(0)
            await expect(seat(ada, ada_name).locator(".avatar-friend")).to_have_count(0)

            # Bob sees the mirror of that.
            await expect(
                seat(bob, ada_name).locator(".avatar-friend")
            ).to_have_count(1, timeout=SETTLE_MS)
            await expect(seat(bob, cat_name).locator(".avatar-friend")).to_have_count(0)

            # Cat is friends with neither, and sees an unmarked room.
            await expect(cat.locator(".player-row .avatar-friend")).to_have_count(0)
        finally:
            for context in contexts:
                await context.close()
            await browser.close()


async def test_signing_in_does_not_announce_requests_that_were_already_there():
    """A change of identity is a new baseline, not a list of changes.

    The notice is a diff across two reads, so signing in compares "no friends"
    against a whole account's worth of them and would announce every waiting
    request as having just arrived. The badge is the right way to learn about
    a backlog; a burst of toasts on login is not.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        asker_context = await browser.new_context()
        owner_context = await browser.new_context()
        fresh_context = await browser.new_context()
        asker = await asker_context.new_page()
        owner = await owner_context.new_page()
        fresh = await fresh_context.new_page()
        asker_name, owner_name = unique("Asker"), unique("Owner")
        password = "a-good-password"

        try:
            await sign_up(asker, asker_name)
            await sign_up(owner, owner_name)
            await ask_from_profile(asker, owner_name)
            # The request is waiting before the fresh browser ever signs in.
            await expect(
                owner.locator('[data-testid="friend-request-badge"]')
            ).to_have_text("1", timeout=SETTLE_MS)

            await fresh.goto(BASE_URL)
            await fresh.click(".first-run-login")
            login = fresh.get_by_role("dialog", name="Sign in")
            await login.get_by_label("Username").fill(owner_name)
            await login.get_by_label("Password").fill(password)
            await login.get_by_role("button", name="Sign in", exact=True).click()
            await login.wait_for(state="hidden")

            # The backlog is counted, which is how it should be learned about.
            await expect(
                fresh.locator('[data-testid="friend-request-badge"]')
            ).to_have_text("1", timeout=SETTLE_MS)
            # And not announced: nothing here is new, it was waiting.
            await expect(fresh.locator(".app-toast")).to_have_count(0)
        finally:
            for context in (asker_context, owner_context, fresh_context):
                await context.close()
            await browser.close()


async def test_the_friend_mark_survives_the_narrow_layout():
    """R-FRIEND-13 says *wherever* a player is drawn, and a phone draws them
    somewhere else.

    Under 900px the sidebar roster is not mounted at all: the waiting room
    draws its own tile grid instead. The seats are asked for once for the
    whole room precisely so that the mark does not belong to whichever panel
    happened to fetch it.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        ada_context = await browser.new_context()
        bob_context = await browser.new_context()
        ada, bob = await ada_context.new_page(), await bob_context.new_page()
        ada_name, bob_name = unique("Ada"), unique("Bob")

        try:
            await sign_up(ada, ada_name)
            await sign_up(bob, bob_name)
            await make_friends(ada, bob, ada_name, bob_name)

            await bob.click('button:has-text("Create room")')
            await bob.click('button:has-text("Public")')
            await bob.click('button:has-text("Create room")')
            await bob.wait_for_selector('[data-testid="room-header"]')
            code = await bob.locator('[data-testid="room-header"]').get_attribute(
                "data-room-code"
            )
            await join_by_code(ada, code)
            await ada.wait_for_selector('[data-testid="waiting-room"]')

            # Narrowed once seated, rather than joined on a phone: getting in
            # is a different flow there (a thumb dock rather than the header),
            # and this is about what the room draws, not how it was entered.
            await ada.set_viewport_size({"width": 420, "height": 900})

            # The narrow waiting roster, which is a different component from
            # the sidebar one and used to draw no marks at all.
            tile = ada.locator(
                f'.waiting-roster-tile:has(.waiting-roster-name:has-text("{bob_name}"))'
            )
            await expect(tile).to_be_visible(timeout=SETTLE_MS)
            await expect(tile.locator(".avatar-friend")).to_have_count(
                1, timeout=SETTLE_MS
            )
            # And still only for the one reading: Ada's own tile is unmarked.
            own = ada.locator(
                f'.waiting-roster-tile:has(.waiting-roster-name:has-text("{ada_name}"))'
            )
            await expect(own.locator(".avatar-friend")).to_have_count(0)
        finally:
            await ada_context.close()
            await bob_context.close()
            await browser.close()
