"""Reporting a line of the lobby's chat, from the line itself.

The room reports a seat over the socket and lets the server pick the evidence.
The lobby has no seat, so a line is reported over REST, naming the account the
line carries and citing the one retained row it was opened from (R-LCHAT-05).
The author's name is the control: a line that cannot be reported keeps it as
plain text and explains nothing.

Every worker in the suite shares one server and so one lobby chat, so the
text each test says carries something unique.
"""
import uuid

import pytest
from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import register_account, use_guest_name

BASE_URL = "http://localhost:8000"

# A line is delivered the moment it is said, but the watcher's own baseline
# arrives on a subscription that may still be settling.
SETTLE_MS = 8000


def line_saying(page, text: str):
    return page.locator(".lobby-chat-line", has_text=text)


@pytest.mark.asyncio
async def test_a_registered_player_reports_a_lobby_line_by_its_author():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        reporter_context = await browser.new_context()
        speaker_context = await browser.new_context()
        reporter = await reporter_context.new_page()
        speaker = await speaker_context.new_page()
        reporter.set_default_timeout(10000)
        speaker.set_default_timeout(10000)
        tag = uuid.uuid4().hex[:8]
        said = f"something worth a second look {tag}"
        replied = f"reporting that {tag}"

        try:
            await reporter.goto(BASE_URL)
            await use_guest_name(reporter, f"LineReporter{tag[:4]}")
            # Reporting needs an account a moderator can follow up with; a
            # guest is offered no control (R-MOD-06).
            await register_account(reporter, f"LineReporter{tag[:4]}")

            await speaker.goto(BASE_URL)
            await use_guest_name(speaker, "LineSpeaker")
            composer = speaker.locator(".lobby-chat-form input")
            await composer.fill(said)
            await composer.press("Enter")

            # The speaker's own line offers them nothing; nor does anyone
            # else's, because they are a guest.
            own = line_saying(speaker, said)
            await expect(own).to_be_visible(timeout=SETTLE_MS)
            assert await own.locator(".lobby-chat-author").count() == 0

            reporter_composer = reporter.locator(".lobby-chat-form input")
            await reporter_composer.fill(replied)
            await reporter_composer.press("Enter")
            mine = line_saying(reporter, replied)
            await expect(mine).to_be_visible(timeout=SETTLE_MS)
            assert await mine.locator(".lobby-chat-author").count() == 0
            theirs_seen_by_guest = line_saying(speaker, replied)
            await expect(theirs_seen_by_guest).to_be_visible(timeout=SETTLE_MS)
            assert await theirs_seen_by_guest.locator(".lobby-chat-author").count() == 0

            # The speaker's line, seen by a registered account: the name is
            # the way to report it, and reads as such to a screen reader.
            theirs = line_saying(reporter, said)
            await expect(theirs).to_be_visible(timeout=SETTLE_MS)
            author = theirs.get_by_role("button", name="Report this line by LineSpeaker")
            await expect(author).to_be_visible()
            await expect(author).to_have_text("LineSpeaker:")
            await author.click()

            dialog = reporter.get_by_test_id("report-lobby-line-dialog")
            await dialog.wait_for(state="visible")
            # Portalled out of the panel, like the room's report dialog.
            assert await reporter.evaluate(
                """() => {
                    const overlay = document.querySelector('.report-player-overlay');
                    return overlay?.parentElement === document.body;
                }"""
            )
            # The reporter sees exactly what they are citing.
            await expect(dialog.get_by_test_id("report-quoted-line")).to_contain_text(said)
            await expect(dialog.get_by_test_id("report-quoted-line")).to_contain_text(
                "LineSpeaker"
            )
            # Words, not drawings: the reasons about a picture or play are
            # not on offer.
            reasons = await dialog.locator("select option").all_inner_texts()
            assert reasons == ["Harassment or abuse", "Spam", "Inappropriate name"]

            # The line is the complaint; nothing more has to be typed.
            await dialog.get_by_role("button", name="Send report").click()
            await expect(reporter.locator('.modal-card:has-text("Report sent")')).to_be_visible()
            await reporter.get_by_role("button", name="Done").click()
            await expect(dialog).to_be_hidden()

            # One open report per target (R-MOD-05): saying it again is
            # refused by the server, and the refusal is shown, not swallowed.
            await author.click()
            dialog = reporter.get_by_test_id("report-lobby-line-dialog")
            await dialog.wait_for(state="visible")
            await dialog.locator("textarea").fill("Again.")
            await dialog.get_by_role("button", name="Send report").click()
            await expect(dialog.get_by_role("alert")).to_contain_text("already reported")
            await dialog.get_by_role("button", name="Cancel").click()
            await expect(dialog).to_be_hidden()
        finally:
            await speaker_context.close()
            await reporter_context.close()
            await browser.close()
