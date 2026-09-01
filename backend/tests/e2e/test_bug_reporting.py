"""Filing a bug from the account menu, and reading it in the admin queue.

The whole path in one test, because the halves are only correct together: what
the dialog gathers is what triage has to work from, and a diagnostics block that
looks right in the dialog but arrives empty is exactly the failure a unit test
on either side would miss.
"""
import os

import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import BugReport, User
from app.domain_values import UserRole
from tests.e2e.lobby_helpers import register_account, room_code, use_guest_name


BASE_URL = "http://localhost:8000"


async def promote_to_admin(username: str) -> None:
    """Make one account staff, through the same database the server uses.

    The URL comes from the runner rather than being guessed: the suite gets a
    throwaway database per run, and a test that wrote to the developer's own
    would be a nasty surprise.
    """
    url = os.environ.get("SKETCHY_E2E_DATABASE_URL")
    if not url:
        pytest.skip("SKETCHY_E2E_DATABASE_URL is not set; run via scripts/test-e2e.sh")
    engine = create_async_engine(url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(User)
                    .where(User.username == username)
                    .values(role=UserRole.ADMIN.value)
                )
    finally:
        await engine.dispose()


async def open_bug_dialog(page) -> None:
    await page.click(".account-menu button")
    await page.click('button:has-text("Report a bug")')
    await page.wait_for_selector(".bug-report-dialog")


@pytest.mark.asyncio
async def test_a_guest_files_a_bug_and_an_admin_reads_it():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        guest_context = await browser.new_context()
        admin_context = await browser.new_context()
        guest_page = await guest_context.new_page()
        admin_page = await admin_context.new_page()
        guest_page.set_default_timeout(10000)
        admin_page.set_default_timeout(10000)

        try:
            await guest_page.goto(BASE_URL)
            # A guest, deliberately: the bugs that go unreported are the ones
            # met before anybody has made an account.
            await use_guest_name(guest_page, "BugFilingGuest")
            await open_bug_dialog(guest_page)

            # The diagnostics are shown, not merely mentioned. Opening the
            # disclosure is the honest version of "some technical details".
            await guest_page.click('.bug-report-context > summary')
            context_rows = guest_page.locator(".bug-report-context .bug-context div")
            # Waiting for the fifth is "at least five", and it retries; a bare
            # `count()` reads whatever has rendered by that instant.
            await context_rows.nth(4).wait_for()
            assert await context_rows.count() >= 5

            await guest_page.select_option("select#" + await guest_page.get_attribute(
                ".bug-report-dialog select", "id"
            ), "connection_and_sync")
            await guest_page.fill(
                '.bug-report-dialog input[type="text"]',
                "Reconnect leaves two seats for one player",
            )
            await guest_page.fill(
                ".bug-report-dialog textarea",
                "I refreshed mid-round and my old seat stayed in the player list.",
            )
            await guest_page.click('.bug-report-dialog button[type="submit"]')

            await guest_page.wait_for_selector(".bug-report-dialog", state="detached")
            await guest_page.wait_for_selector(
                'text=Thanks — your report is with the people who run Sketchy.'
            )

            # An ordinary player is not shown the queue, and the route answers
            # the same way to anyone who tries it anyway.
            await guest_page.goto(f"{BASE_URL}/admin/bug-reports")
            await guest_page.wait_for_selector("text=Nobody drew this page")

            await admin_page.goto(BASE_URL)
            await use_guest_name(admin_page, "BugTriageAdmin")
            await register_account(admin_page, "BugTriageAdmin")
            await promote_to_admin("BugTriageAdmin")
            await admin_page.reload()

            await admin_page.goto(f"{BASE_URL}/admin/bug-reports")
            case = admin_page.locator(".mod-case")
            await case.wait_for()
            await admin_page.wait_for_selector(
                'text=Reconnect leaves two seats for one player'
            )
            # Triage leads with the facts it starts from, and everything else
            # is one disclosure away - both halves still labelled for what they
            # are: what the browser said, and what the server saw.
            await admin_page.wait_for_selector("text=Diagnostics")
            # Read as a strip across the width rather than a column down the
            # side, so the decision controls stay on screen.
            cells = admin_page.locator(".bug-diagnostics .bug-diagnostic")
            # The heading above arrives before the cells under it do.
            await cells.nth(7).wait_for()
            assert await cells.count() >= 8
            await cells.locator("dt").nth(7).wait_for()
            assert await cells.locator("dt").count() >= 8
            await admin_page.click('summary:has-text("Everything the client reported")')
            await admin_page.wait_for_selector("text=browser.userAgent")
            await admin_page.click('summary:has-text("Everything the server saw")')
            await admin_page.wait_for_selector("text=account.registered")

            note = admin_page.locator(".mod-note textarea")
            await note.fill("Reproduced; fixed by rebinding the seat on reconnect.")
            await admin_page.click('button:has-text("Resolve")')
            # Deciding is one-way, so the report leaves the open queue.
            await admin_page.wait_for_selector("text=Nothing in this queue.")
        finally:
            await guest_context.close()
            await admin_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_a_guest_in_a_live_game_can_still_reach_the_report_dialog():
    """The compact chip used to skip its menu entirely and open the claim dialog.

    That was right while every guest entry navigated somewhere - following one
    would have given up the seat. Reporting a bug does not navigate, and a guest
    mid-game is exactly who most needs it, so the compact menu is now cut down
    rather than absent.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host_page = await host_context.new_page()
        guest_page = await guest_context.new_page()
        host_page.set_default_timeout(10000)
        guest_page.set_default_timeout(10000)

        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "CompactHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host_page)

            await guest_page.goto(BASE_URL)
            await use_guest_name(guest_page, "CompactGuest")
            await guest_page.fill('input[placeholder="ABC123"]', code)
            await guest_page.click('button:has-text("Join by code")')
            await guest_page.wait_for_selector('[data-testid="waiting-room"]')

            # The compact chip only exists in the game layout.
            await host_page.wait_for_selector('.waiting-start-button:not([disabled])')
            await host_page.click(".waiting-start-button")
            await guest_page.wait_for_selector(".game-layout")

            await guest_page.click(".identity-chip.is-compact")
            menu = guest_page.locator(".account-dropdown")
            await menu.wait_for(state="visible")

            # Cut down, not absent: what is offered keeps them in their seat.
            entries = await menu.locator("button").all_inner_texts()
            assert "Report a bug" in entries
            assert "My profile" not in entries, entries
            assert "Prompt stats" not in entries, entries

            await guest_page.click('button:has-text("Report a bug")')
            await guest_page.wait_for_selector(".bug-report-dialog")
            # Still in the game, seat intact.
            assert await guest_page.locator(".game-layout").count() == 1
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_the_report_carries_what_triage_needs_without_the_prompt():
    """A guesser filing a bug is still a guesser."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(10000)

        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "BugContextGuest")
            await open_bug_dialog(page)
            await page.fill(
                '.bug-report-dialog input[type="text"]', "Canvas went blank"
            )
            await page.fill(
                ".bug-report-dialog textarea", "Everything disappeared mid-stroke."
            )
            await page.click('.bug-report-dialog button[type="submit"]')
            await page.wait_for_selector(".bug-report-dialog", state="detached")

            url = os.environ.get("SKETCHY_E2E_DATABASE_URL")
            if not url:
                pytest.skip("SKETCHY_E2E_DATABASE_URL is not set")
            engine = create_async_engine(url)
            try:
                factory = async_sessionmaker(engine, expire_on_commit=False)
                async with factory() as session:
                    report = await session.scalar(
                        select(BugReport).where(
                            BugReport.summary == "Canvas went blank"
                        )
                    )
                assert report is not None
                context_blob = report.client_context
                # Gathered generously: the reporter gets one shot at describing
                # it, and the missing detail is usually the one nobody asked for.
                assert context_blob["buildSha"]
                assert context_blob["viewport"]["width"] > 0
                assert context_blob["browser"]["userAgent"]
                assert "prefersReducedMotion" in context_blob["preferences"]
                assert "online" in context_blob["connection"]
                assert "uptimeMs" in context_blob["performance"]
                assert report.route == "/"
                # And privately: no query string, no chat, no prompt.
                assert "?" not in (report.route or "")
            finally:
                await engine.dispose()
        finally:
            await context.close()
            await browser.close()
