"""Dialogs opened on demand are fetched on demand, and a fetch that fails is
a notice rather than the crash page (#1257).

Seven dialogs used to ride in the first-load chunk - which has a CI budget -
for players who never open them. They load themselves now (`lazyOverlay`),
so a chunk that cannot be fetched, over a live room, has to leave the room
standing and say so; and each still has to open when its chunk arrives.
"""
from __future__ import annotations

from uuid import uuid4

from playwright.async_api import async_playwright, expect

from tests.e2e.lobby_helpers import (
    BASE_URL,
    join_by_code,
    open_new_room,
    register_account,
    room_code,
    use_guest_name,
)
from tests.e2e.test_friends import open_row_menu


async def test_a_dialog_whose_chunk_will_not_load_is_a_notice_over_the_room():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host = await host_context.new_page()
        guest = await guest_context.new_page()
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, f"LazyHost{uuid4().hex[:4]}")
            await open_new_room(host)
            code = await room_code(host)
            await guest.goto(BASE_URL)
            await use_guest_name(guest, f"LazyGuest{uuid4().hex[:4]}")
            await join_by_code(guest, code)
            await guest.wait_for_selector('[data-testid="waiting-room"]')

            # The connection drops just as the dialog is asked for.
            await guest.route("**/assets/BugReportDialog-*.js", lambda route: route.abort())
            await guest.click('[data-testid="room-header"] .identity-chip')
            await guest.locator(".account-dropdown").wait_for(state="visible")
            await guest.click('button:has-text("Report a bug")')

            notice = guest.locator(".lazy-overlay-notice[role=alert]")
            await expect(notice).to_be_visible()
            await expect(notice.get_by_role("button", name="Try again")).to_be_visible()
            assert await guest.locator(".crash-page").count() == 0
            assert await guest.locator('[data-testid="waiting-room"]').count() == 1, "the room is still there"
            assert await guest.locator(".bug-report-dialog").count() == 0
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()


async def test_the_report_account_dialog_arrives_when_asked_for():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        reporter_context = await browser.new_context()
        subject_context = await browser.new_context()
        reporter = await reporter_context.new_page()
        subject = await subject_context.new_page()
        run = uuid4().hex[:6]
        try:
            await subject.goto(BASE_URL)
            await use_guest_name(subject, f"Lazysub{run}")
            await register_account(subject, f"lazysub{run}")
            await reporter.goto(BASE_URL)
            await use_guest_name(reporter, f"Lazyrep{run}")
            await register_account(reporter, f"lazyrep{run}")

            fetched: list[str] = []
            reporter.on("request", lambda request: fetched.append(request.url))
            menu = await open_row_menu(reporter, f"lazysub{run}")
            assert not [url for url in fetched if "ReportAccountDialog" in url], "fetched before it was asked for"
            await menu.get_by_role("menuitem", name="Report").click()
            await expect(reporter.get_by_role("dialog", name=f"Report lazysub{run}")).to_be_visible()
            assert [url for url in fetched if "ReportAccountDialog" in url], "its chunk came when it was asked for"
        finally:
            await reporter_context.close()
            await subject_context.close()
            await browser.close()
