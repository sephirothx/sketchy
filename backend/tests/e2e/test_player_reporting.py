"""Reporting somebody, from the room to the moderator's queue.

The whole path in one test, because every piece of it existed separately and
none of them were joined: the endpoint shipped under #340, the client function
sat with no caller, and the review queue could only ever be empty.
"""
import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import register_account, use_guest_name


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_a_player_reports_another_from_the_room_menu():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        host_page = await host_context.new_page()
        player_page = await player_context.new_page()
        host_page.set_default_timeout(10000)
        player_page.set_default_timeout(10000)

        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "ReportingHost")
            # Reporting needs an account: a report a moderator cannot follow up
            # on helps nobody, so the control is not offered to a guest.
            await register_account(host_page, "ReportingHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')

            code_text = await host_page.inner_text(".room-copy-button")
            code = code_text.split("Code:")[1].strip()
            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "ReportedPlayer")
            await player_page.fill('input[placeholder="ABC123"]', code)
            await player_page.click('button:has-text("Join by code")')
            await player_page.wait_for_selector('[data-testid="waiting-room"]')

            # In a game, not a waiting room: the game layout is the stacking
            # context the dialog has to escape.
            await host_page.wait_for_selector('.waiting-start-button:not([disabled])')
            await host_page.click(".waiting-start-button")
            await host_page.wait_for_selector(".game-layout")
            await player_page.wait_for_selector(".game-layout")

            row = host_page.locator(".player-list li", has_text="ReportedPlayer")
            await row.wait_for()
            # One line per player. Reporting shares the menu the votes already
            # use rather than costing every row a second row of its own.
            assert await row.locator(".player-report-button").count() == 0

            await row.locator(".player-moderation-trigger").click()
            menu = host_page.locator(".player-vote-menu")
            await menu.wait_for(state="visible")
            # Report sits with the votes rather than on a row of its own.
            # Rendered uppercase by the stylesheet the votes already use.
            kinds = await menu.locator(".player-vote-action-kind").all_inner_texts()
            assert kinds[-1] == "REPORT"
            assert "KICK" in kinds

            await menu.get_by_role("menuitem", name="Report").click()
            dialog = host_page.locator(".modal-card").filter(has_text="Report")
            await dialog.wait_for(state="visible")

            # It drew beneath the game once: the player list is deep inside the
            # game layout, and a dialog rendered in place is trapped in that
            # stacking context. Portalled out, so its parent is the body and
            # nothing in the game can be painted over it.
            assert await host_page.evaluate(
                """() => {
                    const overlay = document.querySelector('.report-player-overlay');
                    return overlay?.parentElement === document.body;
                }"""
            )
            # The point of the z-index, checked where it matters: whatever the
            # browser would hand a click at the middle of the dialog has to be
            # the dialog.
            assert await host_page.evaluate(
                """() => {
                    const card = document.querySelector('.report-player-overlay .modal-card');
                    const box = card.getBoundingClientRect();
                    const hit = document.elementFromPoint(
                        box.left + box.width / 2,
                        box.top + box.height / 2,
                    );
                    return card.contains(hit);
                }"""
            )

            await dialog.locator("textarea").fill("Said something worth reviewing.")
            await dialog.get_by_role("button", name="Send report").click()

            await host_page.wait_for_selector(
                '.modal-card:has-text("Report sent")'
            )
        finally:
            await host_context.close()
            await player_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_a_guest_votes_but_is_offered_no_way_to_report():
    """The server refuses a guest's report, so offering the control is a dead
    end. The votes stay, because those need no account."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        host_page = await host_context.new_page()
        player_page = await player_context.new_page()
        host_page.set_default_timeout(10000)
        player_page.set_default_timeout(10000)

        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "GuestHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')

            code_text = await host_page.inner_text(".room-copy-button")
            code = code_text.split("Code:")[1].strip()
            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "GuestOther")
            await player_page.fill('input[placeholder="ABC123"]', code)
            await player_page.click('button:has-text("Join by code")')
            await player_page.wait_for_selector('[data-testid="waiting-room"]')

            # Started, so that kick and AFK are on offer and their absence
            # cannot be what this test accidentally proves.
            await host_page.wait_for_selector('.waiting-start-button:not([disabled])')
            await host_page.click(".waiting-start-button")
            await host_page.wait_for_selector(".game-layout")
            await player_page.wait_for_selector(".game-layout")

            row = host_page.locator(".player-list li", has_text="GuestOther")
            await row.wait_for()
            await row.locator(".player-moderation-trigger").click()
            menu = host_page.locator(".player-vote-menu")
            await menu.wait_for(state="visible")

            kinds = await menu.locator(".player-vote-action-kind").all_inner_texts()
            assert "KICK" in kinds
            assert "REPORT" not in kinds
        finally:
            await host_context.close()
            await player_context.close()
            await browser.close()
