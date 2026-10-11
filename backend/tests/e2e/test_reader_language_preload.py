"""The page shell asks for the reader's language - and on an invite link the
room's page - before the entry has run, and a non-English reader downloads
no English (#1426).

English was in the entry chunk, so a French reader downloaded English and then
French, one after the other, before the first paint; the French chunk was only
asked for once the entry had run. Now every language is a chunk, and an inline
script in `index.html` preloads the reader's."""
import asyncio
import json
import re

from playwright.async_api import async_playwright, expect


BASE_URL = "http://localhost:8000"
CATALOGUE = re.compile(r"/assets/(en|de|es|fr|it|nl|pl|pt)-[\w-]+\.js$")


async def test_a_french_reader_gets_french_first_and_no_english():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(locale="fr-FR")
        page = await context.new_page()
        fetched: list[str] = []
        page.on(
            "request",
            lambda request: fetched.append(CATALOGUE.search(request.url).group(1))
            if CATALOGUE.search(request.url)
            else None,
        )
        try:
            # The shell carries the plan: every language a chunk of its own,
            # English included, and the room's page with its imports.
            shell = await (await page.request.get(BASE_URL)).text()
            plan = json.loads(re.search(r"var p=(\{\"locales\":.*?\});", shell).group(1))
            assert set(plan["locales"]) == {"de", "en", "es", "fr", "it", "nl", "pl", "pt"}
            assert re.search(r"^assets/en-[\w-]+\.js$", plan["locales"]["en"][0])
            assert any("GameRoomPage-" in path for path in plan["room"])
            # After Vite's own tags: before them, the room's preloads starved vendor.
            assert shell.index("var p=") > shell.index('rel="modulepreload"')

            await page.goto(BASE_URL)
            await expect(page.locator("html")).to_have_attribute("lang", "fr")
            assert "fr" in fetched and "en" not in fetched, fetched
            await page.goto(f"{BASE_URL}/room/NOPE42")
            await expect(page.locator(f'head link[rel="modulepreload"][href="/{plan["room"][0]}"]')).to_have_count(1)
            # And its stylesheets: Vite's loader holds the page's import for them.
            assert any("GameRoomPage-" in path and path.endswith(".css") for path in plan["roomCss"]), plan["roomCss"]
            await expect(page.locator(f'head link[rel="preload"][as="style"][href="/{plan["roomCss"][0]}"]')).to_have_count(1)
            assert "en" not in fetched, fetched
        finally:
            await context.close()
            await browser.close()


async def test_a_language_that_stalls_paints_in_english_and_then_switches():
    """Review of #1426: the paint waited for the reader's chunk without a
    bound. Past the bound English stands in, and theirs arrives as a switch."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(locale="fr-FR")
        page = await context.new_page()
        release = asyncio.Event()

        async def stall(route):
            await release.wait()
            await route.continue_()

        await page.route(re.compile(r"/assets/fr-[\w-]+\.js$"), stall)
        try:
            await page.goto(BASE_URL)
            await expect(page.locator("html")).to_have_attribute("lang", "en", timeout=6000)
            await expect(page.locator("#root")).not_to_be_empty()
            release.set()
            await expect(page.locator("html")).to_have_attribute("lang", "fr")
        finally:
            release.set()
            await context.close()
            await browser.close()


async def test_a_page_with_no_language_at_all_says_so_rather_than_going_blank():
    """Review of #1426: with English a chunk too, a first visit that can fetch
    no catalogue had nothing to render with, and the crash page needs words as
    well. The shell's own page needs none."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(locale="en-US")
        page = await context.new_page()
        await page.route(CATALOGUE, lambda route: route.abort())
        try:
            await page.goto(BASE_URL)
            notice = page.locator("#no-words")
            await expect(notice).to_be_visible(timeout=10000)
            await expect(notice.get_by_role("button", name="Reload")).to_be_visible()
        finally:
            await context.close()
            await browser.close()
