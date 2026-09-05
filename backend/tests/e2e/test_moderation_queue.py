"""The moderator's side of a report that carries a drawing, and the way back
to cases already decided.

The report is filed the way a player files it - from the room, about the seat
holding the pen - so what the queue shows is what that path stored, not a row
planted for the page.
"""
import asyncio
import os

import pytest
from playwright.async_api import async_playwright
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import User
from app.domain_values import UserRole
from tests.e2e.lobby_helpers import join_by_code, register_account, room_code, use_guest_name


BASE_URL = "http://localhost:8000"


async def set_role(username: str, role: str) -> None:
    url = os.environ.get("SKETCHY_E2E_DATABASE_URL")
    if not url:
        pytest.skip("SKETCHY_E2E_DATABASE_URL is not set; run via scripts/test-e2e.sh")
    engine = create_async_engine(url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(User).where(User.username == username).values(role=role)
                )
    finally:
        await engine.dispose()


async def _choose_prompt(pages):
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
async def test_a_moderator_sees_the_drawing_and_can_find_the_case_once_decided():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context() for _ in range(3)]
        host_page, player_page, moderator_page = [
            await context.new_page() for context in contexts
        ]
        for page in (host_page, player_page, moderator_page):
            page.set_default_timeout(10000)

        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "QueueHost")
            await register_account(host_page, "QueueHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host_page)

            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "QueueOther")
            await register_account(player_page, "QueueOther")
            await join_by_code(player_page, code)
            await player_page.wait_for_selector('[data-testid="waiting-room"]')

            await host_page.wait_for_selector('.waiting-start-button:not([disabled])')
            await host_page.click(".waiting-start-button")
            await host_page.wait_for_selector(".game-layout")
            await player_page.wait_for_selector(".game-layout")

            names = {host_page: "QueueHost", player_page: "QueueOther"}
            drawer, guesser = await _choose_prompt([host_page, player_page])
            canvas = drawer.locator("canvas.drawing-canvas")
            box = await canvas.bounding_box()
            await drawer.mouse.move(box["x"] + 80, box["y"] + 80)
            await drawer.mouse.down()
            await drawer.mouse.move(box["x"] + 260, box["y"] + 200)
            await drawer.mouse.up()

            row = guesser.locator(".player-list li", has_text=names[drawer])
            await row.locator(".player-moderation-trigger").click()
            await guesser.locator(".player-vote-menu").get_by_role(
                "menuitem", name="Report"
            ).click()
            dialog = guesser.locator(".modal-card").filter(has_text="Report")
            await dialog.wait_for(state="visible")
            assert await dialog.get_by_label("Include their drawing").is_checked()
            await dialog.locator("textarea").fill("Not what the prompt asked for.")
            await dialog.get_by_role("button", name="Send report").click()
            await guesser.wait_for_selector('.modal-card:has-text("with their drawing")')

            # The moderator: made staff in the database the way every other
            # end-to-end test does, then arriving at the queue afresh.
            await moderator_page.goto(BASE_URL)
            await use_guest_name(moderator_page, "QueueModerator")
            await register_account(moderator_page, "QueueModerator")
            await set_role("QueueModerator", UserRole.MODERATOR.value)
            await moderator_page.goto(f"{BASE_URL}/moderation")

            case = moderator_page.locator(".mod-queue-item", has_text="Offensive drawing")
            await case.wait_for()
            await case.click()
            figure = moderator_page.locator('[data-testid="mod-drawing"]')
            await figure.wait_for()
            # Decoded and drawn, not described: the same canvas element the
            # room uses, from the stored frame.
            await figure.locator("canvas").wait_for()
            caption = await figure.locator("figcaption").inner_text()
            assert "They were asked to draw" in caption
            assert "1 action" in caption

            # Decide it, then find it again under Closed.
            await moderator_page.locator(".mod-note textarea").fill("Looked, and it was fine.")
            # Scoped to the case's own actions: the email reminder banner
            # carries a Dismiss of its own.
            await moderator_page.locator(".mod-actions").get_by_role(
                "button", name="Dismiss"
            ).click()
            await moderator_page.wait_for_selector('[role="status"]:has-text("Dismissed.")')
            # The status lands before the queue is fetched again, so the row
            # leaves a moment later rather than at once.
            await case.wait_for(state="detached")

            await moderator_page.get_by_role("button", name="Closed").click()
            closed = moderator_page.locator(".mod-queue-item", has_text="Offensive drawing")
            await closed.wait_for()
            await closed.click()
            await moderator_page.locator('[data-testid="mod-drawing"] canvas').wait_for()
            # The decision, not only its note: what was done, by whom, when.
            decision = moderator_page.locator('[data-testid="mod-decision"]')
            await decision.wait_for()
            assert await decision.locator(".chip", has_text="Dismissed").count() == 1
            assert "By QueueModerator" in await decision.inner_text()
            assert await decision.locator(
                ".mod-resolution", has_text="Looked, and it was fine."
            ).count() == 1
            # The chip sits beside the case in the list as well.
            assert await closed.locator(".chip", has_text="Dismissed").count() == 1
            # The one page there is: nothing newer, nothing older.
            pager = moderator_page.get_by_role("navigation", name="Closed cases pages")
            await pager.wait_for()
            assert await pager.get_by_role("button", name="Newer").is_disabled()
            assert await pager.get_by_role("button", name="Older").is_disabled()
        finally:
            for context in contexts:
                await context.close()
            await browser.close()
