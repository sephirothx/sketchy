"""A pass bought through the stub shows on the thanks page, in Settings and in the inbox (#1475)."""
from __future__ import annotations

import uuid

from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import register_account, use_guest_name

BASE_URL = "http://localhost:8000"


def unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


async def test_a_pass_bought_through_the_stub_shows_everywhere():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        page = await (await browser.new_context()).new_page()
        name = unique("Marta")
        await page.goto(BASE_URL)
        await use_guest_name(page, name)
        await register_account(page, name)

        await page.goto(f"{BASE_URL}/settings/support")
        pane = page.get_by_test_id("support-pane")
        await pane.wait_for()
        await pane.get_by_role("button", name="Continue to checkout").click()
        await page.get_by_role("button", name="Pay").click()

        await page.get_by_test_id("support-thanks").get_by_text("Thank you").wait_for()

        await page.goto(f"{BASE_URL}/settings/support")
        await pane.get_by_text("You're a supporter. Thank you!").wait_for()
        await pane.get_by_text("renews on").wait_for()

        await page.goto(BASE_URL)
        await page.locator(".identity-chip .supporter-mark").wait_for()

        await page.goto(f"{BASE_URL}/support/cancel")
        await page.get_by_role("button", name="Cancel renewal").click()
        await page.get_by_text("Done. Your pass stays active").wait_for()
        await browser.close()


async def test_a_guest_cannot_reach_checkout():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        page = await (await browser.new_context()).new_page()
        await page.goto(BASE_URL)
        await use_guest_name(page, unique("Visitor"))
        await page.goto(f"{BASE_URL}/settings/support")
        pane = page.get_by_test_id("support-pane")
        await pane.get_by_text("You need an account to get a pass.").wait_for()
        assert await pane.get_by_role("button", name="Continue to checkout").count() == 0
        # The price is known before signing up.
        await pane.get_by_text("Lifetime").wait_for()
        await browser.close()


async def test_a_pass_can_be_gifted_from_a_profile_and_lands_in_the_inbox():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        recipient = await (await browser.new_context()).new_page()
        giver = await (await browser.new_context()).new_page()
        bruno, marta = unique("Bruno"), unique("Marta")
        await recipient.goto(BASE_URL)
        await use_guest_name(recipient, bruno)
        await register_account(recipient, bruno)
        bruno_id = (await (await recipient.request.get(f"{BASE_URL}/api/auth/me")).json())["id"]
        await giver.goto(BASE_URL)
        await use_guest_name(giver, marta)
        await register_account(giver, marta)

        await giver.goto(f"{BASE_URL}/profile/{bruno_id}")
        await giver.get_by_role("button", name="Gift a pass").click()
        dialog = giver.get_by_test_id("gift-pass-dialog")
        await dialog.get_by_role("button", name="Continue to checkout").click()
        await giver.get_by_role("button", name="Pay").click()
        await giver.wait_for_url("**/support/thanks**")

        await recipient.goto(f"{BASE_URL}/settings/support")
        await recipient.get_by_test_id("support-pane").get_by_text("You're a supporter").wait_for()
        inbox = (await (await recipient.request.get(f"{BASE_URL}/api/inbox")).json())["entries"]
        gift = next(entry for entry in inbox if entry["kind"] == "supporter_gifted")
        assert gift["person"]["displayName"] == marta
        await browser.close()


async def test_solo_shows_the_pitch_on_its_two_doors_and_a_pass_opens_them():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        page = await (await browser.new_context()).new_page()
        name = unique("Marta")
        await page.goto(BASE_URL)
        await use_guest_name(page, name)
        await register_account(page, name)

        await page.goto(f"{BASE_URL}/solo")
        await page.get_by_test_id("solo-perk-endless").wait_for()
        await page.get_by_test_id("solo-archive-locked").wait_for()
        assert await page.get_by_test_id("solo-free-unlimited").count() == 0
        # The short runs stay everybody's.
        await page.get_by_test_id("solo-free-5").wait_for()

        response = await page.request.post(
            f"{BASE_URL}/api/support/checkout", data={"product": "year"}
        )
        await page.goto((await response.json())["url"])
        await page.get_by_role("button", name="Pay").click()
        await page.get_by_test_id("support-thanks").get_by_text("Thank you").wait_for()

        await page.goto(f"{BASE_URL}/solo")
        await page.get_by_test_id("solo-free-unlimited").wait_for()
        assert await page.get_by_test_id("solo-perk-endless").count() == 0
        assert await page.get_by_test_id("solo-archive-locked").count() == 0
        await browser.close()
