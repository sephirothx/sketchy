"""The recovery pages outside a session: forgot, reset and verify (#1280)."""
from playwright.async_api import async_playwright, expect

BASE_URL = "http://localhost:8000"


async def test_each_recovery_step_has_its_own_words_and_a_phone_gets_the_form_first():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        laptop = await browser.new_context(viewport={"width": 1280, "height": 800})
        phone = await browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        page, handset = await laptop.new_page(), await phone.new_page()
        try:
            # A dead verification link says so, as a dead reset link does -
            # not "Confirming your email" over the refusal - and its aside is
            # about the address, not about forgetting.
            await page.goto(f"{BASE_URL}/verify-email?token=not-a-real-token")
            await expect(page.get_by_role("heading", level=1)).to_have_text("That link no longer works")
            await expect(page.locator(".recovery-aside h2")).to_have_text("A spare key to your account.")

            # Forgot names the confirmed email once, in the form.
            await page.goto(f"{BASE_URL}/forgot-password")
            await expect(page.locator(".recovery-aside h2")).to_have_text("Even the best guessers forget sometimes.")
            text = await page.locator(".recovery-card").inner_text()
            assert text.lower().count("confirmed email") == 1, text

            # A phone opens on the form, not on the encouragement above it.
            await handset.goto(f"{BASE_URL}/forgot-password")
            await expect(handset.locator("#recovery-identifier")).to_be_visible()
            await expect(handset.locator(".recovery-aside")).to_be_hidden()
        finally:
            await laptop.close()
            await phone.close()
            await browser.close()


async def test_a_verification_that_never_reached_the_server_does_not_call_the_link_dead():
    """Review of #1329: any failure read "That link no longer works", though a
    network error says nothing about a link that may work on a second try."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        await context.route("**/api/auth/email/verify", lambda route: route.abort())
        page = await context.new_page()
        try:
            await page.goto(f"{BASE_URL}/verify-email?token=some-token")
            await expect(page.get_by_role("heading", level=1)).to_have_text("Could not confirm your email")
        finally:
            await context.close()
            await browser.close()
