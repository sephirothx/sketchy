"""The privacy notice and the terms, where a player meets them (#1417)."""
import re
import time

from playwright.async_api import async_playwright, expect

from tests.e2e.lobby_helpers import open_new_room, register_account, room_code, use_guest_name
from tests.e2e.staff_helpers import set_role

BASE_URL = "http://localhost:8000"


def _suffix() -> str:
    return str(time.time_ns())[-6:]


async def test_a_suspended_player_can_read_the_privacy_notice_and_the_terms():
    """The terms tell a suspended player how to download or delete their
    data; a dialog in front of those very pages left only Sign out
    (review of #1429)."""
    suffix = _suffix()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        moderator_context = await browser.new_context()
        target_context = await browser.new_context()
        moderator = await moderator_context.new_page()
        target = await target_context.new_page()
        try:
            await moderator.goto(BASE_URL)
            await use_guest_name(moderator, f"LegalMod{suffix}")
            await register_account(moderator, f"legalmod{suffix}")
            await target.goto(BASE_URL)
            await use_guest_name(target, f"LegalTgt{suffix}")
            await register_account(target, f"legaltgt{suffix}")
            await set_role(f"legalmod{suffix}", "moderator")

            target_id = await target.evaluate(
                "async () => (await (await fetch('/api/auth/me')).json()).id"
            )
            banned = await moderator.evaluate(
                """async (id) => (await fetch('/api/moderation/bans', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({userId: id, reason: 'Suspended for the E2E'}),
                })).status""",
                target_id,
            )
            assert banned == 201

            # Anywhere else, the notice is a dialog with one way on, and it
            # now links the two documents.
            await target.goto(BASE_URL + "/")
            dialog = target.get_by_role("alertdialog")
            await expect(dialog).to_be_visible()
            await dialog.get_by_role("link", name="privacy notice").click()

            # On the documents themselves it is a bar, and the page is usable.
            await expect(target).to_have_url(re.compile(r"/privacy$"))
            await expect(target.locator(".suspension-reading-bar")).to_be_visible()
            await expect(target.get_by_role("alertdialog")).to_have_count(0)
            await expect(target.get_by_role("heading", level=1, name="Privacy notice")).to_be_visible()
            await target.get_by_role("link", name="Terms of use").click()
            await expect(target.get_by_role("heading", level=1, name="Terms of use")).to_be_visible()
            await expect(target.get_by_role("alertdialog")).to_have_count(0)

            # Leaving for another page in the app brings the dialog back, and
            # Back - a route change, not a load - takes it away again. The
            # notice sat outside the router and kept whichever it had first.
            await target.locator("nav a.site-nav-link:not([href='/rules'])").first.click()
            await expect(target.get_by_role("alertdialog")).to_be_visible()
            await target.go_back()
            await expect(target.get_by_role("heading", level=1, name="Terms of use")).to_be_visible()
            await expect(target.locator(".suspension-reading-bar")).to_be_visible()
            await expect(target.get_by_role("alertdialog")).to_have_count(0)

            # The same page with a trailing slash is the same page.
            await target.goto(BASE_URL + "/privacy/")
            await expect(target.locator(".suspension-reading-bar")).to_be_visible()
            await expect(target.get_by_role("alertdialog")).to_have_count(0)
        finally:
            await browser.close()


async def test_every_form_that_starts_an_identity_says_what_it_agrees_to():
    """The lobby's name tag was the only one; an invite link and Settings
    made guests without the age (review of #1429). One row of links: the
    terms, the privacy notice and the age."""
    suffix = _suffix()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        host_context = await browser.new_context()
        visitor_context = await browser.new_context()
        settings_context = await browser.new_context()
        host = await host_context.new_page()
        visitor = await visitor_context.new_page()
        settings = await settings_context.new_page()
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, f"LegalHost{suffix}")
            await open_new_room(host)
            code = await room_code(host)

            await visitor.goto(f"{BASE_URL}/room/{code}")
            agreement = visitor.locator(".invite-agreement")
            await expect(agreement).to_contain_text("16 or older")
            await expect(agreement).to_contain_text("16+")
            await expect(agreement.get_by_role("link", name="Terms")).to_have_attribute("href", "/terms")
            await expect(agreement.get_by_role("link", name="Privacy")).to_have_attribute("href", "/privacy")

            await settings.goto(f"{BASE_URL}/settings")
            nameless = settings.get_by_test_id("settings-nameless")
            await expect(nameless.locator(".identity-agreement")).to_contain_text("16 or older")
        finally:
            await browser.close()
