"""The crash page: what a screen shows when its own code throws, and the report it files.

The crash is real - a component under each boundary throws on request through
`window.__SKETCHY_CRASH__`, which exists only in the diagnostics build the E2E
runner makes - so what is under test is the recovery, not a stub of it.
"""
import os

import pytest
from playwright.async_api import async_playwright, expect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import BugReport
from tests.e2e.a11y import assert_no_axe_violations
from tests.e2e.lobby_helpers import join_by_code, room_code, use_guest_name

BASE_URL = "http://localhost:8000"
HEADING = "A bug crawled onto the page"


async def filed_reports_mentioning(marker: str) -> list[BugReport]:
    """The reports whose details carry `marker`, read from the server's own database.

    The URL comes from the runner rather than being guessed, for the same reason
    as in test_bug_reporting.py: the suite gets a throwaway database per run.
    """
    url = os.environ.get("SKETCHY_E2E_DATABASE_URL")
    if not url:
        pytest.skip("SKETCHY_E2E_DATABASE_URL is not set; run via scripts/test-e2e.sh")
    engine = create_async_engine(url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            result = await session.execute(
                select(BugReport).where(BugReport.details.contains(marker))
            )
            return list(result.scalars().all())
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_crash_at_the_root_shows_the_page_and_files_a_prefilled_report():
    """R-UX-06, R-BUG-01. Before this a render error was a blank page.

    The report is the interesting half: the player types one line, and what
    arrives carries the crash in the summary, the diagnostic block under their
    words, and the `render` entry on top of the error tail.
    """
    marker = "crash-e2e-root-7f3a"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()
        page.set_default_timeout(10000)

        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "CrashReporter")
            # A stored setting, to prove recovery leaves browser storage alone.
            await page.evaluate("() => localStorage.setItem('sketchy_theme', 'dark')")

            await page.evaluate("() => window.__SKETCHY_CRASH__('app')")
            await expect(page.get_by_role("heading", name=HEADING)).to_be_visible()
            await assert_no_axe_violations(page, "crash page")

            # What is listed is what is sent, with the crash first.
            await page.click(".bug-report-context > summary")
            await expect(page.locator(".bug-console-log li").first).to_contain_text(
                "Test crash: app"
            )

            await page.fill(".crash-report textarea", f"I was opening the lobby. {marker}")
            await page.click('.crash-report button[type="submit"]')
            await expect(page.locator(".crash-sent")).to_contain_text("your report is with")

            reports = await filed_reports_mentioning(marker)
            assert len(reports) == 1, [r.summary for r in reports]
            report = reports[0]
            assert report.summary == "Crash on /: Error: Test crash: app"
            assert report.severity == "blocks_play"
            assert report.area == "rooms_and_lobby"
            assert report.route == "/"
            assert report.details.startswith(f"I was opening the lobby. {marker}")
            assert "--- Diagnostic ---" in report.details
            assert "Component tree:" in report.details
            kinds = [entry["kind"] for entry in report.client_context["recentErrors"]]
            assert "render" in kinds, kinds

            # Reload puts the lobby back, and the stored setting is still there.
            await page.get_by_role("button", name="Reload").click()
            await expect(page.get_by_role("button", name="Create room")).to_be_visible()
            assert await page.evaluate("() => localStorage.getItem('sketchy_theme')") == "dark"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_crash_in_the_room_can_leave_it_and_the_seat_goes_too():
    """R-UX-06. The socket outlives the crashed tree, so leaving has to say so.

    Without the `leave_room` in the crash page's way out, the host's seat would
    stay in the guest's player list for as long as the tab lived.
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host = await host_context.new_page()
        guest = await guest_context.new_page()
        host.set_default_timeout(10000)
        guest.set_default_timeout(10000)

        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "CrashHost")
            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "CrashGuest")
            await join_by_code(guest, code)
            await guest.wait_for_selector('[data-testid="waiting-room"]')
            host_seat = guest.locator(".player-name .colored-player-name", has_text="CrashHost")
            await expect(host_seat).to_be_visible()

            await host.evaluate("() => window.__SKETCHY_CRASH__('room')")
            await expect(host.get_by_role("heading", name=HEADING)).to_be_visible()

            await host.get_by_role("button", name="Back to lobby").click()
            await host.wait_for_url(f"{BASE_URL}/")
            await expect(host.get_by_role("button", name="Create room")).to_be_visible()
            await expect(host_seat).to_have_count(0)
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_reloading_after_a_room_crash_keeps_the_seat():
    """R-UX-06. Reload is the way back *into* the room, not out of it.

    The socket drops, the server holds the seat through its disconnect grace,
    and the page that loads rejoins it from the URL.
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host = await host_context.new_page()
        guest = await guest_context.new_page()
        host.set_default_timeout(10000)
        guest.set_default_timeout(10000)

        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "ReloadingHost")
            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "ReloadingGuest")
            await join_by_code(guest, code)
            await guest.wait_for_selector('[data-testid="waiting-room"]')

            await host.evaluate("() => window.__SKETCHY_CRASH__('room')")
            await expect(host.get_by_role("heading", name=HEADING)).to_be_visible()

            await host.get_by_role("button", name="Reload").click()
            await host.wait_for_selector('[data-testid="waiting-room"]')
            assert await room_code(host) == code
            await expect(
                guest.locator(".player-name .colored-player-name", has_text="ReloadingHost")
            ).to_be_visible()
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()
