"""A player saves and revises reusable prompt content, and plays it."""
from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import choose_room_language, register_account

BASE_URL = "http://localhost:8000"


def list_checkbox(page, name: str):
    """A list's checkbox in the room form's tree, by the list's name (#1388)."""
    return page.locator(".prompt-list-check").filter(has_text=name).locator("input")


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
            await choose_room_language(owner, "en")
            await owner.click('summary:has-text("Prompts")')
            # The player's own lists are a branch of the tree (#1388), folded
            # while nothing on it is chosen.
            await owner.get_by_role("button", name="Your lists").click()
            owned = list_checkbox(owner, "Party animals")
            await owned.check()
            assert await owned.is_checked()
            await list_checkbox(owner, "English — Standard").uncheck()
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

            # Chosen while the room is still English, then carried when the
            # host switches the room to German: the list has no language to
            # leave behind, so it stays chosen beside German's Standard list.
            await owner.goto(f"{BASE_URL}/create")
            # Private: a public German room left waiting is one another test's
            # German Quick play would land in (e2e global server state).
            await owner.get_by_role("button", name="Private").click()
            await choose_room_language(owner, "en")
            await owner.click('summary:has-text("Prompts")')
            await owner.get_by_role("button", name="Your lists").click()
            names_row = owner.locator(".prompt-list-check").filter(has_text="Pocket monsters")
            await names_row.wait_for()
            assert await names_row.get_by_text("Any language").count() == 1
            names = list_checkbox(owner, "Pocket monsters")
            await names.check()
            assert await names.is_checked()
            await owner.get_by_role("button", name="Prompt language: English").click()
            await owner.get_by_role("option", name="Deutsch").click()
            await owner.get_by_role("button", name="Prompt language: Deutsch").wait_for()
            assert await names.is_checked()
            assert await list_checkbox(owner, "Deutsch — Standard").is_checked()
            assert await owner.locator(".prompt-list-check").filter(
                has_text="English — Standard"
            ).count() == 0
            await owner.get_by_role("button", name="Create room", exact=True).click()
            await owner.locator('[data-testid="waiting-room"]').wait_for()
        finally:
            await context.close()
            await browser.close()


async def test_a_new_list_opens_in_the_players_play_language():
    """#1272: every new list opened on English, and a list's language is fixed
    at its first save (R-LIST-05) - a German player's first list, saved without
    a look at the picker, was English for good. Both ways in - the first list
    and New list - open on the player's default play language."""
    from uuid import uuid4

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        await context.add_init_script("localStorage.setItem('sketchy_promptlanguage', 'de')")
        owner = await context.new_page()
        try:
            await owner.goto(BASE_URL)
            await register_account(owner, f"Listy{uuid4().hex[:6]}")
            await owner.goto(f"{BASE_URL}/my-prompt-lists")
            picker = owner.locator(".prompt-list-language .language-picker-trigger")
            await picker.wait_for()
            assert "Deutsch" in await picker.inner_text()

            await owner.get_by_label("Name").fill("Tiere")
            await owner.get_by_label("Add prompts", exact=True).fill("Hund, Katze")
            await owner.get_by_role("button", name="Add to list").click()
            await owner.get_by_role("button", name="Save list").click()
            await owner.locator(".app-toast").get_by_text("Prompt list saved.").wait_for()

            await owner.get_by_role("button", name="New list").click()
            await owner.get_by_label("Name").wait_for()
            assert await owner.get_by_label("Name").input_value() == ""
            assert "Deutsch" in await picker.inner_text()
        finally:
            await context.close()
            await browser.close()


async def test_signing_in_on_the_page_moves_a_new_list_to_the_accounts_language():
    """Review of #1272: the draft was built once, from this browser's default,
    so a German account signing in from the page's own dialog on a fresh
    English browser still got a first list on English."""
    from uuid import uuid4

    name = f"Konto{uuid4().hex[:6]}"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        owner_context = await browser.new_context()
        await owner_context.add_init_script("localStorage.setItem('sketchy_promptlanguage', 'de')")
        visitor_context = await browser.new_context()
        try:
            owner = await owner_context.new_page()
            await owner.goto(BASE_URL)
            await register_account(owner, name)
            await owner_context.close()

            page = await visitor_context.new_page()
            await page.goto(f"{BASE_URL}/my-prompt-lists")
            await page.get_by_role("button", name="Create account").click()
            dialog = page.get_by_role("dialog", name="Create your account")
            await dialog.wait_for()
            await dialog.get_by_role("button", name="Sign in").click()
            sign_in = page.get_by_role("dialog", name="Sign in")
            await sign_in.wait_for()
            inputs = sign_in.locator("input")
            await inputs.nth(0).fill(name)
            await inputs.nth(1).fill("a-good-password")
            await sign_in.locator('button[type="submit"]').click()
            await sign_in.wait_for(state="hidden")
            picker = page.locator(".prompt-list-language .language-picker-trigger")
            await picker.wait_for()
            await page.wait_for_function(
                "() => document.querySelector('.prompt-list-language .language-picker-trigger')"
                "?.textContent?.includes('Deutsch')"
            )
        finally:
            await visitor_context.close()
            await browser.close()
