"""Setting up two-factor authentication, and being asked for it again.

The ceremony R-AUTH-20 describes has three parts a browser has to get right,
and none of them is provable from the server side alone: the secret is held in
the page between the offer and the confirmation (nothing is stored until a code
comes back), the recovery codes are shown exactly once, and a destructive staff
action that is refused for want of a step-up has to raise a prompt rather than
report a failure.

The other staff suites grant the second factor straight into the database, on
purpose - they are about the moderation queue and the tuning panel. This is the
one that would fail if the dialogs broke.
"""
import time

import pytest
from playwright.async_api import async_playwright, expect

from app.auth.totp import code_at, current_step
from tests.e2e.lobby_helpers import register_account, room_code, use_guest_name
from tests.e2e.staff_helpers import offer_role, set_role, type_code

BASE_URL = "http://localhost:8000"
PASSWORD = "a-good-password"


async def _open_two_factor(page):
    # Settings → Account, where it appears for an account with a role waiting
    # on it - and for nobody else, since a second factor does nothing for an
    # ordinary player (R-AUTH-20).
    await page.goto(f"{BASE_URL}/settings/account")
    await page.get_by_role("button", name="Set up").click()
    # By accessible name: the settings overlay is a dialog too, and it
    # carries this row's label.
    return page.get_by_role("dialog", name="Two-factor authentication")


@pytest.mark.asyncio
async def test_two_factor_is_set_up_once_and_then_asked_for_again():
    """Enrolment, the codes, and the step-up prompt, in one browser.

    Deliberately one test rather than three. Each one would want its own
    browser, and the suite already runs eight workers against a single server;
    two extra browsers were enough to push the heaviest game tests past their
    timeouts. The three things checked here are steps of one flow anyway, and
    a person performs them in this order.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(10000)
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "TwoFactorPlayer")
            await register_account(page, "TwoFactorPlayer")

            # Nothing about two-factor authentication is offered to a player
            # with no role and none waiting: it would be a setting that gates
            # nothing, on a credential with no way back if it were lost.
            await page.goto(f"{BASE_URL}/settings/account")
            await expect(
                page.get_by_text("Two-factor authentication")
            ).to_have_count(0)

            # An administrator offers the role. Now there is something for it
            # to be the last step of.
            await offer_role("TwoFactorPlayer")

            dialog = await _open_two_factor(page)
            await expect(dialog).to_be_visible()
            # A passkey is offered first (R-AUTH-23) and covered by
            # `test_passkey_setup.py`; this is the app route beneath it, which
            # is what a device with no authenticator of its own uses.
            await dialog.get_by_role(
                "button", name="Use an authenticator app instead"
            ).click()
            # A QR code is what a phone points at; the key beside it is the
            # same secret written out, and is what this test can read.
            await expect(dialog.locator(".two-factor-qr")).to_be_visible()
            secret = (await dialog.locator(".two-factor-secret code").inner_text()).strip()
            assert secret

            # The password says whose account the factor is being bound to;
            # the code says an authenticator produced it. The role waiting on
            # this is granted on the pair (R-AUTH-20). Six boxes that submit
            # themselves on the last digit, so there is no button to press.
            await dialog.get_by_label("Your password").fill(PASSWORD)
            await type_code(dialog, code_at(secret, current_step(time.time())))

            codes = dialog.get_by_role("list", name="Recovery codes")
            await expect(codes).to_be_visible()
            assert await codes.locator("li").count() == 10

            # Shown once, so the way past is a tick that says they were kept:
            # until it is given, "Done" is disabled and Escape does nothing.
            done = dialog.get_by_role("button", name="Done")
            await expect(done).to_be_disabled()
            await page.keyboard.press("Escape")
            await expect(codes).to_be_visible()
            await dialog.locator(".two-factor-ack input").check()
            await done.click()

            # And the role that was waiting has begun. Every other device was
            # signed out with it; this one, which proved a password and a code
            # one request ago, is handed a session for the role it now holds.
            await expect(dialog).to_contain_text("You are now a moderator")
            await dialog.get_by_role("button", name="Done").click()

            # Signing in again, with the code - the one thing an account with
            # a second factor does that nothing else here does, and the thing
            # that was quietly broken: the dialog handed `login` the code in
            # the argument `register` uses for an email, so the server was
            # asked to accept a sign-in with no code and said so.
            await page.evaluate(
                "async () => { await fetch('/api/auth/logout', {method: 'POST'}); }"
            )
            await page.goto(BASE_URL)
            await page.click(".first-run-login")
            form = page.locator(".modal-card").filter(has_text="Password")
            await form.get_by_label("Username").fill("TwoFactorPlayer")
            await form.get_by_label("Password", exact=True).fill(PASSWORD)
            await form.locator('button[type="submit"]').click()
            # Asked for, rather than assumed: the field appears only once the
            # server has said the password was right and it wants a code.
            code_field = form.get_by_label("Code from your authenticator app")
            await expect(code_field).to_be_visible()
            # One step on from the enrolment's, which is spent.
            await code_field.fill(code_at(secret, current_step(time.time()) + 1))
            await form.locator('button[type="submit"]').click()
            await expect(form).to_have_count(0)
            await expect(page.locator(".identity-chip")).to_contain_text(
                "TwoFactorPlayer"
            )

            # Administrator from here, written rather than offered: only a
            # moderator role can be offered, and what the rest of this test is
            # about is the step-up prompt, which the operator's own commands
            # are the clearest example of.
            await set_role("TwoFactorPlayer", "admin")
            # Nothing proved since: exactly the state a browser is in once its
            # step-up window has run out.
            await _clear_step_up("TwoFactorPlayer")

            # Closing a room this test opened itself, rather than pausing
            # admission. Both are destructive staff actions that raise the
            # prompt (R-AUTH-21), but a pause is *server-wide* - it refuses
            # new rooms, games and restart votes for everybody - and this
            # suite runs eight workers against one server, so holding one even
            # for a second failed whichever room or game happened to be
            # starting elsewhere. A room of our own is the same gate with none
            # of the blast radius.
            # Straight to the setup route rather than through the lobby's
            # button. How a room is reached is not what this test is about,
            # and going by click meant waiting on a navigation between two
            # pages that both carry a "Create room" button - a race this lost
            # twice on CI, where a shard is slower than anything local.
            # `test_waiting_room` covers the lobby's own path to it.
            await page.goto(f"{BASE_URL}/create")
            await page.wait_for_selector(".create-room-page h1")
            await page.click('button:has-text("Create room")')
            await page.wait_for_selector('[data-testid="waiting-room"]')
            # Found by its code rather than by a name typed into the setup
            # form: the operator's table lists every room on the server, so
            # the row has to be identified, and the code is issued rather than
            # entered - one less field on the way there to wait for.
            code = await room_code(page)

            await page.goto(f"{BASE_URL}/admin/operations?tab=controls")
            await page.wait_for_selector(
                '[role="tab"][aria-selected="true"]:has-text("Controls")'
            )
            room_row = page.locator(".ops-table tbody tr", has_text=code)
            await expect(room_row).to_be_visible()
            await room_row.get_by_role("button", name="Close room").click()
            await room_row.get_by_role("button", name="Confirm close").click()

            prompt = page.locator('[role="dialog"]', has_text="Confirm it is you")
            await expect(prompt).to_be_visible()

            # The code showing on the phone right now, which is what a
            # moderator would type. Six boxes that submit themselves on the
            # last digit, so there is no button to press here.
            await type_code(prompt, code_at(secret, current_step(time.time())))
            await expect(prompt).not_to_be_visible()

            # And the command the prompt interrupted actually ran: the row is
            # gone from a table this test is the only writer of.
            await expect(room_row).to_have_count(0)
        finally:
            await context.close()
            await browser.close()


async def _clear_step_up(username: str) -> None:
    """Take back the step-up the sign-in stamps, so the prompt is reachable.

    Forgets the spent TOTP step with it. Enrolment and the sign-in that
    followed have each spent one, and a browser cannot wait out a 30-second
    interval inside a suite that finishes in 40 - so without this the only
    codes left to type are ones the verifier has already seen. What that rule
    protects is checked where it can be checked properly, in
    `test_auth_hardening.py`; what this test needs is a code its subject will
    accept.
    """
    from sqlalchemy import select, update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.models import AuthSession, User, UserSecondFactor
    from tests.e2e.staff_helpers import database_url

    engine = create_async_engine(database_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            async with session.begin():
                user_id = await session.scalar(
                    select(User.id).where(User.username == username)
                )
                await session.execute(
                    update(AuthSession)
                    .where(AuthSession.user_id == user_id)
                    .values(stepped_up_at=None)
                )
                await session.execute(
                    update(UserSecondFactor)
                    .where(UserSecondFactor.user_id == user_id)
                    .values(last_step=0)
                )
    finally:
        await engine.dispose()
