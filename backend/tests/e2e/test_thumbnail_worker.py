"""Gallery thumbnails are drawn off the page's thread (#1282).

A thumbnail's replay costs whatever its history makes the renderer do, and
the costliest history the server accepts - `fixtures/fill_replay_100.json`,
100 full-canvas fills - held the main thread for about a second a
thumbnail on a phone-speed CPU. The built app draws thumbnails on a worker;
this proves it does in the real bundle, under the real Content-Security-
Policy, where a worker that failed to load would fall back to the page
silently: the worker's script is fetched, the image appears, and no task on
the main thread comes near the replay's length.

The drawing is written straight into the server's database, as a finished
public game - what matters is the history, not how a test could draw it.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from playwright.async_api import async_playwright
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    TurnDrawingInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import SqlAlchemyGameHistoryRepository, SqlAlchemyUserRepository
from tests.e2e.lobby_helpers import BASE_URL, use_guest_name
from tests.e2e.staff_helpers import database_url
from tests.e2e.test_gallery import find_in_gallery

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "fill_replay_100.json"
# The page's own tasks at this throttle stay well under this; the fixture
# replayed on the page is one task of about a second (#1282's benchmark:
# 972 ms at 4x).
LONGEST_TASK_BUDGET_MS = 500
CPU_THROTTLE = 4


async def seed_fill_heavy_game(prompt: str) -> None:
    engine = create_async_engine(database_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        users = SqlAlchemyUserRepository(factory)
        drawer = await users.create_anonymous(f"Filler{prompt[-4:]}")
        guesser = await users.create_anonymous(f"Watcher{prompt[-4:]}")
        drawer_seat, guesser_seat, turn_id = (str(uuid4()) for _ in range(3))
        finished = datetime.now(timezone.utc)
        await SqlAlchemyGameHistoryRepository(factory).save_game(
            GameRecordInput(
                room_name="Fills", scoring_mode="none", hint_mode="none", drawing_seconds=90,
                total_rounds=1, player_count=2, started_at=finished - timedelta(minutes=2),
                finished_at=finished, visibility="public",
            ),
            [
                GameParticipantInput(user_id=drawer.id, final_score=0, final_rank=1, seat_id=drawer_seat,
                                     display_name=drawer.display_name),
                GameParticipantInput(user_id=guesser.id, final_score=0, final_rank=1, seat_id=guesser_seat,
                                     display_name=guesser.display_name),
            ],
            [
                TurnRecordInput(
                    id=turn_id, round_number=1, turn_number=1, drawer_user_id=drawer.id,
                    drawer_seat_id=drawer_seat, prompt=prompt, duration_seconds=60, guesser_count=1,
                    participant_outcomes=(
                        TurnParticipantOutcomeInput(
                            seat_id=guesser_seat, user_id=guesser.id, eligible=True,
                            eligibility_reason="eligible", outcome="no_attempt", terminal_state="active",
                        ),
                    ),
                )
            ],
            None,
            [TurnDrawingInput(turn_id=turn_id, payload=base64.b64decode(json.loads(FIXTURE.read_text())["base64"]))],
        )
    finally:
        await engine.dispose()


async def test_a_fill_heavy_thumbnail_is_drawn_without_holding_the_page():
    prompt = f"fills {uuid4().hex[:6]}"
    await seed_fill_heavy_game(prompt)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "ThumbViewer")
            await page.add_init_script(
                "window.__longTasks = [];"
                "new PerformanceObserver((list) => {"
                "  for (const entry of list.getEntries()) window.__longTasks.push(entry.duration);"
                "}).observe({ type: 'longtask', buffered: true });"
            )
            session = await context.new_cdp_session(page)
            await session.send("Emulation.setCPUThrottlingRate", {"rate": CPU_THROTTLE})
            await page.goto(f"{BASE_URL}/gallery?sort=new")
            (card,) = await find_in_gallery(page, [prompt])
            await card.locator("img").wait_for(timeout=30_000)

            workers = await page.evaluate(
                "() => performance.getEntriesByType('resource')"
                ".map((entry) => entry.name).filter((name) => name.includes('thumbnail.worker'))"
            )
            assert workers, "the thumbnail worker's script was never fetched: thumbnails were drawn on the page"
            longest = await page.evaluate("() => Math.max(0, ...window.__longTasks)")
            assert longest < LONGEST_TASK_BUDGET_MS, (
                f"a {longest:.0f} ms task held the main thread; the fixture's replay belongs on the worker"
            )
        finally:
            await context.close()
            await browser.close()
