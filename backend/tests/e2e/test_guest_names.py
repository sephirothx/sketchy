"""One guest name per person online (R-ACCT-09), from both sides of it."""
from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import use_guest_name


BASE_URL = "http://localhost:8000"


async def test_a_guest_who_comes_back_to_a_taken_name_chooses_another():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        returning_context = await browser.new_context()
        holder_context = await browser.new_context()
        stranger_context = await browser.new_context()
        try:
            # Chose the name while nobody else had it, and is not here now:
            # named before any page opened, so this browser holds the cookie
            # and has never held a socket.
            returning = await returning_context.new_page()
            await use_guest_name(returning, "DupeGuest")
            await returning.close()

            # Nobody online holds it now, so somebody else may take it.
            holder = await holder_context.new_page()
            await holder.goto(BASE_URL)
            await use_guest_name(holder, "DupeGuest")
            online = holder.get_by_test_id("online-players-list")
            await online.get_by_text("DupeGuest", exact=True).wait_for()

            # A third visitor cannot, while the holder is here - whatever the case.
            stranger = await stranger_context.new_page()
            await stranger.goto(BASE_URL)
            await stranger.wait_for_selector(".first-run")
            await stranger.fill(".first-run-guest-row input", "dupeguest")
            await stranger.click(".first-run-guest-submit")
            await stranger.locator(".first-run .auth-error").get_by_text(
                "already playing under that name"
            ).wait_for()

            # The first comes back and is asked for another name before playing,
            # and the online list still shows one DupeGuest.
            returning = await returning_context.new_page()
            await returning.goto(BASE_URL)
            notice = returning.locator(".first-run-name-in-use")
            await notice.wait_for()
            assert "DupeGuest" in await notice.inner_text()
            await returning.wait_for_timeout(1500)
            assert await online.get_by_text("DupeGuest", exact=True).count() == 1

            await returning.fill(".first-run-guest-row input", "DupeGuestTwo")
            await returning.click(".first-run-guest-submit")
            await returning.locator(".first-run").wait_for(state="detached")
            await online.get_by_text("DupeGuestTwo", exact=True).wait_for()
            assert await online.get_by_text("DupeGuest", exact=True).count() == 1
        finally:
            await returning_context.close()
            await holder_context.close()
            await stranger_context.close()
            await browser.close()
