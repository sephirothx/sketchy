"""Solo (#1434) end to end: the Daily and a free run, played in the browser.

The drawings are written straight into the server's database as finished
public games, with prompts from the official lists the server seeds - what
matters is that Solo serves them, not how a test could draw them. A player
names the first Daily drawing (the prompt read back from their own serve,
since play is local and the answer never shows), misses one with a wrong
guess and gives it up, reloads mid-Daily and carries on where they were,
finishes it, and then plays a five-drawing free run. The page also has to
hold together at phone width, and a guest is told what an account unlocks.
A past day picked in the calendar (#1470) is played late, and then, finished,
opens as a review of its five.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from playwright.async_api import Page, async_playwright, expect
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import (
    Prompt,
    PromptList,
    PromptVersion,
    SoloDailyConcept,
    SoloDailyDay,
    SoloDailySet,
    SoloServe,
    TurnDrawing,
    User,
)
from app.domain_values import PROMPT_LANGUAGES
from app.repositories.solo import daily_set, ensure_open_dailies
from app.solo_rules import DAILY_LENGTH, open_dates
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    TurnDrawingInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import SqlAlchemyGameHistoryRepository, SqlAlchemyUserRepository
from tests.e2e.lobby_helpers import (
    BASE_URL,
    answer_play_languages_question,
    register_account,
    use_guest_name,
)
from tests.e2e.staff_helpers import database_url

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "fill_replay_100.json"

# Every date open somewhere takes its own five the first time anything asks
# for one - a free run asks for them all - and two or three are open at any
# moment. Enough for all of them, wherever the pool stood.
OPEN_DAILIES_DRAWINGS = 3 * DAILY_LENGTH


async def seed_solo_drawings(count: int, *, finished: datetime | None = None) -> None:
    """`count` public games of one curated turn each, every language able
    to name it, two guessers and one of them right: Daily candidates, and
    free-run drawings for anybody who was not in them. Each of a concept no
    Daily has held, so the sixty-day rule cannot leave one of them out."""
    engine = create_async_engine(database_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            every_language = (
                select(PromptVersion.concept_id)
                .where(PromptVersion.language.in_(PROMPT_LANGUAGES))
                .group_by(PromptVersion.concept_id)
                .having(func.count(func.distinct(PromptVersion.language)) == len(PROMPT_LANGUAGES))
            )
            versions = (
                await session.scalars(
                    select(PromptVersion.id)
                    .join(Prompt, Prompt.prompt_version_id == PromptVersion.id)
                    .join(PromptList, PromptList.id == Prompt.prompt_list_id)
                    .where(
                        PromptList.is_bundled.is_(True),
                        PromptVersion.language == "en",
                        PromptVersion.content_rating == "everyone",
                        PromptVersion.moderation_state == "active",
                        PromptVersion.concept_id.in_(every_language),
                        PromptVersion.concept_id.not_in(select(SoloDailyConcept.concept_id)),
                    )
                    .order_by(func.random())
                    .limit(count * 3)
                )
            ).all()
            # One a concept: two lists can carry the same one.
            concepts = {
                version.id: version.concept_id
                for version in (
                    await session.scalars(select(PromptVersion).where(PromptVersion.id.in_(versions)))
                ).all()
            }
        versions = list({concepts[version]: version for version in versions}.values())[:count]
        assert len(versions) == count, "the official lists have too few eight-language prompts"
        users = SqlAlchemyUserRepository(factory)
        history = SqlAlchemyGameHistoryRepository(factory)
        payload = base64.b64decode(json.loads(FIXTURE.read_text())["base64"])
        tag = uuid4().hex[:4]
        drawer = await users.create_anonymous(f"SoloDrawer{tag}")
        guessers = [await users.create_anonymous(f"SoloSeat{tag}{i}") for i in range(2)]
        finished = finished or datetime.now(timezone.utc) - timedelta(hours=2)
        for version_id in versions:
            seats = [str(uuid4()) for _ in range(3)]
            turn_id = str(uuid4())
            await history.save_game(
                GameRecordInput(
                    room_name="Solo source", scoring_mode="none", hint_mode="none",
                    drawing_seconds=80, total_rounds=1, player_count=3,
                    started_at=finished - timedelta(minutes=3), finished_at=finished,
                    visibility="public",
                ),
                [
                    GameParticipantInput(
                        user_id=user.id, final_score=0, final_rank=1, seat_id=seat,
                        display_name=user.display_name,
                    )
                    for user, seat in zip([drawer, *guessers], seats, strict=True)
                ],
                [
                    TurnRecordInput(
                        id=turn_id, round_number=1, turn_number=1, drawer_user_id=drawer.id,
                        drawer_seat_id=seats[0], prompt="seeded", duration_seconds=40,
                        prompt_version_id=str(version_id), prompt_source_kind="curated",
                        guesser_count=2, stroke_count=100,
                        participant_outcomes=tuple(
                            TurnParticipantOutcomeInput(
                                seat_id=seat, user_id=user.id, eligible=True,
                                eligibility_reason="eligible",
                                outcome="correct" if index == 0 else "incorrect",
                                terminal_state="active",
                                correct_guess_time_seconds=12.0 if index == 0 else None,
                                points_awarded=0 if index == 0 else None,
                            )
                            for index, (user, seat) in enumerate(zip(guessers, seats[1:], strict=True))
                        ),
                    )
                ],
                None,
                [TurnDrawingInput(turn_id=turn_id, payload=payload)],
            )
    finally:
        await engine.dispose()


async def settle_open_dailies() -> None:
    """Give every date open somewhere its Daily now, as the server would,
    before a test asks for one: left to whichever test asks first, one date
    could take the drawings another test seeded for today, leaving today
    with too few - stored as skipped for minutes - or take a past Daily's
    before it is opened. A date stored with no Daily is looked at again
    first: nobody can have played it."""
    engine = create_async_engine(database_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        async with factory() as session, session.begin():
            await session.execute(
                delete(SoloDailyDay).where(
                    SoloDailyDay.daily_date.in_(open_dates(now)), SoloDailyDay.state == "skipped"
                )
            )
        await ensure_open_dailies(factory, now)
        async with factory() as session:
            states = (
                await session.scalars(
                    select(SoloDailyDay.state).where(SoloDailyDay.daily_date.in_(open_dates(now)))
                )
            ).all()
        assert states == ["set"] * len(open_dates(now)), "too few drawings for the open Dailies"
    finally:
        await engine.dispose()


async def open_prompt(username: str) -> str:
    """The prompt of the player's drawing in play: the server keeps it on the
    serve, the page never shows it until the drawing is over."""
    engine = create_async_engine(database_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            user_id = await session.scalar(select(User.id).where(User.username == username))
            return await session.scalar(
                select(SoloServe.prompt)
                .where(SoloServe.user_id == UUID(str(user_id)), SoloServe.settled_at.is_(None))
                .order_by(SoloServe.served_at, SoloServe.position)
                .limit(1)
            )
    finally:
        await engine.dispose()


async def give_up_and_continue(page: Page) -> None:
    await page.get_by_test_id("solo-canvas").locator("canvas").wait_for()
    await page.get_by_test_id("solo-give-up").click()
    await expect(page.get_by_test_id("solo-card")).to_be_visible()
    await page.get_by_test_id("solo-next").click()


async def test_a_daily_and_a_free_run_are_played_through():
    # One more than the open Dailies can hold, for the free run - which
    # never serves an open Daily's concept.
    await seed_solo_drawings(OPEN_DAILIES_DRAWINGS + 1)
    await settle_open_dailies()
    username = f"solo{uuid4().hex[:8]}"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, username.capitalize())
            await register_account(page, username)

            # The lobby and the bar both lead here.
            await page.get_by_test_id("lobby-solo").click()
            await page.wait_for_url(f"{BASE_URL}/solo")
            await expect(page.get_by_role("navigation", name="Pages").get_by_role("link", name="Solo")).to_have_attribute(
                "aria-current", "page"
            )

            await page.get_by_test_id("solo-play-daily").click()
            await expect(page.get_by_text("Drawing 1 of 5")).to_be_visible()
            await page.get_by_test_id("solo-canvas").locator("canvas").wait_for()
            # The answer is nowhere on the page while the drawing is in play.
            prompt = await open_prompt(username)
            assert prompt and prompt not in await page.locator("body").inner_text()
            await page.get_by_test_id("solo-guess").fill(prompt)
            await page.get_by_test_id("solo-guess").press("Enter")
            await expect(page.get_by_test_id("solo-verdict")).to_have_text("You got it!")
            await expect(page.get_by_test_id("solo-prompt")).to_have_text(prompt)
            await expect(page.get_by_test_id("solo-points")).to_contain_text("points")
            # The drawing stays on screen, finished, under what it was.
            await page.get_by_test_id("solo-card-drawing").locator("canvas").wait_for()
            await page.get_by_test_id("solo-next").click()

            # A wrong guess is not a miss: the clock runs on.
            await expect(page.get_by_text("Drawing 2 of 5")).to_be_visible()
            await page.get_by_test_id("solo-canvas").locator("canvas").wait_for()
            await page.get_by_test_id("solo-guess").fill("zzqqxx")
            await page.get_by_test_id("solo-guess").press("Enter")
            await expect(page.get_by_test_id("solo-feedback")).to_contain_text("zzqqxx")
            await expect(page.get_by_text("Drawing 2 of 5")).to_be_visible()

            # A reload mid-Daily resumes it where it was, its clock carrying on
            # rather than starting again.
            await page.wait_for_timeout(2500)
            await page.reload()
            await page.get_by_test_id("solo-play-daily").click()
            await expect(page.get_by_text("Drawing 2 of 5")).to_be_visible()
            await page.get_by_test_id("solo-canvas").locator("canvas").wait_for()
            left = int((await page.get_by_test_id("solo-clock").inner_text()).split()[0])
            assert left <= 28, left
            for _ in range(4):
                await give_up_and_continue(page)

            await expect(page.get_by_test_id("solo-summary")).to_be_visible()
            await expect(page.get_by_test_id("solo-summary")).to_contain_text("Daily complete")
            await page.get_by_test_id("solo-back").click()
            daily = page.get_by_test_id("solo-daily")
            await expect(daily.get_by_test_id("solo-copy-result")).to_be_visible()
            await expect(daily.get_by_test_id("solo-countdown")).to_be_visible()
            # The streak: one day, with its line running to a week.
            streak = daily.get_by_test_id("solo-streak")
            await expect(streak).to_have_attribute("aria-label", "1 day in a row; the next milestone is 7 days")
            await expect(streak).to_contain_text("1 day")
            await expect(streak.get_by_test_id("solo-streak-goal")).to_have_text("7")
            # The calendar rings today as finished with a miss - one of five
            # named - and counts the Daily.
            today = await page.evaluate(
                "() => { const d = new Date(); return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'),"
                " String(d.getDate()).padStart(2, '0')].join('-') }"
            )
            cell = page.locator(f'[data-testid="solo-calendar-day"][data-date="{today}"]')
            await expect(cell).to_have_class(re.compile(r"\bis-finished\b"))
            await expect(page.get_by_test_id("solo-stats")).to_contain_text("1")

            # A five-drawing free run: the Daily's drawings stay out of it
            # while the Daily is open, so the one seeded past every open
            # Daily is played, and repeats fill the rest.
            await page.get_by_test_id("solo-free-5").click()
            await expect(page.get_by_text("Drawing 1 of 5")).to_be_visible()
            await give_up_and_continue(page)
            # Left half-way, the run waits in its row - Quick's - while
            # Classic and Endless have none, and Continue picks it up.
            await page.reload()
            await expect(page.get_by_test_id("solo-run-progress-5")).to_contain_text("1/5")
            await expect(page.get_by_test_id("solo-free-10")).to_be_visible()
            # Start over asks first, and Cancel keeps the run.
            await page.get_by_test_id("solo-restart-5").click()
            await page.get_by_role("alertdialog").get_by_role("button", name="Cancel").click()
            await expect(page.get_by_test_id("solo-run-progress-5")).to_contain_text("1/5")
            await page.get_by_test_id("solo-continue-5").click()
            await expect(page.get_by_text("Drawing 2 of 5")).to_be_visible()
            for _ in range(4):
                await give_up_and_continue(page)
            await expect(page.get_by_test_id("solo-summary")).to_contain_text("Run over")
        finally:
            await context.close()
            await browser.close()


async def test_solo_holds_together_on_a_phone_and_asks_a_guest_for_an_account():
    await seed_solo_drawings(OPEN_DAILIES_DRAWINGS + 1)
    await settle_open_dailies()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 412, "height": 915}, is_mobile=True, has_touch=True)
        page = await context.new_page()

        async def fits(where: str) -> None:
            width = await page.evaluate("() => document.documentElement.scrollWidth")
            assert width <= 412, (where, width)

        try:
            username = f"phone{uuid4().hex[:8]}"
            await page.goto(BASE_URL)
            await use_guest_name(page, username.capitalize())
            await page.get_by_test_id("lobby-solo").click()
            await page.wait_for_url(f"{BASE_URL}/solo")
            await expect(page.get_by_test_id("solo-account-required")).to_be_visible()
            await fits("guest")

            # The page's own way to an account, and then every view of a run
            # fits too (R-SOLO-17).
            await page.get_by_test_id("solo-account-required").get_by_role("button").click()
            dialog = page.locator(".modal-card").filter(has_text="Password")
            await dialog.wait_for(state="visible")
            await dialog.locator("input").nth(0).fill(username)
            await dialog.locator("input").nth(1).fill("a-good-password")
            await dialog.locator('button[type="submit"]').click()
            await dialog.wait_for(state="hidden")
            await page.goto(BASE_URL)
            await answer_play_languages_question(page)
            await page.goto(f"{BASE_URL}/solo")
            await expect(page.get_by_test_id("solo-free")).to_be_visible()
            await fits("home")
            await page.get_by_test_id("solo-free-5").click()
            await page.get_by_test_id("solo-canvas").locator("canvas").wait_for()
            await fits("play")
            await page.get_by_test_id("solo-give-up").click()
            await expect(page.get_by_test_id("solo-card")).to_be_visible()
            await fits("card")
        finally:
            await context.close()
            await browser.close()


async def open_past_daily(day: date) -> None:
    """Give `day` its Daily as somebody asking for it on the day would have:
    the archive plays only the Dailies there were."""
    engine = create_async_engine(database_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        noon = datetime.combine(day, time(12), tzinfo=timezone.utc)
        async with factory() as session, session.begin():
            assert await daily_set(session, day, now=noon), "too few drawings for a past Daily"
    finally:
        await engine.dispose()


async def take_out_of_solo(day: date, *, position: int) -> None:
    """Take one drawing of `day`'s Daily out of Solo, as its drawer would."""
    engine = create_async_engine(database_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session, session.begin():
            turns = select(SoloDailySet.turn_id).where(
                SoloDailySet.daily_date == day, SoloDailySet.position == position
            )
            await session.execute(
                update(TurnDrawing)
                .where(TurnDrawing.turn_id.in_(turns))
                .values(solo_withdrawn_at=datetime.now(timezone.utc))
            )
    finally:
        await engine.dispose()


async def show_month(page: Page, day: date) -> None:
    """Page the calendar back to `day`'s month."""
    month = day.isoformat()[:7]
    calendar = page.get_by_test_id("solo-calendar")
    for _ in range(40):
        if await calendar.get_attribute("data-month") == month:
            break
        await page.get_by_test_id("solo-calendar-previous").click()
    await expect(calendar).to_have_attribute("data-month", month)


async def test_a_missed_daily_is_played_from_the_calendar_and_then_reviewed():
    # Within sixty days, so no Daily open now can take its concepts - one
    # that did would hold it back, rightly, until today's had ended (R-SOLO-18)
    # - and far enough back to have ended everywhere and to need the
    # calendar's arrows. Its drawings were finished before it.
    day = datetime.now(timezone.utc).date() - timedelta(days=40)
    # The open dates' Dailies first, so no free run elsewhere picks one of
    # them from these five before the past day has them.
    await seed_solo_drawings(OPEN_DAILIES_DRAWINGS)
    await settle_open_dailies()
    await seed_solo_drawings(DAILY_LENGTH, finished=datetime.combine(day, time(0), tzinfo=timezone.utc) - timedelta(days=1))
    await open_past_daily(day)
    username = f"past{uuid4().hex[:8]}"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()
        pick = page.locator(f'[data-testid="solo-calendar-day"][data-date="{day.isoformat()}"]').get_by_test_id(
            "solo-calendar-play"
        )
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, username.capitalize())
            await register_account(page, username)
            await page.goto(f"{BASE_URL}/solo")
            # A new player's calendar reaches back to the first Daily there was.
            await show_month(page, day)
            await expect(pick).to_have_attribute("aria-label", re.compile(r"\. Play$"))
            await pick.click()
            await expect(page.get_by_text("Drawing 1 of 5")).to_be_visible()
            await expect(page.get_by_test_id("solo-play-date")).to_be_visible()
            for _ in range(5):
                await give_up_and_continue(page)
            await expect(page.get_by_test_id("solo-summary")).to_contain_text("Daily complete")
            # A past Daily has no countdown: the next one is today's.
            await expect(page.get_by_test_id("solo-countdown")).to_have_count(0)

            # Finished, the day opens its review: the five in a strip, the
            # one picked large, nothing played again.
            await page.get_by_test_id("solo-back").click()
            await show_month(page, day)
            await expect(pick).to_have_attribute("aria-label", re.compile(r"\. Review$"))
            await pick.click()
            review = page.get_by_test_id("solo-review")
            await expect(review.get_by_test_id("solo-review-thumb")).to_have_count(5)
            first = await review.get_by_test_id("solo-prompt").inner_text()
            await review.get_by_test_id("solo-review-thumb").nth(2).click()
            await expect(review.get_by_test_id("solo-review-thumb").nth(2)).to_have_attribute("aria-pressed", "true")
            await expect(review.get_by_test_id("solo-prompt")).not_to_have_text(first)
            await review.get_by_test_id("solo-card-drawing").locator("canvas").wait_for()
            await expect(page.get_by_test_id("solo-play")).to_have_count(0)
            # The arrow keys step through the five, and stop at the ends.
            thumbs = review.get_by_test_id("solo-review-thumb")
            await page.keyboard.press("ArrowRight")
            await expect(thumbs.nth(3)).to_have_attribute("aria-pressed", "true")
            for _ in range(3):
                await page.keyboard.press("ArrowRight")
            await expect(thumbs.nth(4)).to_have_attribute("aria-pressed", "true")
            await page.keyboard.press("ArrowLeft")
            await expect(thumbs.nth(3)).to_have_attribute("aria-pressed", "true")
            # Stepped from a button under the drawing, which the step replaces,
            # the focus goes to the thumb picked, not back to the page's top.
            await review.get_by_test_id("solo-report").focus()
            await page.keyboard.press("ArrowLeft")
            await expect(thumbs.nth(2)).to_be_focused()
            # Seen whole on a 900 px screen: the actions under the drawing are
            # in view without scrolling.
            bottom = await review.get_by_test_id("solo-report").evaluate(
                "(node) => node.getBoundingClientRect().bottom + window.scrollY"
            )
            assert bottom <= 900, bottom

            # The review fits a phone too (R-SOLO-17).
            await page.set_viewport_size({"width": 412, "height": 915})
            await expect(review).to_be_visible()
            width = await page.evaluate("() => document.documentElement.scrollWidth")
            assert width <= 412, width
            await review.get_by_test_id("solo-review-back").click()
            await expect(page.get_by_test_id("solo-calendar")).to_be_visible()

            # Its first drawing taken out of Solo since: the review opened
            # again asks the drawing door afresh, and shows it no more,
            # however recently this page decoded it (#1496 review). One
            # drawing, not five: the pool is every parallel test's.
            await page.set_viewport_size({"width": 1280, "height": 900})
            await take_out_of_solo(day, position=1)
            await show_month(page, day)
            await pick.click()
            await expect(review.get_by_test_id("solo-card-drawing")).to_contain_text("This drawing could not be loaded.")
            await expect(review.get_by_test_id("solo-review-thumb").locator("canvas")).to_have_count(4)
        finally:
            await context.close()
            await browser.close()
