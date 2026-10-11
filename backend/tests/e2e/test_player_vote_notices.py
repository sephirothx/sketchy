"""A kick or AFK vote reaches a phone seat in the room bar, and no vote's
popover covers the card that says the connection was lost (#1422, R-VOTE-04).

A vote's only trace was the tally on the target's row in the desktop players
list. A phone folds that list behind the Room menu, so a phone seat never saw
a vote, and a vote nobody sees never reaches its majority."""
import asyncio
import re
from uuid import uuid4

from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import (
    join_by_code,
    open_new_room,
    open_room_menu,
    room_code,
    use_guest_name,
)


BASE_URL = "http://localhost:8000"
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
DESKTOP = {"viewport": {"width": 1280, "height": 860}}
POPOVER = '[data-testid="player-vote"]'


async def vote_from_the_list(page, nickname: str, kind: str) -> None:
    """Cast a ballot the desktop way: the target's row in the players list."""
    # "Kick vote or AFK vote for X" for a guest, "... or report X" otherwise.
    await page.get_by_role("button", name=re.compile(rf"^Kick vote.* {re.escape(nickname)}$")).click()
    await page.locator(f".player-vote-action.player-vote-{kind}").click()


async def test_a_phone_seat_sees_and_answers_a_kick_and_an_afk_vote():
    tag = uuid4().hex[:5]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        starter_context = await browser.new_context(**DESKTOP)
        phone_contexts = [await browser.new_context(**PHONE) for _ in range(3)]
        starter = await starter_context.new_page()
        phones = [await context.new_page() for context in phone_contexts]
        names = {starter: f"Starter{tag}"}
        try:
            await starter.goto(BASE_URL)
            await use_guest_name(starter, names[starter])
            await open_new_room(starter)
            code = await room_code(starter)
            for index, page in enumerate(phones):
                names[page] = f"Phone{index}{tag}"
                await page.goto(BASE_URL)
                await use_guest_name(page, names[page])
                await join_by_code(page, code)
                await page.wait_for_selector('[data-testid="waiting-room"]')
            await starter.get_by_role("button", name="Start game").click()

            # Four seats: three ballots carry a vote, so one or two stay open.
            # The target, and a voter who is not the one drawing.
            drawer = None
            for _ in range(150):
                for page in [starter, *phones]:
                    if await page.locator(".prompt-choices button").count():
                        drawer = page
                if drawer:
                    break
                await asyncio.sleep(0.1)
            assert drawer is not None
            target = phones[0] if phones[0] is not drawer else phones[1]
            voter = next(page for page in phones if page is not target and page is not drawer)
            afk_target = next(page for page in [starter, *phones] if page not in (starter, target, voter))

            # Opened on a desktop row: the phone's popover asks by itself.
            await vote_from_the_list(starter, names[target], "kick")
            popover = voter.locator(POPOVER)
            await expect(popover).to_be_visible(timeout=8000)
            await expect(popover).to_contain_text(f"Kick {names[target]} from the room?")
            await expect(popover).to_contain_text("1 of 3 votes")
            # Put off, then withdrawn and cast again: a ballot is a toggle, and
            # the reopened vote does not ask the phone a second time.
            await popover.get_by_role("button", name="Not now").click()
            await expect(popover).to_be_hidden()
            await vote_from_the_list(starter, names[target], "kick")
            await expect(voter.locator(".room-notice-chip", has_text="Kick")).to_have_count(0)
            await vote_from_the_list(starter, names[target], "kick")
            await expect(voter.locator(".room-notice-chip", has_text="Kick 1/3")).to_be_visible()
            await voter.wait_for_timeout(1500)
            await expect(popover).to_be_hidden()
            await voter.locator(".room-notice-chip", has_text="Kick 1/3").click()
            await popover.get_by_role("button", name="Vote to kick").click()
            # Cast: the popover goes, and the chip carries the new tally.
            await expect(popover).to_be_hidden()
            chip = voter.locator(".room-notice-chip", has_text="Kick 2/3")
            await expect(chip).to_be_visible()
            # The opening was said in the chat, in words.
            await expect(
                voter.locator(".chat-message.system", has_text=f"A vote to kick {names[target]} has started.")
            ).to_have_count(1)

            # The target sees the vote about them, and has nothing to cast.
            await target.locator(".room-notice-chip", has_text="Kick 2/3").click()
            about_me = target.locator(POPOVER)
            await expect(about_me).to_contain_text("A vote to kick you from the room is open.")
            await expect(about_me.get_by_role("button")).to_have_count(0)

            # An AFK vote is its own chip and its own question. It opens while
            # the phone is typing a guess: the keyboard hides the room bar, but
            # not while a vote waits for this seat - the chip lives there
            # (review of #1447). The question waits for the keyboard to close.
            if await drawer.locator(".prompt-choices button").count():
                await drawer.locator(".prompt-choices button").first.click()
            field = voter.locator(".chat-input input")
            await field.focus()
            await voter.locator(".game-room.guess-focused").wait_for()
            await vote_from_the_list(starter, names[afk_target], "afk")
            await expect(voter.locator(".room-notice-chip", has_text="AFK 1/3")).to_be_visible()
            await expect(popover).to_be_hidden()
            await field.blur()
            await expect(popover).to_contain_text(f"Mark {names[afk_target]} AFK?")
            await popover.get_by_role("button", name="Vote AFK").click()
            await expect(voter.locator(".room-notice-chip", has_text="AFK 2/3")).to_be_visible()

            # The phone's way into the players list says votes are open.
            menu = await open_room_menu(voter)
            await expect(menu.get_by_test_id("players-vote-badge")).to_have_text("2 votes open")
            await voter.keyboard.press("Escape")

            # No vote's popover over the card that says the connection is lost.
            await chip.click()
            await expect(popover).to_be_visible()
            await phone_contexts[phones.index(voter)].set_offline(True)
            await expect(voter.get_by_test_id("room-stage-paused")).to_be_visible(timeout=15000)
            await expect(popover).to_be_hidden()
            await phone_contexts[phones.index(voter)].set_offline(False)
        finally:
            for context in (starter_context, *phone_contexts):
                await context.close()
            await browser.close()
