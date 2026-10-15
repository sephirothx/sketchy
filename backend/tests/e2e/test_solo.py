"""Solo (#1434) end to end: the Daily and a free run, played in the browser.

The drawings are written straight into the server's database as finished
public games, with prompts from the official lists the server seeds - what
matters is that Solo serves them, not how a test could draw them. A player
names the first Daily drawing (the prompt read back from their own serve,
since play is local and the answer never shows), misses one with a wrong
guess and gives it up, reloads mid-Daily and carries on where they were,
finishes it, and then plays a five-drawing free run. The page also has to
hold together at phone width, and a guest is told what an account unlocks.
Past Dailies (#1470) plays a missed day late and then plays it again, which
records nothing.
"""
from __future__ import annotations

import base64
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from playwright.async_api import Page, async_playwright, expect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Prompt, PromptList, PromptVersion, SoloServe, User
from app.domain_values import PROMPT_LANGUAGES
from app.repositories.solo import daily_set
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


async def seed_solo_drawings(count: int, *, finished: datetime | None = None) -> None:
    """`count` public games of one curated turn each, every language able
    to name it, two guessers and one of them right: Daily candidates, and
    free-run drawings for anybody who was not in them."""
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
                    )
                    .order_by(func.random())
                    .limit(count)
                )
            ).all()
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
    await expect(page.get_by_test_id("solo-verdict")).to_be_visible()
    await page.get_by_test_id("solo-next").click()


async def test_a_daily_and_a_free_run_are_played_through():
    await seed_solo_drawings(6)
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
            await expect(daily.get_by_test_id("solo-streak")).to_have_text("1 day in a row")

            # A five-drawing free run: the Daily's drawings stay out of it
            # while the Daily is open, so the sixth seeded one is played, and
            # repeats fill the rest.
            await page.get_by_test_id("solo-free-5").click()
            await expect(page.get_by_text("Drawing 1 of 5")).to_be_visible()
            for _ in range(5):
                await give_up_and_continue(page)
            await expect(page.get_by_test_id("solo-summary")).to_contain_text("Run over")
        finally:
            await context.close()
            await browser.close()


async def test_solo_holds_together_on_a_phone_and_asks_a_guest_for_an_account():
    # Six: a free run picks today's Daily if nobody has, so whichever test
    # runs first the Daily has five drawings, and a free run - which never
    # serves an open Daily's concept - still has a sixth to play.
    await seed_solo_drawings(6)
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
            await expect(page.get_by_test_id("solo-verdict")).to_be_visible()
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


async def test_a_missed_daily_is_played_from_past_dailies_and_then_played_again():
    # Far enough back that its concepts never stand in the way of today's
    # Daily, which a concept used within sixty days would; its drawings were
    # finished before it.
    day = datetime.now(timezone.utc).date() - timedelta(days=400)
    await seed_solo_drawings(5, finished=datetime.combine(day, time(0), tzinfo=timezone.utc) - timedelta(days=1))
    await open_past_daily(day)
    username = f"past{uuid4().hex[:8]}"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, username.capitalize())
            await register_account(page, username)
            await page.goto(f"{BASE_URL}/solo")
            await page.get_by_test_id("solo-open-archive").click()
            row = page.locator(f'[data-testid="solo-archive-day"][data-date="{day.isoformat()}"]')
            await expect(row.get_by_test_id("solo-archive-play")).to_have_text("Play")
            await row.get_by_test_id("solo-archive-play").click()
            await expect(page.get_by_text("Drawing 1 of 5")).to_be_visible()
            await expect(page.get_by_test_id("solo-play-date")).to_be_visible()
            for _ in range(5):
                await give_up_and_continue(page)
            await expect(page.get_by_test_id("solo-summary")).to_contain_text("Daily complete")
            # A past Daily has no countdown: the next one is today's.
            await expect(page.get_by_test_id("solo-countdown")).to_have_count(0)

            await page.get_by_test_id("solo-back").click()
            await expect(row.get_by_test_id("solo-archive-play")).to_have_text("Play it again")
            await row.get_by_test_id("solo-archive-play").click()
            await expect(page.get_by_text("Not recorded")).to_be_visible()
            for _ in range(5):
                await give_up_and_continue(page)
            await expect(page.get_by_test_id("solo-summary")).to_contain_text("Played again")

            # The archive's rows fit a phone too (R-SOLO-17).
            await page.get_by_test_id("solo-back").click()
            await page.set_viewport_size({"width": 412, "height": 915})
            await expect(page.get_by_test_id("solo-archive-day").first).to_be_visible()
            width = await page.evaluate("() => document.documentElement.scrollWidth")
            assert width <= 412, width
        finally:
            await context.close()
            await browser.close()
