"""A moderator hides a reported lobby line from the case, every open lobby
shows "This message was deleted" in its place at once, and showing it again
brings the words back (#1435, R-LCHAT-09).

Every worker in the suite shares one lobby chat, so the line carries
something unique."""
import uuid

from playwright.async_api import async_playwright, expect

from app.domain_values import UserRole
from tests.e2e.lobby_helpers import BASE_URL, register_account, use_guest_name
from tests.e2e.staff_helpers import set_role

SETTLE_MS = 8000


async def test_a_moderator_hides_a_reported_lobby_line_and_shows_it_again():
    tag = uuid.uuid4().hex[:6]
    said = f"something to hide {tag}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        speaker = await (await browser.new_context()).new_page()
        reporter = await (await browser.new_context()).new_page()
        moderator = await (await browser.new_context()).new_page()
        try:
            await speaker.goto(BASE_URL)
            await use_guest_name(speaker, f"HSpeak{tag}")
            await register_account(speaker, f"HSpeak{tag}")
            await reporter.goto(BASE_URL)
            await use_guest_name(reporter, f"HReport{tag}")
            await register_account(reporter, f"HReport{tag}")

            composer = speaker.locator(".lobby-chat-form input")
            await composer.fill(said)
            await composer.press("Enter")
            line = reporter.locator(".lobby-chat-line", has_text=said)
            await expect(line).to_be_visible(timeout=SETTLE_MS)
            await line.get_by_role("button", name=f"Report this line by HSpeak{tag}").click()
            dialog = reporter.get_by_test_id("report-lobby-line-dialog")
            await dialog.get_by_role("button", name="Send report").click()
            await dialog.get_by_role("button", name="Close").click()

            await moderator.goto(BASE_URL)
            await use_guest_name(moderator, f"HMod{tag}")
            await register_account(moderator, f"HMod{tag}")
            await set_role(f"HMod{tag}", UserRole.MODERATOR.value)
            await moderator.goto(f"{BASE_URL}/moderation")
            await moderator.locator(".mod-queue-item", has_text=f"HSpeak{tag}").click()
            await moderator.locator(".mod-line-note input").fill("Abusive in the lobby")
            toggle = moderator.get_by_test_id("mod-evidence-line").filter(has_text=said).get_by_test_id(
                "mod-line-toggle"
            )
            await toggle.click()
            await expect(moderator.get_by_role("status").filter(has_text="Hidden")).to_be_visible()

            # Every open lobby, the author's included: the placeholder in its
            # place, set apart, and the words nowhere on the page.
            for page in (reporter, speaker):
                # Scoped to this speaker: the lobby is shared with every other test.
                placeholder = page.locator(".lobby-chat-line", has_text=f"HSpeak{tag}:").locator(
                    ".lobby-chat-deleted", has_text="This message was deleted."
                )
                await expect(placeholder).to_be_visible(timeout=SETTLE_MS)
                assert await placeholder.evaluate("el => getComputedStyle(el).fontStyle") == "italic"
                await expect(page.locator(".lobby-chat-line", has_text=said)).to_have_count(0)

            # Shown again, with its own note - each decision is ledgered with
            # why: the words come back where they were.
            await expect(toggle).to_have_text("Show again")
            await moderator.locator(".mod-line-note input").fill("Hidden by mistake")
            await toggle.click()
            await expect(reporter.locator(".lobby-chat-line", has_text=said)).to_be_visible(timeout=SETTLE_MS)
            await expect(
                reporter.locator(".lobby-chat-line", has_text=f"HSpeak{tag}:").locator(".lobby-chat-deleted")
            ).to_have_count(0)
        finally:
            await browser.close()
