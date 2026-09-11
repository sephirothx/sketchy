"""An account's language on the very first paint, in a browser that has never seen it.

R-I18N-06 puts the account's stored locale first and asks for it before the
first paint. A browser with nothing remembered and an English
`Accept-Language` is the case that tests both at once: until the account has
answered, everything the page can see points at English, so a page drawn
before that answer is drawn in English and then switches under its reader.

What is measured is the document's language at the moment React first puts
anything into `#root` - recorded by a script that runs before the app does, so
nothing the app does afterwards can change the answer.
"""
from __future__ import annotations

import secrets

from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import register_account, use_guest_name


BASE_URL = "http://localhost:8000"

FIRST_PAINT_PROBE = """
window.__firstPaintLang = null;
new MutationObserver((_, observer) => {
  const root = document.getElementById("root");
  if (root && root.childElementCount > 0) {
    window.__firstPaintLang = document.documentElement.lang;
    observer.disconnect();
  }
}).observe(document, { childList: true, subtree: true });
"""


async def test_a_german_account_is_drawn_in_german_on_a_new_browser():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        first = await browser.new_context(locale="en-US")
        second = None
        try:
            page = await first.new_page()
            await page.goto(BASE_URL)
            await use_guest_name(page, "Sprache")
            await register_account(page, f"de_{secrets.token_hex(4)}")
            status = await page.evaluate(
                """async () => (await fetch("/api/users/me/settings", {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ locale: "de" }),
                })).status"""
            )
            assert status == 200

            # The same account, somewhere it has never been: its cookie and
            # nothing else - no remembered language, an English browser.
            second = await browser.new_context(locale="en-US")
            await second.add_cookies(await first.cookies())
            await second.add_init_script(FIRST_PAINT_PROBE)
            fresh = await second.new_page()
            await fresh.goto(BASE_URL)
            await fresh.wait_for_function("() => window.__firstPaintLang !== null")
            assert await fresh.evaluate("window.__firstPaintLang") == "de", (
                "the first paint was in the browser's language, not the account's"
            )
        finally:
            if second is not None:
                await second.close()
            await first.close()
            await browser.close()
