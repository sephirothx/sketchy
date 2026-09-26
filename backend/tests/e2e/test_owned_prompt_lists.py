"""A player saves and revises reusable prompt content, and plays it."""
from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import register_account

BASE_URL = "http://localhost:8000"


async def test_registered_owner_can_manage_and_play_a_private_prompt_list():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        owner = await context.new_page()
        try:
            await owner.goto(BASE_URL)
            await register_account(owner, "PromptListOwner")
            await owner.locator(".identity-chip").click()
            await owner.get_by_role("menuitem", name="My prompt lists").click()
            await owner.wait_for_url("**/my-prompt-lists")
            await owner.get_by_role("heading", name="My prompt lists").wait_for()

            # A list is private or published, and publishing is the only way
            # between them (R-LIST-02): there is no visibility field to set.
            # This account has no confirmed email, which publishing needs
            # (R-LIST-12), and the panel says so before Publish is ever
            # pressed. The E2E server sends no mail, so it cannot offer to add
            # an address either - an address nobody can confirm unlocks nothing.
            assert await owner.get_by_label("Visibility").count() == 0
            publication = owner.locator(".prompt-list-publication")
            await publication.get_by_text(
                "Publishing needs a confirmed email address, and this server cannot send email."
            ).wait_for()
            assert await publication.get_by_role("button", name="Add an email").count() == 0
            assert await publication.get_by_role("button", name="Publish", exact=True).is_disabled()

            await owner.get_by_label("Name").fill("Party animals")
            await owner.get_by_label("Description").fill("For Friday games")
            # Prompts arrive in batches, and a batch merges into what is
            # already there rather than replacing it.
            await owner.get_by_label("Add prompts", exact=True).fill("red panda, capybara")
            await owner.get_by_role("button", name="Add to list").click()
            await owner.get_by_role("button", name="Remove red panda").wait_for()
            await owner.get_by_role("button", name="Remove capybara").wait_for()
            await owner.get_by_role("button", name="Save list").click()
            await owner.locator(".app-toast").get_by_text("Prompt list saved.").wait_for()
            await owner.locator("aside").get_by_text("2 prompts · private").wait_for()
            # Saving is not what stands in the way; the address still is.
            assert await publication.get_by_role("button", name="Publish", exact=True).is_disabled()

            # A subsequent save creates revision two and leaves the list
            # private. Re-adding an existing prompt is silently skipped, so the
            # edit here is a removal plus a fresh batch.
            await owner.get_by_role("button", name="Remove red panda").click()
            await owner.get_by_label("Add prompts", exact=True).fill("giant panda\ncapybara")
            await owner.get_by_role("button", name="Add to list").click()
            await owner.get_by_text(
                "Added 1 prompt; skipped 1 already in the list."
            ).wait_for()
            await owner.get_by_role("button", name="Save list").click()
            await owner.locator(".app-toast").get_by_text("Prompt list saved.").wait_for()
            await owner.locator("aside").get_by_text("2 prompts · private").wait_for()

            # Its owner can play it: a room whose only selected list is this one.
            await owner.goto(f"{BASE_URL}/create")
            await owner.click('summary:has-text("Prompts")')
            owned_chip = owner.locator(".toggle-chip").filter(has_text="Party animals")
            await owned_chip.click()
            assert await owned_chip.get_attribute("aria-pressed") == "true"
            await owner.locator(".toggle-chip").filter(
                has_text="English — Standard"
            ).click()
            await owner.get_by_role("button", name="Create room", exact=True).click()
            await owner.locator('[data-testid="waiting-room"]').wait_for()
        finally:
            await context.close()
            await browser.close()


async def test_a_list_in_any_language_is_offered_to_a_room_in_another_language():
    """A list of names is not in a language (#821, R-PROMPT-12): saved once as
    Any language, it is offered to a German room beside German's own lists."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        owner = await context.new_page()
        try:
            await owner.goto(BASE_URL)
            await register_account(owner, "AnyLanguageOwner")
            await owner.goto(f"{BASE_URL}/my-prompt-lists")
            await owner.get_by_role("heading", name="My prompt lists").wait_for()

            await owner.get_by_label("Name").fill("Pocket monsters")
            await owner.get_by_role("button", name="Language: English").click()
            await owner.get_by_role("option", name="Any language").click()
            await owner.get_by_label("Add prompts", exact=True).fill("Pikachu, Bulbasaur")
            await owner.get_by_role("button", name="Add to list").click()
            await owner.get_by_role("button", name="Remove Pikachu").wait_for()
            await owner.get_by_role("button", name="Save list").click()
            await owner.locator(".app-toast").get_by_text("Prompt list saved.").wait_for()
            # Fixed once saved, like any list's language (R-LIST-05).
            await owner.locator(".prompt-list-language").get_by_text("Any language").wait_for()

            await owner.goto(f"{BASE_URL}/create")
            await owner.get_by_role("button", name="Prompt language: English").click()
            await owner.get_by_role("option", name="Deutsch").click()
            await owner.click('summary:has-text("Prompts")')
            names_chip = owner.locator(".toggle-chip").filter(has_text="Pocket monsters")
            await names_chip.wait_for()
            assert await names_chip.get_by_text("Any language").count() == 1
            await names_chip.click()
            assert await names_chip.get_attribute("aria-pressed") == "true"
            await owner.locator(".toggle-chip").filter(has_text="Deutsch — Standard").click()
            await owner.get_by_role("button", name="Create room", exact=True).click()
            await owner.locator('[data-testid="waiting-room"]').wait_for()
        finally:
            await context.close()
            await browser.close()
