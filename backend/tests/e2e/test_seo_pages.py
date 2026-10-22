"""What a search engine reads, before and after the page's script runs (#1458, #1459).

Against the real built shell and server: the crawler files are routes in front
of the static mount, each public page carries its own head in the HTML, and
the title the app sets once it runs is the one the server wrote. A crawler
that renders the page indexes what the app leaves behind, so a disagreement
between the two would undo the server's work.
"""
import re
import urllib.request

from playwright.async_api import async_playwright

BASE_URL = "http://localhost:8000"


def fetch(path: str) -> tuple[int, dict[str, str], str]:
    with urllib.request.urlopen(BASE_URL + path) as answer:
        return answer.status, {k.lower(): v for k, v in answer.headers.items()}, answer.read().decode()


def served_title(body: str) -> str:
    import html

    return html.unescape(re.search(r"<title>(.*?)</title>", body, re.S).group(1))


def test_the_crawler_files_are_served_in_front_of_the_static_mount():
    status, headers, body = fetch("/robots.txt")
    assert status == 200 and headers["content-type"].startswith("text/plain")
    assert body.startswith("User-agent: *")
    status, _, body = fetch("/sitemap.xml")
    assert status == 200 and "/prompt-lists/english_standard</loc>" in body


def test_every_page_in_the_sitemap_is_served_its_own_head():
    # The build writes the lists' heads from the seed files and the server
    # serves the lists it seeded from them: a list the two disagree about -
    # a name list expanded one way here and another there - would be listed
    # in the sitemap with the generic head.
    _, _, sitemap = fetch("/sitemap.xml")
    paths = [
        re.sub(r"^https?://[^/]+", "", location)
        for location in re.findall(r"<loc>([^<]+)</loc>", sitemap)
    ]
    assert len(paths) > 100, paths
    for path in paths:
        status, headers, body = fetch(path)
        assert status == 200, path
        assert "x-robots-tag" not in headers, path
        assert served_title(body) != "Sketchy", f"{path} was served the generic head"


async def test_the_app_keeps_the_title_the_server_wrote():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()
        try:
            for path in (
                "/",
                "/rules",
                "/terms",
                "/privacy",
                "/solo",
                "/prompt-lists/english_standard",
                # A name list, expanded per language by the seed (#1399).
                "/prompt-lists/french_pokemon_gen1",
            ):
                _, headers, body = fetch(path)
                assert "x-robots-tag" not in headers, path
                expected = served_title(body)
                assert expected != "Sketchy", f"{path} was served the generic head"
                assert re.search(r'<link rel="canonical" href="[^"]+' + re.escape(path.rstrip("/")), body), path
                await page.goto(BASE_URL + path)
                # Settled: the page's own heading is drawn by then.
                await page.locator("h1").first.wait_for(state="attached")
                await page.wait_for_function(
                    "expected => document.title === expected", arg=expected, timeout=10_000
                )
                description = await page.locator('meta[name="description"]').get_attribute("content")
                assert description == re.search(
                    r'<meta name="description" content="([^"]*)"', body
                ).group(1).replace("&amp;", "&"), path
        finally:
            await browser.close()


async def test_the_readable_text_is_there_without_script_and_gone_with_it():
    # #1460: the words a crawler that runs no script reads, and which a
    # player's browser never parses - a <noscript>, replaced on mount.
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        try:
            plain = await browser.new_context(java_script_enabled=False)
            page = await plain.new_page()
            await page.goto(BASE_URL + "/rules")
            await page.get_by_role("heading", name="Harassment").wait_for()
            assert await page.locator(".prerender").is_visible()
            await page.goto(BASE_URL + "/")
            assert await page.get_by_role("link", name="Prompt stats").count() == 1
            assert await page.locator("h1").inner_text() == (
                "Sketchy – Free multiplayer drawing & guessing game"
            )
            # The contact address is the server's to fill in: an address, or
            # the words the page shows without one - never the placeholder.
            await page.goto(BASE_URL + "/privacy")
            text = await page.locator(".prerender").inner_text()
            assert "{contact}" not in text and "Who is responsible" in text
            await plain.close()

            context = await browser.new_context()
            page = await context.new_page()
            # In a <noscript>, which a browser that runs script never parses:
            # no element to lay out, no font fetched for it. Read before
            # React has drawn anything (it waits on the account read first).
            await page.add_init_script(
                """
                document.addEventListener('DOMContentLoaded', () => {
                  const copy = document.querySelector('.prerender');
                  window.__copy = copy ? getComputedStyle(copy).display : 'gone';
                });
                """
            )
            await page.goto(BASE_URL + "/rules")
            await page.locator(".rules-page").wait_for()
            assert await page.evaluate("window.__copy") == "gone"
            assert await page.locator(".prerender").count() == 0
            await context.close()
        finally:
            await browser.close()
