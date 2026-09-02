"""Lobby chat over a real socket: said once, seen by every open lobby, and by
whoever arrives afterwards.

Every worker in the suite shares one server and so one lobby chat, so the
text each test says carries something unique, and nothing here asserts on
how many lines there are.
"""
import re
import uuid

import pytest
from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import use_guest_name

BASE_URL = "http://localhost:8000"

# A line is delivered the moment it is said, but the watcher's own baseline
# arrives on a subscription that may still be settling.
SETTLE_MS = 8000

COMPOSER_CONTRACT = {
    "type": "search",
    "role": None,
    "inputMode": "text",
    "autoComplete": "off",
    "autoCapitalize": "sentences",
    "spellCheck": True,
    "autoCorrect": None,
    "enterKeyHint": "send",
}


def line_saying(page, text: str):
    return page.locator(".lobby-chat-line", has_text=text)


@pytest.mark.asyncio
async def test_a_line_reaches_every_open_lobby_and_whoever_arrives_after(
    assert_input_contract,
):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        watcher_context = await browser.new_context()
        speaker_context = await browser.new_context()
        latecomer_context = await browser.new_context()
        watcher = await watcher_context.new_page()
        speaker = await speaker_context.new_page()
        latecomer = await latecomer_context.new_page()
        said = f"Anyone up for a round? {uuid.uuid4().hex[:8]}"

        try:
            await watcher.goto(BASE_URL)
            await use_guest_name(watcher, "ChatWatcher")
            await speaker.goto(BASE_URL)
            await use_guest_name(speaker, "ChatSpeaker")

            composer = speaker.locator(".lobby-chat-form input")
            await assert_input_contract(composer, COMPOSER_CONTRACT)
            await composer.fill(said)
            await composer.press("Enter")

            # The watcher sees it without clicking anything, signed by a guest
            # in guest grey (R-ACCT-05), and marked as fresh.
            heard = line_saying(watcher, said)
            await expect(heard).to_be_visible(timeout=SETTLE_MS)
            await expect(heard.locator(".colored-player-name")).to_contain_text(
                "ChatSpeaker"
            )
            await expect(heard.locator(".colored-player-name")).to_have_class(
                re.compile(r"\bis-guest\b")
            )
            await expect(heard.locator(".lobby-chat-time")).to_have_text("now")
            assert await heard.locator(".lobby-chat-time").get_attribute("title")

            # The speaker sees their own line too, and the box is theirs again.
            await expect(line_saying(speaker, said)).to_be_visible(timeout=SETTLE_MS)
            await expect(composer).to_have_value("")

            # Somebody arriving afterwards is handed what was said before they
            # got here - and, until they choose a name, a way to do that
            # rather than a box that would refuse them.
            await latecomer.goto(BASE_URL)
            await expect(
                latecomer.get_by_role("button", name="Choose a name to chat")
            ).to_be_visible(timeout=SETTLE_MS)
            await expect(line_saying(latecomer, said)).to_be_visible(
                timeout=SETTLE_MS
            )
            await use_guest_name(latecomer, "ChatLatecomer")
            await expect(line_saying(latecomer, said)).to_be_visible(
                timeout=SETTLE_MS
            )
            await expect(latecomer.locator(".lobby-chat-form input")).to_be_visible()
        finally:
            await latecomer_context.close()
            await speaker_context.close()
            await watcher_context.close()
            await browser.close()
