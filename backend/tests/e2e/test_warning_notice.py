"""A moderator's warning reaches a player who is online when it is issued
(R-MOD-12), whatever the page's own read of the pending warning is doing. The
notice hears of a warning twice - a read of `GET /api/warnings/pending` and the
`moderator_warning` push - and each test widens the window between them that
CI hit by chance (#1336): a read already on its way when the push lands, and a
push sent while the tab has no socket to carry it."""
from __future__ import annotations

import asyncio

from playwright.async_api import Browser, Page, async_playwright, expect

from app.domain_values import UserRole
from tests.e2e.lobby_helpers import BASE_URL, register_account, use_guest_name
from tests.e2e.staff_helpers import set_role

PENDING = "**/api/warnings/pending"
SOCKET = "**/socket.io/**"


async def _admin_and_target(browser: Browser, tag: str) -> tuple[Page, Page, str]:
    """An admin to issue the warning and a registered player to receive it."""
    admin = await (await browser.new_context()).new_page()
    target = await (await browser.new_context()).new_page()
    await admin.goto(BASE_URL)
    await use_guest_name(admin, f"{tag}Admin")
    await register_account(admin, f"{tag}Admin")
    await set_role(f"{tag}Admin", UserRole.ADMIN.value)
    await target.goto(BASE_URL)
    await use_guest_name(target, f"{tag}Target")
    await register_account(target, f"{tag}Target")
    user_id = await target.evaluate("async () => (await (await fetch('/api/auth/me')).json()).id")
    return admin, target, user_id


async def _warn(admin: Page, user_id: str, reason: str) -> None:
    """Issue a warning the way a moderator does."""
    status = await admin.evaluate(
        """async ([userId, reason]) => (await fetch('/api/moderation/warnings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({userId, reason, category: 'spam'}),
        })).status""",
        [user_id, reason],
    )
    assert status == 201, status


def _notice(page: Page):
    return page.get_by_role("alertdialog", name="A moderator warning")


async def test_a_read_already_on_its_way_does_not_take_a_pushed_warning_back():
    """The page's read of the pending warning is answered before the warning
    exists, and the answer is held until the push has shown the notice. It
    says nothing is pending - older news than the push - and used to replace
    it."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        try:
            admin, target, user_id = await _admin_and_target(browser, "HeldRead")
            held = asyncio.Event()
            released = asyncio.Event()

            async def hold(route):
                # The server answers now, before the warning exists; only the
                # answer is late. Holding the request itself would let it
                # reach the server after the warning and find it.
                answer = await route.fetch()
                if not released.is_set():
                    held.set()
                    await released.wait()
                await route.fulfill(response=answer)

            await target.route(PENDING, hold)
            await target.reload()
            await asyncio.wait_for(held.wait(), timeout=15)
            # The push needs a socket to land on.
            await target.wait_for_function("() => window.__SKETCHY_SOCKET__?.connected === true")

            await _warn(admin, user_id, "Held read check")
            notice = _notice(target)
            await expect(notice).to_be_visible()

            async with target.expect_response(PENDING) as answered:
                released.set()
            assert (await (await answered.value).json())["warning"] is None
            # Every read held above has answered by now, each with nothing.
            await target.wait_for_timeout(500)
            await expect(notice).to_be_visible()
        finally:
            await browser.close()


async def test_a_warning_pushed_while_the_tab_had_no_socket_shows_once_it_connects():
    """The tab's socket is held off while the warning is issued, so the push
    reaches nobody, and its read at load answered before the warning existed.
    The notice used to wait for the next visit; the connection that follows
    reads again."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        try:
            admin, target, user_id = await _admin_and_target(browser, "NoSocket")
            opened = asyncio.Event()

            async def websocket(ws_route):
                if opened.is_set():
                    ws_route.connect_to_server()
                else:
                    await ws_route.close()

            async def polling(route):
                if opened.is_set():
                    await route.continue_()
                else:
                    await route.abort()

            await target.route_web_socket(SOCKET, websocket)
            await target.route(SOCKET, polling)
            async with target.expect_response(PENDING) as first_read:
                await target.reload()
            assert (await (await first_read.value).json())["warning"] is None

            await _warn(admin, user_id, "No socket check")
            notice = _notice(target)
            # Nothing has reached the tab: the push had no socket to go to.
            await target.wait_for_timeout(1_000)
            await expect(notice).to_have_count(0)

            opened.set()
            # The client's reconnect backoff is at most 10 s, randomised by half.
            await expect(notice).to_be_visible(timeout=30_000)
        finally:
            await browser.close()
