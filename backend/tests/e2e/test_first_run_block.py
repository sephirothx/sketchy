"""The lobby's first landing (#588, #590): a name tag, a line from the pool, and
a button that only names you."""

import random
import re

from playwright.async_api import async_playwright


BASE_URL = "http://localhost:8000"

# The English pool, as `content/ui/en.ts` has it.
LINES = {
    "That is a submarine? I thought it was a toothbrush.",
    "Time to prove your art teacher wrong.",
    "Cubism, but by accident.",
    "Is that you, Michelangelo?",
    "Wow, it looks like a Pollock!",
}
ITALIAN_LINES = {
    "\u00c8 uno spazzolino? Credevo fosse una scopa.",
    "Sfoggia le doti artistiche che non sapevi di avere.",
    "Cubismo, per sbaglio.",
    "Sei proprio tu, Michelangelo?",
    "Bello, sembra un Pollock!",
}
SUBTITLE = (
    "One player draws, everybody else tries to guess. "
    "No account, no install, no talent required."
)


async def test_the_first_landing_names_you_and_says_what_the_game_is():
    # A guest name is held while somebody online has it (R-ACCT-09), so a rerun
    # against a warm server cannot reuse the last one.
    tag = random.randint(1000, 9999)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        try:
            for width, mobile in ((1280, False), (390, True)):
                context = await browser.new_context(
                    viewport={"width": width, "height": 860}, is_mobile=mobile, has_touch=mobile
                )
                page = await context.new_page()
                await page.goto(BASE_URL)
                await page.wait_for_selector(".first-run")

                # One line of the pool, and the subtitle that never changes.
                line = (await page.locator(".first-run-heading").inner_text()).strip()
                assert line in LINES, line
                assert (await page.locator(".first-run-copy").inner_text()).strip() == SUBTITLE
                # The account offer is there, and it is not the loud one.
                assert await page.locator(".first-run-account .first-run-signup").count() == 1
                assert await page.locator(".first-run-account .first-run-login").count() == 1
                # Nothing in the block runs off the edge of the screen.
                assert await page.evaluate("document.documentElement.scrollWidth") <= width

                # The tag's button names the player. It must not put them in a game.
                await page.fill(".first-run-guest-row input", f"Tag{tag}w{width}")
                await page.click(".first-run-guest-submit")
                await page.wait_for_selector(".identity-chip")
                assert await page.locator(".first-run").count() == 0
                assert await page.locator('[data-testid="waiting-room"]').count() == 0
                assert await page.locator(".lobby-page").count() == 1
                await context.close()
        finally:
            await browser.close()


async def test_the_line_changes_language_with_the_page():
    """The line was held as a string, so switching language left the previous
    language's joke on screen until the page was reloaded."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 1280, "height": 800}, locale="en-US")
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            heading = page.locator(".first-run-heading")
            await heading.wait_for()
            assert (await heading.inner_text()).strip() in LINES

            await page.click(".lobby-header .language-picker-trigger")
            await page.get_by_role("option", name=re.compile("italiano", re.IGNORECASE)).click()
            await page.wait_for_function("() => document.documentElement.lang === 'it'")

            line = (await heading.inner_text()).strip()
            assert line not in LINES, f"still the English pool: {line}"
            assert line in ITALIAN_LINES, line
            # And the subtitle is Italian too, without a reload.
            assert "Nessun account" in await page.locator(".first-run-copy").inner_text()
        finally:
            await context.close()
            await browser.close()
