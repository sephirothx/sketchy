"""The moderator's side of a report that carries a drawing, and the way back
to cases already decided.

The report is filed the way a player files it - from the room, about the seat
holding the pen - so what the queue shows is what that path stored, not a row
planted for the page.
"""
import asyncio

from playwright.async_api import async_playwright

from app.domain_values import UserRole
from tests.e2e.lobby_helpers import join_by_code, register_account, room_code, use_guest_name

# Grants the role *and* the second factor R-AUTH-20 now requires of one.
from tests.e2e.staff_helpers import set_role


BASE_URL = "http://localhost:8000"

#: The details this test's own report carries, and how its case is found.
#:
#: Not the reason: the moderation queue is server-wide, so every report any
#: test in the suite files lands in the same list, and several of them use the
#: reason "Offensive drawing". Filtering on that matched two cases and failed
#: the whole test on a strict-mode violation - a failure that depends on which
#: tests happen to be running beside it, which is the worst kind to debug.
#: The details are this test's own sentence, so they name its case and nobody
#: else's.
DETAILS = "Not what the prompt asked for."


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
            await dialog.locator("textarea").fill(DETAILS)
            await dialog.get_by_role("button", name="Send report").click()
            await guesser.wait_for_selector('.modal-card:has-text("with their drawing")')

            # The moderator: made staff in the database the way every other
            # end-to-end test does, then arriving at the queue afresh.
            await moderator_page.goto(BASE_URL)
            await use_guest_name(moderator_page, "QueueModerator")
            await register_account(moderator_page, "QueueModerator")
            await set_role("QueueModerator", UserRole.MODERATOR.value)
            await moderator_page.goto(f"{BASE_URL}/moderation")

            # The queue shows incidents now: an entry carries the player it
            # is about and the reasons given, never a report's own words. So
            # it is found by this test's own player rather than by a reason
            # several of the suite's tests share.
            case = moderator_page.locator(".mod-queue-item", has_text=names[drawer])
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
            closed = moderator_page.locator(".mod-queue-item", has_text=names[drawer])
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


async def test_two_players_reporting_one_thing_are_one_case_decided_once():
    """The whole point of grouping, played out (#620).

    Two players in one room report the same person for the same thing. The
    moderator gets one entry saying two people complained, both complaints in
    their own words, one merged thread, and one Dismiss that leaves nothing
    behind - not one entry dealt with and another still waiting.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context() for _ in range(4)]
        host_page, first_page, second_page, moderator_page = [
            await context.new_page() for context in contexts
        ]
        for page in (host_page, first_page, second_page, moderator_page):
            page.set_default_timeout(10000)

        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "PileHost")
            await register_account(host_page, "PileHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host_page)

            for page, name in ((first_page, "PileOne"), (second_page, "PileTwo")):
                await page.goto(BASE_URL)
                await use_guest_name(page, name)
                await register_account(page, name)
                await join_by_code(page, code)
                await page.wait_for_selector('[data-testid="waiting-room"]')

            await host_page.wait_for_selector('.waiting-start-button:not([disabled])')
            await host_page.click(".waiting-start-button")
            for page in (host_page, first_page, second_page):
                await page.wait_for_selector(".game-layout")

            # Whoever draws is who the other two complain about, so the two
            # reports are about one seat in one room - one incident.
            pages = [host_page, first_page, second_page]
            names = {host_page: "PileHost", first_page: "PileOne", second_page: "PileTwo"}
            drawer = None
            for _ in range(120):
                for page in pages:
                    if await page.locator(".prompt-choices").count():
                        drawer = page
                        break
                if drawer:
                    break
                await asyncio.sleep(0.1)
            assert drawer is not None, "no drawer received prompt choices"
            await drawer.locator(".prompt-choices button").first.click()
            await drawer.locator("canvas.drawing-canvas").wait_for()
            reporters = [page for page in pages if page is not drawer]

            for index, reporter in enumerate(reporters):
                row = reporter.locator(".player-list li", has_text=names[drawer])
                await row.locator(".player-moderation-trigger").click()
                await reporter.locator(".player-vote-menu").get_by_role(
                    "menuitem", name="Report"
                ).click()
                dialog = reporter.locator(".modal-card").filter(has_text="Report")
                await dialog.wait_for(state="visible")
                await dialog.locator("textarea").fill(
                    f"Complaint number {index + 1}, in my own words."
                )
                await dialog.get_by_role("button", name="Send report").click()
                await reporter.wait_for_selector('.modal-card:has-text("Sent,")')

            await moderator_page.goto(BASE_URL)
            await use_guest_name(moderator_page, "PileMod")
            await register_account(moderator_page, "PileMod")
            await set_role("PileMod", UserRole.MODERATOR.value)
            await moderator_page.goto(f"{BASE_URL}/moderation")

            # One entry, not two, and it says how many complained.
            case = moderator_page.locator(".mod-queue-item", has_text=names[drawer])
            await case.wait_for()
            # One entry for this drawer, not two: the queue is shared with the
            # other tests on this server, so it is this player's entries that
            # are counted.
            assert await case.count() == 1
            assert await case.locator(".chip", has_text="2 reporters").count() == 1
            await case.click()

            # Both complaints, each in its reporter's own words.
            reporters_panel = moderator_page.locator('[data-testid="mod-reporters"]')
            await reporters_panel.wait_for()
            assert await reporters_panel.locator("li").count() == 2
            panel_text = await reporters_panel.inner_text()
            assert "Complaint number 1, in my own words." in panel_text
            assert "Complaint number 2, in my own words." in panel_text

            # And the decision says what it will close before it is taken.
            scope = moderator_page.locator('[data-testid="mod-decision-scope"]')
            await scope.wait_for()
            assert "all 2 complaints" in await scope.inner_text()

            await moderator_page.locator(".mod-note textarea").fill(
                "Spoke to them; nothing further."
            )
            await moderator_page.locator(".mod-actions").get_by_role(
                "button", name="Dismiss"
            ).click()
            await moderator_page.wait_for_selector(
                '[role="status"]:has-text("Dismissed.")'
            )
            await case.wait_for(state="detached")

            # One decision took both complaints with it: nothing about this
            # player is left waiting.
            assert await case.count() == 0

            # The same room, the same player, complained about again. R-MOD-05
            # lets a reporter raise a new one once the first is decided, and
            # R-MOD-07 keeps the decided case closed - so this opens a *new*
            # incident, which must not arrive looking untouched (R-MOD-18).
            repeat_reporter = reporters[0]
            # Their first report's acknowledgement is still up, and it sits
            # over the player list the next one is opened from.
            await repeat_reporter.locator(
                ".modal-card .modal-dismiss"
            ).click()
            await repeat_reporter.locator(".modal-card").wait_for(state="detached")
            row = repeat_reporter.locator(".player-list li", has_text=names[drawer])
            await row.locator(".player-moderation-trigger").click()
            await repeat_reporter.locator(".player-vote-menu").get_by_role(
                "menuitem", name="Report"
            ).click()
            dialog = repeat_reporter.locator(".modal-card").filter(has_text="Report")
            await dialog.wait_for(state="visible")
            await dialog.locator("textarea").fill("They are at it again.")
            await dialog.get_by_role("button", name="Send report").click()
            await repeat_reporter.wait_for_selector('.modal-card:has-text("Sent,")')

            await moderator_page.reload()
            repeat_case = moderator_page.locator(
                ".mod-queue-item", has_text=names[drawer]
            )
            await repeat_case.wait_for()
            await repeat_case.click()

            banner = moderator_page.locator('[data-testid="mod-prior-decision"]')
            await banner.wait_for()
            banner_text = await banner.inner_text()
            assert "decided before" in banner_text
            assert "PileMod" in banner_text
            # The note the earlier decision was required to carry, shown to
            # the reader it was written for.
            assert "Spoke to them; nothing further." in banner_text

            # And the ending a repeat usually has, one press away - with no
            # note to type, because the case above is the note.
            await moderator_page.locator(
                '[data-testid="mod-prior-dismiss"]'
            ).click()
            await moderator_page.wait_for_selector(
                '[role="status"]:has-text("Dismissed, as already decided.")'
            )
            await repeat_case.wait_for(state="detached")

            # Closed, carrying what it deferred to rather than a bare word.
            await moderator_page.locator(
                ".mod-filter-pill", has_text="Closed"
            ).click()
            closed = moderator_page.locator(
                ".mod-queue-item", has_text=names[drawer]
            ).first
            await closed.wait_for()
            await closed.click()
            resolution = moderator_page.locator(".mod-resolution").first
            await resolution.wait_for()
            assert "Already dismissed" in await resolution.inner_text()
        finally:
            for context in contexts:
                await context.close()
            await browser.close()
