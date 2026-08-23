"""A player saves, revises, and shares reusable prompt content."""
import pytest
from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import register_account, use_guest_name

BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_registered_owner_can_manage_and_share_a_prompt_list():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        owner_context = await browser.new_context()
        recipient_context = await browser.new_context()
        owner = await owner_context.new_page()
        recipient = await recipient_context.new_page()
        try:
            await owner.goto(BASE_URL)
            await register_account(owner, "PromptListOwner")
            await owner.locator(".identity-chip").click()
            await owner.get_by_role("menuitem", name="My prompt lists").click()
            await owner.wait_for_url("**/my-prompt-lists")
            await owner.get_by_role("heading", name="Reusable prompt lists").wait_for()

            await owner.get_by_label("Name").fill("Party animals")
            await owner.get_by_label("Description").fill("For Friday games")
            # Prompts arrive in batches, and a batch merges into what is
            # already there rather than replacing it.
            await owner.get_by_label("Add prompts", exact=True).fill("red panda, capybara")
            await owner.get_by_role("button", name="Add to list").click()
            await owner.get_by_role("button", name="Remove red panda").wait_for()
            await owner.get_by_role("button", name="Remove capybara").wait_for()
            await owner.get_by_role("button", name="Save list").click()
            await owner.get_by_text("Prompt list saved.").wait_for()
            await owner.locator("aside").get_by_text("2 prompts · private").wait_for()

            # A subsequent save creates revision two and a random bearer code.
            # Re-adding an existing prompt is silently skipped, so the edit here
            # is a removal plus a fresh batch.
            await owner.get_by_role("button", name="Remove red panda").click()
            await owner.get_by_label("Add prompts", exact=True).fill("giant panda\ncapybara")
            await owner.get_by_role("button", name="Add to list").click()
            await owner.get_by_text(
                "Added 1 prompt; skipped 1 already in the list."
            ).wait_for()
            await owner.get_by_label("Visibility").select_option("unlisted")
            await owner.get_by_role("button", name="Save list").click()
            await owner.get_by_text("Prompt list saved.").wait_for()
            share_code = (await owner.locator(".prompt-list-share-code code").inner_text()).strip()
            assert len(share_code) >= 8

            # Another browser can add the Unlisted list only by presenting the
            # code, then create a room whose only selected list is that one.
            await recipient.goto(BASE_URL)
            await use_guest_name(recipient, "SharedListGuest")
            await recipient.get_by_role("button", name="Create room").click()
            await recipient.wait_for_url("**/create")
            await recipient.get_by_label("Add an unlisted list by code").fill(share_code)
            await recipient.locator(".prompt-list-share-form").get_by_role(
                "button", name="Add"
            ).click()
            shared_chip = recipient.locator(".toggle-chip").filter(
                has_text="Party animals"
            )
            await shared_chip.wait_for()
            assert await shared_chip.get_attribute("aria-pressed") == "true"

            # Shared player-authored content can be reported as a whole list or
            # as one exact immutable prompt version. Submission is post-
            # moderation, so it does not interrupt this waiting-room flow.
            await recipient.get_by_role("button", name="Report Party animals").click()
            await recipient.get_by_label("Content", exact=True).select_option(label="giant panda")
            await recipient.get_by_label("Reason").select_option("inappropriate")
            await recipient.get_by_label("What should the moderator know?").fill(
                "This exact prompt needs review."
            )
            await recipient.get_by_role("button", name="Send report").click()
            await recipient.get_by_text("Report sent for moderator review.").wait_for()

            await recipient.locator(".toggle-chip").filter(
                has_text="English — Standard"
            ).click()
            await recipient.get_by_role("button", name="Create room", exact=True).click()
            await recipient.locator('[data-testid="waiting-room"]').wait_for()
        finally:
            await owner_context.close()
            await recipient_context.close()
            await browser.close()
