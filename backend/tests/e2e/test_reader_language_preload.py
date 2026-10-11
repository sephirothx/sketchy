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

import pytest
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

            # An invite link, opened by somebody arriving fresh: a context of
            # its own, so nothing the lobby fetched while idle is in its cache
            # or lands in its count.
            invited = await browser.new_context(locale="fr-FR")
            room = await invited.new_page()
            urls: list[str] = []
            room.on("request", lambda request: urls.append(request.url))
            await room.goto(f"{BASE_URL}/room/NOPE42")
            await expect(room.locator(f'head link[rel="modulepreload"][href="/{plan["room"][0]}"]')).to_have_count(1)
            # And its stylesheets: Vite's loader holds the page's import for them.
            assert any("GameRoomPage-" in path and path.endswith(".css") for path in plan["roomCss"]), plan["roomCss"]
            await expect(room.locator(f'head link[rel="preload"][as="style"][crossorigin][href="/{plan["roomCss"][0]}"]')).to_have_count(1)
            # Once: Vite's loader reuses the preload rather than asking again.
            sheet = next(path for path in plan["roomCss"] if "GameRoomPage-" in path)
            await expect(room.locator(f'link[rel="stylesheet"][href$="/{sheet}"]')).to_have_count(1)
            assert sum(url.endswith("/" + sheet) for url in urls) == 1, [u for u in urls if u.endswith(".css")]
            assert not any(CATALOGUE.search(url) and "/en-" in url for url in urls), urls
            await invited.close()
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
            # Painted, in English, while French is still on its way.
            await expect(page.locator("#root")).not_to_be_empty(timeout=6000)
            await expect(page.locator("html")).to_have_attribute("lang", "en")
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


@pytest.mark.parametrize("english", ["fails", "stalls"])
async def test_a_slow_language_still_paints_when_english_cannot(english):
    """Review of #1451: past the bound the paint waited for English alone, so
    French landing meanwhile could not end the wait - a stalled English left
    the page blank, and a failed one showed the could-not-load page with
    French ready."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(locale="fr-FR")
        page = await context.new_page()
        release = asyncio.Event()

        async def late_french(route):
            await asyncio.sleep(3)
            await route.continue_()

        async def no_english(route):
            if english == "fails":
                await route.abort()
            else:
                await release.wait()

        await page.route(re.compile(r"/assets/fr-[\w-]+\.js$"), late_french)
        await page.route(re.compile(r"/assets/en-[\w-]+\.js$"), no_english)
        try:
            await page.goto(BASE_URL)
            await expect(page.locator("html")).to_have_attribute("lang", "fr", timeout=10000)
            await expect(page.locator("#root")).not_to_be_empty()
            await expect(page.locator("#no-words")).to_be_hidden()
        finally:
            release.set()
            await context.close()
            await browser.close()
