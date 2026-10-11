"""The page shell asks for the reader's language - and on an invite link the
room's page - before the entry has run, and a non-English reader downloads
no English (#1426).

English was in the entry chunk, so a French reader downloaded English and then
French, one after the other, before the first paint; the French chunk was only
asked for once the entry had run. Now every language is a chunk, and an inline
script in `index.html` preloads the reader's."""
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
            assert "en" not in fetched, fetched
        finally:
            await context.close()
            await browser.close()
