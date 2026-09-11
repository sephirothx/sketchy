"""A refused settings write is reported wherever it was made (R-SET-05).

The lobby's language flag saves to the account like any Settings row, but the
only thing listening for a refused save used to be the Settings panel - so a
save that failed from the lobby vanished, and the player's other devices kept
the old language without anybody being told. Here the account's settings
PATCH is made to fail, the language is changed from the lobby with Settings
never opened, and the notice has to appear while the choice stays applied.
"""
from __future__ import annotations

import re
import uuid

from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import register_account, use_guest_name


BASE_URL = "http://localhost:8000"


async def test_a_refused_save_from_the_lobby_raises_a_notice():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(locale="en-US")
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "Synced")
            await register_account(page, f"sy_{uuid.uuid4().hex[:8]}")

            async def refuse_writes(route):
                if route.request.method == "PATCH":
                    await route.fulfill(status=500, body="")
                else:
                    await route.continue_()

            await page.route("**/api/users/me/settings", refuse_writes)

            await page.locator(".lobby-header .language-picker-trigger").click()
            await page.get_by_role("option", name=re.compile("Deutsch")).click()

            notice = page.locator(".app-toast.error")
            await notice.wait_for(timeout=10_000)
            # Applied here all the same: the notice says it did not follow the
            # player to their other devices, not that nothing happened.
            assert await page.evaluate("document.documentElement.lang") == "de"
        finally:
            await context.close()
            await browser.close()
