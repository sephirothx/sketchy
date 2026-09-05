"""Reporting somebody, from the room to the moderator's queue.

The whole path in one test, because every piece of it existed separately and
none of them were joined: the endpoint shipped under #340, the client function
sat with no caller, and the review queue could only ever be empty.
"""
import asyncio

import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import join_by_code, register_account, room_code, use_guest_name


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

            code = await room_code(host_page)
            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "ReportedPlayer")
            await join_by_code(player_page, code)
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

            code = await room_code(host_page)
            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "GuestOther")
            await join_by_code(player_page, code)
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


async def _choose_prompt(pages):
    """Wait for whichever page was dealt the prompt choices, pick one, and
    hand back (drawer, guesser)."""
    for _ in range(120):
        for page in pages:
            if await page.locator(".prompt-choices").count():
                drawer = page
                guesser = pages[1] if page is pages[0] else pages[0]
                await drawer.locator(".prompt-choices button").first.click()
                await drawer.locator(".prompt-choices").wait_for(state="detached")
                await drawer.locator("canvas.drawing-canvas").wait_for()
                return drawer, guesser
        await asyncio.sleep(0.1)
    raise AssertionError("No drawer received prompt choices within 12 seconds")


@pytest.mark.asyncio
async def test_a_report_about_the_drawer_carries_the_drawing():
    """Mid-turn, a report about the player drawing offers to include the
    canvas, on by default, and the confirmation says it went. A report about
    a guesser offers nothing of the kind: there is nothing on the canvas that
    is theirs."""
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
            await use_guest_name(host_page, "DrawReportHost")
            await register_account(host_page, "DrawReportHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')

            code = await room_code(host_page)
            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "DrawReportOther")
            # Either seat may be dealt the pen first, so both need an account
            # to report from.
            await register_account(player_page, "DrawReportOther")
            await join_by_code(player_page, code)
            await player_page.wait_for_selector('[data-testid="waiting-room"]')

            await host_page.wait_for_selector('.waiting-start-button:not([disabled])')
            await host_page.click(".waiting-start-button")
            await host_page.wait_for_selector(".game-layout")
            await player_page.wait_for_selector(".game-layout")

            names = {host_page: "DrawReportHost", player_page: "DrawReportOther"}
            drawer, guesser = await _choose_prompt([host_page, player_page])

            # Something on the canvas, so the frame that goes is a drawing.
            canvas = drawer.locator("canvas.drawing-canvas")
            box = await canvas.bounding_box()
            await drawer.mouse.move(box["x"] + 100, box["y"] + 100)
            await drawer.mouse.down()
            await drawer.mouse.move(box["x"] + 220, box["y"] + 210)
            await drawer.mouse.up()

            async def open_report(page, about: str):
                row = page.locator(".player-list li", has_text=about)
                await row.wait_for()
                await row.locator(".player-moderation-trigger").click()
                menu = page.locator(".player-vote-menu")
                await menu.wait_for(state="visible")
                await menu.get_by_role("menuitem", name="Report").click()
                dialog = page.locator(".modal-card").filter(has_text="Report")
                await dialog.wait_for(state="visible")
                return dialog

            # The drawer reporting a guesser is offered no drawing.
            dialog = await open_report(drawer, names[guesser])
            assert await dialog.get_by_label("Include their drawing").count() == 0
            await dialog.get_by_role("button", name="Cancel").click()
            await dialog.wait_for(state="hidden")

            # The guesser reporting the drawer is, and it is on by default,
            # with the reason already set to the drawing.
            dialog = await open_report(guesser, names[drawer])
            include = dialog.get_by_label("Include their drawing")
            await include.wait_for()
            assert await include.is_checked()
            assert await dialog.locator("select").input_value() == "offensive_drawing"
            # Nothing typed: the drawing is the complaint, and the details
            # are optional wherever the server attaches the evidence itself.
            await dialog.get_by_role("button", name="Send report").click()

            sent = guesser.locator('.modal-card:has-text("Report sent")')
            await sent.wait_for()
            assert "with their drawing" in await sent.inner_text()
        finally:
            await host_context.close()
            await player_context.close()
            await browser.close()
