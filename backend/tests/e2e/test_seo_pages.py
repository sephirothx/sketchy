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


async def test_the_app_keeps_the_title_the_server_wrote():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()
        try:
            for path in ("/", "/rules", "/terms", "/privacy", "/solo", "/prompt-lists/english_standard"):
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
