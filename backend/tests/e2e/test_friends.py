"""Friends, end to end: asking, answering, and getting into a private room.

Two accounts in two browser contexts, over a real socket and a real database.
The part worth proving here is the part unit tests cannot: that a friendship
made in the lobby is what lets somebody through a door they can never name.
"""
import re
import uuid

import pytest
from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import register_account, use_guest_name

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


async def make_friends(asker, accepter, asker_name: str, accepter_name: str) -> None:
    """Ask from one lobby, and answer it where requests are answered.

    Which is the friends surface, not the lobby row: the online panel says a
    request is waiting and stops there (R-FRIEND-10).
    """
    row = row_for(asker, accepter_name)
    await expect(row).to_be_visible(timeout=SETTLE_MS)
    await row.locator(".online-add-friend").click()

    await expect(row_for(accepter, asker_name)).to_contain_text(
        "Wants to be friends", timeout=SETTLE_MS
    )
    await open_friends(accepter)
    incoming = accepter.locator('[data-testid="friends-incoming"]').get_by_role(
        "button", name="Accept"
    )
    await expect(incoming).to_be_visible(timeout=SETTLE_MS)
    await incoming.click()
    await accepter.get_by_role("button", name="Close friends").click()
    # Both sides settle on a friendship: the asker's row stops offering to ask.
    await expect(row.locator(".online-add-friend")).to_have_count(
        0, timeout=SETTLE_MS
    )


@pytest.mark.asyncio
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
            await bob.wait_for_selector(".room-copy-button")
            code = await bob.locator(".room-copy-button").first.get_attribute(
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


@pytest.mark.asyncio
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
            await host.wait_for_selector(".room-copy-button")

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


@pytest.mark.asyncio
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

            # The member sees the guest, and is offered nothing for them.
            guest_row = row_for(as_member, guest_name)
            await expect(guest_row).to_be_visible(timeout=SETTLE_MS)
            await expect(guest_row.locator(".online-add-friend")).to_have_count(0)

            # And the guest is offered nothing for the member either.
            member_row = row_for(as_guest, member_name)
            await expect(member_row).to_be_visible(timeout=SETTLE_MS)
            await expect(member_row.locator(".online-add-friend")).to_have_count(0)
            await expect(member_row.locator(".online-player-status")).to_have_text(
                re.compile("In the lobby")
            )
        finally:
            await guest_context.close()
            await member_context.close()
            await browser.close()


@pytest.mark.asyncio
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

            row = row_for(asker, target_name)
            await expect(row).to_be_visible(timeout=SETTLE_MS)
            await row.locator(".online-add-friend").click()
            # The lobby row settles before the asker's browser is the only one
            # left, so what follows is about the surface rather than a race.
            # Asserted over the row: it carries two statuses, the friendship's
            # and the presence one, and this is about the first.
            await expect(row).to_contain_text("Request sent", timeout=SETTLE_MS)

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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_the_online_panel_reports_a_request_without_answering_it():
    """Who is online says who is around; Friends is where a request is answered.

    A pair of answer buttons on a row that comes and goes with presence is a
    decision taken in the wrong place - and a decline in particular is kept
    (R-FRIEND-05), so it belongs behind the confirmation the surface gives it.
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

            row = row_for(asker, target_name)
            await expect(row).to_be_visible(timeout=SETTLE_MS)
            await row.locator(".online-add-friend").click()

            await expect(row_for(target, asker_name)).to_contain_text(
                "Wants to be friends", timeout=SETTLE_MS
            )
            # Stated, not offered - anywhere on the panel, for anyone.
            panel = target.locator('[data-testid="online-players-list"]')
            await expect(panel.get_by_role("button", name="Accept")).to_have_count(0)
            await expect(panel.get_by_role("button", name="Decline")).to_have_count(0)
            # And the block that used to carry requests from offline senders is
            # gone with it: the surface holds those now.
            await expect(
                target.locator('[data-testid="friend-requests"]')
            ).to_have_count(0)

            # The mirror of it on the sender's side.
            await expect(row).to_contain_text("Request sent", timeout=SETTLE_MS)
        finally:
            await asker_context.close()
            await target_context.close()


@pytest.mark.asyncio
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

            row = row_for(ada, bob_name)
            await expect(row).to_be_visible(timeout=SETTLE_MS)
            # The name is the way in. A guest's is not a link, which the
            # existing guest test already pins from the other direction.
            await row.locator("a.online-player-name").click()
            await ada.wait_for_selector(".profile-identity")
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


@pytest.mark.asyncio
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
