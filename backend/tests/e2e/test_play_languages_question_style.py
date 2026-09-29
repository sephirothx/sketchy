"""The first-time languages question is styled from the frame it appears on.

Its rules lived in Settings' stylesheet, which the lobby only prefetched on an
idle callback - a 1000 ms timer where the API is missing, which includes
Safari - while the question itself was in the entry chunk. The "due" flag is
kept in storage, so a player who came back with it pending (iOS discards
background tabs often) saw it at first paint as a bare list for about a
second: "1." markers, chips with no layout (#1274). The question now loads
with its own stylesheet, so it cannot be drawn before its rules are there.

Settings' chunk is held back two seconds here, the way a slow network would,
so a question still waiting on it would show unstyled for that long.
"""
import asyncio
import os
import re
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import use_guest_name

BASE_URL = "http://localhost:8000"

DUE = "localStorage.setItem('sketchy_playlanguages_question_due', '1')"

# The body's display on the frame it is first attached, before anything later
# can restyle it: `grid` once its rules are in, `block` without them.
WATCH_QUESTION = """
(() => {
  window.__questionFirstDisplay = null;
  const record = () => {
    const body = document.querySelector('.play-languages-question-body');
    if (!body || window.__questionFirstDisplay !== null) return;
    window.__questionFirstDisplay = getComputedStyle(body).display;
    observer.disconnect();
  };
  const observer = new MutationObserver(record);
  document.addEventListener('DOMContentLoaded', () => {
    observer.observe(document.body, { childList: true, subtree: true });
    record();
  });
})();
"""


def _webkit_installed(p) -> bool:
    try:
        return os.path.exists(p.webkit.executable_path)
    except Exception:
        return False


@pytest.mark.parametrize("engine", ["chromium", "webkit"])
async def test_the_languages_question_is_never_drawn_without_its_layout(engine):
    async with async_playwright() as p:
        if engine == "webkit":
            if not _webkit_installed(p):
                pytest.skip("WebKit is not installed here (CI installs Chromium and Firefox)")
            browser = await p.webkit.launch(headless=True)
        else:
            browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        await context.add_init_script(DUE)
        await context.add_init_script(WATCH_QUESTION)

        async def hold_back(route):
            await asyncio.sleep(2)
            await route.continue_()

        # Settings' own chunk and stylesheet, held back as a slow network would.
        await context.route(re.compile(r".*/assets/(SettingsOverlay|settings)-[^/]*\.(js|css)$"), hold_back)
        page = await context.new_page()
        try:
            await use_guest_name(page, f"Asked{uuid4().hex[:6]}")
            await page.goto(BASE_URL)
            question = page.get_by_test_id("play-languages-question")
            await question.wait_for(state="visible", timeout=15_000)
            first = await page.evaluate("() => window.__questionFirstDisplay")
            assert first == "grid", f"the question was first drawn with display: {first}"
        finally:
            await context.close()
            await browser.close()


def _sheets_holding_the_question() -> list[str]:
    """The built stylesheets carrying the question's rules, by file name.

    Read before the browser starts, and synchronously: the build is on disk
    beside the tests, and an async test may not block on the filesystem."""
    assets = Path(__file__).resolve().parents[3] / "frontend" / "dist" / "assets"
    return [path.name for path in assets.glob("*.css") if "play-languages-question-body" in path.read_text()]


async def test_the_question_waits_for_a_shared_sheet_another_prefetch_is_still_loading():
    """Review of #1312: the question's sheet is shared with Settings, and when
    Settings' prefetch has already put its link in the page, Vite's preload
    helper sees the link and does not wait for it. The link is put there
    first here, and held back, as that prefetch on a slow network would."""
    shared = _sheets_holding_the_question()
    assert shared, "no built stylesheet holds the question's rules"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        await context.add_init_script(DUE)
        await context.add_init_script(WATCH_QUESTION)
        await context.add_init_script(
            "document.addEventListener('DOMContentLoaded', () => {"
            + "".join(
                f"const l{i} = document.createElement('link'); l{i}.rel = 'stylesheet';"
                f" l{i}.href = '/assets/{name}'; document.head.append(l{i});"
                for i, name in enumerate(shared)
            )
            + "});"
        )

        async def hold_back(route):
            await asyncio.sleep(2)
            await route.continue_()

        await context.route(re.compile(r".*/assets/(" + "|".join(re.escape(n) for n in shared) + r")$"), hold_back)
        page = await context.new_page()
        try:
            await use_guest_name(page, f"Shared{uuid4().hex[:6]}")
            await page.goto(BASE_URL)
            question = page.get_by_test_id("play-languages-question")
            await question.wait_for(state="visible", timeout=15_000)
            first = await page.evaluate("() => window.__questionFirstDisplay")
            assert first == "grid", f"the question was first drawn with display: {first}"
        finally:
            await context.close()
            await browser.close()


async def test_a_question_whose_stylesheet_cannot_load_is_not_asked_and_breaks_nothing():
    """Review of #1274: Vite's preload helper fetches a lazy chunk's stylesheet
    before the chunk, and when the stylesheet fails it throws past a `.then`
    failure handler - which took the lobby to the crash page. The question
    is just not asked this time; it stays due for the next load."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        await context.add_init_script(DUE)

        async def refuse(route):
            await route.abort()

        # Every stylesheet fetched after the entry one: the question's among them.
        await context.route(re.compile(r".*/assets/(?!index-)[^/]*\.css$"), refuse)
        page = await context.new_page()
        try:
            await use_guest_name(page, f"Unasked{uuid4().hex[:6]}")
            await page.goto(BASE_URL)
            await page.wait_for_selector(".identity-chip")
            await page.wait_for_timeout(1500)
            assert await page.locator(".crash-card").count() == 0
            assert await page.get_by_test_id("play-languages-question").count() == 0
            await page.locator(".lobby-rooms-panel").wait_for(state="visible")
            assert await page.evaluate(
                "() => localStorage.getItem('sketchy_playlanguages_question_due')"
            ) == "1"
        finally:
            await context.close()
            await browser.close()


async def test_a_shared_sheet_later_than_the_wait_skips_the_question_rather_than_unstyling_it():
    """Review of #1312, round two: the wait's timeout was taken for "loaded",
    so a shared sheet still loading after three seconds let the question draw
    without its rules. Past the wait it is not asked this time, and stays due
    for the next load."""
    shared = _sheets_holding_the_question()
    assert shared, "no built stylesheet holds the question's rules"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        await context.add_init_script(DUE)
        await context.add_init_script(WATCH_QUESTION)
        await context.add_init_script(
            "document.addEventListener('DOMContentLoaded', () => {"
            + "".join(
                f"const l{i} = document.createElement('link'); l{i}.rel = 'stylesheet';"
                f" l{i}.href = '/assets/{name}'; document.head.append(l{i});"
                for i, name in enumerate(shared)
            )
            + "});"
        )

        async def hold_back(route):
            await asyncio.sleep(5)
            await route.continue_()

        await context.route(re.compile(r".*/assets/(" + "|".join(re.escape(n) for n in shared) + r")$"), hold_back)
        page = await context.new_page()
        try:
            await use_guest_name(page, f"Late{uuid4().hex[:6]}")
            await page.goto(BASE_URL)
            await page.wait_for_timeout(7_000)
            first = await page.evaluate("() => window.__questionFirstDisplay")
            assert first is None, f"the question was drawn, first with display: {first}"
            assert await page.evaluate("localStorage.getItem('sketchy_playlanguages_question_due')") == "1"
        finally:
            await context.close()
            await browser.close()
