"""Tuning a live server from the operations page, and a client already running obeying it.

The motivating value in #446 is a *client* cadence, which is what makes this
worth an end-to-end test rather than two unit tests on either side: the number
is set on one machine, travels over the socket, and has to reach a timer that
is already armed in a browser that never reloaded. Each of those is somewhere
the value could be quietly dropped, and none of them is visible from one side.

The cadence under test is the lobby poll rather than the drawer's flush
interval, for two reasons. It is observable without adding anything to the
application: counting the lobby's own requests watches the behaviour the
setting names, where reading the flush interval back would mean exposing it on
`window` for the benefit of this file - production code existing only for a
test, which is what R-ENG-10 discourages. And it is the safe one to move.

**A tunable is process-wide, and this suite shares one server.** `--dist=load`
spreads individual tests across workers, so anything changed here is changed
for whatever else is running at that moment. That rules out most of them: a
flush interval of 20ms would reach every drawing test in flight. Polling the
lobby *faster* cannot break a test that waits for a room card to appear, which
is why it is the one this file moves - briefly, and put back in a `finally`
through the API rather than the page, so a failed assertion still restores it.

These tests must never reach for a tunable to make themselves faster (R-CONF-08).
Nothing here shortens a timeout; the settings are the subject, not the tool.
"""
import os
import time

import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import AppConfig, AuditEvent, User
from app.domain_values import UserRole
from tests.e2e.lobby_helpers import register_account, use_guest_name


BASE_URL = "http://localhost:8000"


def _database_url() -> str:
    url = os.environ.get("SKETCHY_E2E_DATABASE_URL")
    if not url:
        pytest.skip("SKETCHY_E2E_DATABASE_URL is not set; run via scripts/test-e2e.sh")
    return url


async def promote_to_admin(username: str) -> None:
    """Make one account staff, through the same throwaway database the server uses."""
    engine = create_async_engine(_database_url())
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


async def stored_settings() -> dict:
    engine = create_async_engine(_database_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            rows = (await session.scalars(select(AppConfig))).all()
        return {row.key: row.value for row in rows}
    finally:
        await engine.dispose()


async def config_changes() -> list:
    engine = create_async_engine(_database_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            events = (
                await session.scalars(
                    select(AuditEvent).where(AuditEvent.event_type == "config.changed")
                )
            ).all()
        return [(event.target_id, event.details) for event in events]
    finally:
        await engine.dispose()


async def an_admin_page(browser, username: str):
    context = await browser.new_context()
    page = await context.new_page()
    page.set_default_timeout(10000)
    await page.goto(BASE_URL)
    await use_guest_name(page, username)
    await register_account(page, username)
    await promote_to_admin(username)
    await page.reload()
    return context, page


def field_for(name: str) -> str:
    """The number input for one setting, by the id the panel gives it."""
    return "#tunable-" + name.replace(".", "\\.")


@pytest.mark.asyncio
async def test_a_tuned_cadence_reaches_a_browser_that_never_reloaded():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        admin_context, admin_page = await an_admin_page(browser, "TuningAdmin")
        player_context = await browser.new_context()
        player_page = await player_context.new_page()
        player_page.set_default_timeout(10000)

        polls: list[float] = []
        player_page.on(
            "request",
            lambda request: (
                polls.append(time.monotonic())
                if request.url.endswith("/api/rooms")
                else None
            ),
        )

        try:
            # Connected before anything is tuned, and never reloaded after.
            # A page that arrived later would read the new value at its own
            # handshake, which would prove nothing about a change reaching a
            # client that was already running.
            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "TunedPlayer")
            await player_page.bring_to_front()
            await player_page.wait_for_timeout(500)

            await admin_page.goto(f"{BASE_URL}/admin/operations?tab=tuning")
            # The tab is addressable, so a link to one survives being sent.
            await admin_page.wait_for_selector(
                '[role="tab"][aria-selected="true"]:has-text("Tuning")'
            )
            # Every control is drawn from what the server said about the
            # setting, so the page knows nothing about any particular one.
            await admin_page.wait_for_selector(
                "text=Freshness against request volume"
            )

            await admin_page.fill(field_for("client.lobby_poll_interval_ms"), "1000")
            await admin_page.click('button:has-text("Apply changes")')
            await admin_page.wait_for_selector("text=In force now")

            assert (
                await stored_settings()
            ).get("tunable.client.lobby_poll_interval_ms") == "1000"
            # `override` says the change is now a durable row, which is the
            # half of the record a reset later takes back.
            assert (
                "client.lobby_poll_interval_ms",
                {"from": 4000, "to": 1000, "override": "stored"},
            ) in await config_changes()

            # Four polls inside eight seconds is impossible at the four-second
            # default and comfortable at one second, so this discriminates
            # without depending on the browser hitting an exact cadence.
            await player_page.bring_to_front()
            polls.clear()
            deadline = time.monotonic() + 8
            while len(polls) < 4 and time.monotonic() < deadline:
                await player_page.wait_for_timeout(250)
            assert len(polls) >= 4, (
                f"the lobby polled {len(polls)} times in eight seconds; a change "
                "from 4000ms to 1000ms did not reach a browser already running"
            )

            # Reset through the page, since that control is part of what is
            # being tested: the row goes with it, because a stored value equal
            # to the boot value would pin the setting against a later change to
            # whatever supplies it.
            await admin_page.click(
                f'{field_for("client.lobby_poll_interval_ms")} ~ button:has-text("Reset")'
            )
            await admin_page.wait_for_selector("text=In force now")
            assert (
                "tunable.client.lobby_poll_interval_ms" not in await stored_settings()
            )
        finally:
            # Through the API, not the page: a failed assertion above must not
            # leave every other test in this run polling four times as often.
            await admin_page.request.patch(
                f"{BASE_URL}/api/admin/tunables",
                data={"reset": ["client.lobby_poll_interval_ms"]},
            )
            await player_context.close()
            await admin_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_a_pair_that_cannot_hold_together_is_refused_with_its_reason():
    """20ms is inside its own bounds and outside what the drawing budget admits.

    A drawer flushing every 20ms produces a hundred frames per two seconds, and
    the budget is sized at twice what a legitimate drawer sends. Either number
    is defensible alone, which is exactly why the server checks the pair rather
    than each in turn - and why the panel has to be able to show the reason.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        admin_context, admin_page = await an_admin_page(browser, "BoundsAdmin")
        try:
            await admin_page.goto(f"{BASE_URL}/admin/operations?tab=tuning")
            await admin_page.fill(field_for("client.flush_interval_ms"), "20")
            await admin_page.click('button:has-text("Apply changes")')
            await admin_page.wait_for_selector("text=drawing budget of at least")

            # Nothing was applied, which is the other half of the claim: an
            # all-or-nothing change leaves no trace when it is refused. It is
            # also why this test is safe to run beside a drawing test - a 20ms
            # flush interval never reaches the server the others are using.
            # That the pair *is* accepted when set together is checked in
            # `tests/test_runtime_settings.py`, where it costs nobody anything.
            assert "tunable.client.flush_interval_ms" not in await stored_settings()
        finally:
            await admin_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_an_ordinary_player_is_not_shown_the_operations_page():
    """R-ROLE-01: the route answers the same way to anyone who types it in."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(10000)
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "CuriousPlayer")
            await page.goto(f"{BASE_URL}/admin/operations")
            await page.wait_for_selector("text=This page is for administrators.")
        finally:
            await context.close()
            await browser.close()
