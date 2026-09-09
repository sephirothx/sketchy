"""Setting up a passkey, and signing in with it (R-AUTH-23).

Driven with Chromium's virtual authenticator, which is the only way a browser
test can complete a WebAuthn ceremony: the real thing asks a person for a
fingerprint. The virtual one answers as a platform authenticator with user
verification, which is what this deployment asks for.

Chromium only. Firefox has no equivalent, so `test_multi_browser_game` cannot
cover this and does not try; what the other engines are tested on is the game,
which is where they differ.
"""
from __future__ import annotations

from playwright.async_api import async_playwright, expect

from tests.e2e.lobby_helpers import register_account, use_guest_name
from tests.e2e.staff_helpers import offer_role

BASE_URL = "http://localhost:8000"
PASSWORD = "a-good-password"


async def _virtual_authenticator(page):
    """A platform authenticator that verifies the user and syncs its keys.

    `hasResidentKey` and `hasUserVerification` are what make the credential
    discoverable and the gesture two factors: without them the browser would
    refuse the options this server sends, which is itself the assertion that
    those options are what it asks for.
    """
    session = await page.context.new_cdp_session(page)
    await session.send("WebAuthn.enable")
    result = await session.send(
        "WebAuthn.addVirtualAuthenticator",
        {
            "options": {
                "protocol": "ctap2",
                "transport": "internal",
                "hasResidentKey": True,
                "hasUserVerification": True,
                "isUserVerified": True,
                "automaticPresenceSimulation": True,
            }
        },
    )
    return session, result["authenticatorId"]


async def test_a_passkey_is_set_up_once_and_then_signs_in_on_its_own():
    """The whole of what a moderator does: take up the offer, then come back.

    One test rather than two, for the reason the two-factor one gives: each
    would want its own browser, and the suite already runs eight workers
    against a single server.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(10000)
        try:
            await page.goto(BASE_URL)
            await _virtual_authenticator(page)
            await use_guest_name(page, "PasskeyPlayer")
            await register_account(page, "PasskeyPlayer")

            # Nothing is offered to a player with no role waiting on them.
            await page.goto(f"{BASE_URL}/settings/account")
            await expect(page.get_by_text("Two-factor authentication")).to_have_count(0)

            await offer_role("PasskeyPlayer")
            await page.goto(f"{BASE_URL}/settings/account")
            await page.get_by_role("button", name="Set up").click()
            dialog = page.get_by_role("dialog", name="Two-factor authentication")

            # The passkey is what is offered first; the app is the fallback
            # below it.
            await expect(
                dialog.get_by_role("button", name="Set up a passkey")
            ).to_be_visible()
            await dialog.get_by_label("Your password").fill(PASSWORD)
            await dialog.get_by_role("button", name="Set up a passkey").click()

            # And the role that was waiting has begun.
            await expect(dialog).to_contain_text("You are now a moderator")
            await dialog.get_by_role("button", name="Done").click()

            # Signed out everywhere else; this browser carries on as staff.
            await page.goto(BASE_URL)
            await page.click(".identity-chip")
            await expect(
                page.get_by_role("menuitem", name="Moderation")
            ).to_be_visible()
            await page.keyboard.press("Escape")

            # Now the other half: a fresh browser, with the same authenticator
            # and no password typed at all.
            await page.evaluate("async () => { await fetch('/api/auth/logout', {method: 'POST'}); }")
            await page.goto(BASE_URL)
            await page.click(".first-run-login")
            form = page.locator(".modal-card").filter(has_text="Password")
            await form.get_by_role("button", name="Sign in with a passkey").click()
            await expect(form).to_have_count(0)
            await expect(page.locator(".identity-chip")).to_contain_text(
                "PasskeyPlayer"
            )
        finally:
            await context.close()
            await browser.close()
