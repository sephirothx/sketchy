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


async def make_friends(asker, accepter, asker_name: str, accepter_name: str) -> None:
    """Ask from one lobby and accept from the other."""
    row = row_for(asker, accepter_name)
    await expect(row).to_be_visible(timeout=SETTLE_MS)
    await row.locator(".online-add-friend").click()

    incoming = row_for(accepter, asker_name).get_by_role("button", name="Accept")
    await expect(incoming).to_be_visible(timeout=SETTLE_MS)
    await incoming.click()
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
