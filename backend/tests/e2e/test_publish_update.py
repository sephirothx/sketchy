"""A published list's edits reach players only through Publish update (#1363).

Publishing freezes the list as an edition (#1360): other players' rooms play
that edition while its owner keeps editing. The editor says so - Unpublished
changes - and offers Publish update, after saying what it changes, or Discard
changes.
"""
import asyncio
from uuid import uuid4

from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import (
    join_by_code,
    register_account,
    room_code,
    use_guest_name,
)
from tests.e2e.publishing_helpers import confirm_email

BASE_URL = "http://localhost:8000"
FIRST = {"lighthouse", "harbour", "seagull"}
UPDATED = {"volcano", "glacier", "canyon"}


async def _open_my_list(page, name: str) -> None:
    await page.goto(f"{BASE_URL}/my-prompt-lists")
    await page.get_by_role("heading", name="My prompt lists").wait_for()
    await page.locator("aside button").filter(has_text=name).click()
    await page.get_by_label("Name").wait_for()


async def _replace_prompts(page, prompts: set[str], remove: set[str]) -> None:
    for prompt in remove:
        await page.get_by_role("button", name=f"Remove {prompt}").click()
    await page.get_by_label("Add prompts", exact=True).fill(", ".join(sorted(prompts)))
    await page.get_by_role("button", name="Add to list").click()
    await page.get_by_role("button", name="Save list").click()
    await page.locator(".app-toast").get_by_text("Prompt list saved.").wait_for()


async def _choices_in_a_new_room(host, guest, list_id: str) -> set[str]:
    """The prompts the first drawer is offered, in a room the stranger hosts
    on this list alone - so the room plays the live edition."""
    await host.goto(f"{BASE_URL}/create?list={list_id}")
    await host.click('summary:has-text("Prompts")')
    await host.locator(".toggle-chip[aria-pressed='true']").filter(has_text="Shore words").wait_for()
    # Only this list: nothing built-in mixed in.
    standard = host.locator(".toggle-chip[aria-pressed='true']").filter(has_text="Standard")
    if await standard.count():
        await standard.first.click()
    await host.locator(".create-room-submit").click()
    await host.locator('[data-testid="waiting-room"]').wait_for()
    code = await room_code(host)
    await guest.goto(BASE_URL)
    await join_by_code(guest, code)
    await guest.locator('[data-testid="waiting-room"]').wait_for()
    await host.click('button:has-text("Start game")')
    await host.wait_for_selector(".game-layout")
    await guest.wait_for_selector(".game-layout")
    # Polled on both pages: either may draw first, and the drawer's choices
    # can land a moment after the layout does.
    drawer = None
    for _ in range(150):
        for page in (host, guest):
            if await page.locator(".prompt-choices button").count():
                drawer = page
                break
        if drawer:
            break
        await asyncio.sleep(0.1)
    assert drawer is not None, "no drawer received prompt choices"
    return {text.strip() for text in await drawer.locator(".prompt-choices button").all_inner_texts()}


async def test_an_edit_reaches_other_rooms_only_after_publish_update():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        owner_context = await browser.new_context()
        stranger_context = await browser.new_context()
        owner = await owner_context.new_page()
        stranger = await stranger_context.new_page()
        owner.set_default_timeout(15000)
        stranger.set_default_timeout(15000)
        try:
            await owner.goto(BASE_URL)
            # Unique per run: the account outlives it in the server's database.
            author = f"Author{uuid4().hex[:8]}"
            await register_account(owner, author)
            await confirm_email(author)
            await owner.goto(f"{BASE_URL}/my-prompt-lists")
            await owner.get_by_role("heading", name="My prompt lists").wait_for()
            await owner.get_by_label("Name").fill("Shore words")
            await owner.get_by_label("Add prompts", exact=True).fill(", ".join(sorted(FIRST)))
            await owner.get_by_role("button", name="Add to list").click()
            await owner.get_by_role("button", name="Save list").click()
            await owner.locator(".app-toast").get_by_text("Prompt list saved.").wait_for()
            publication = owner.locator(".prompt-list-publication")
            await publication.get_by_role("button", name="Publish", exact=True).click()
            await owner.locator(".app-toast").get_by_text("Prompt list published.").wait_for()
            await publication.get_by_text("In the community catalogue").wait_for()
            list_id = await owner.evaluate(
                """async () => (await (await fetch('/api/prompt-lists/mine')).json())
                     .find((list) => list.name === 'Shore words').id"""
            )

            # An edit, saved: the editor says players do not see it yet.
            await _replace_prompts(owner, UPDATED, FIRST)
            await publication.get_by_text("Unpublished changes").wait_for()

            # Discard changes puts back exactly what players see...
            await publication.get_by_role("button", name="Discard changes").click()
            await owner.get_by_role("alertdialog").get_by_role("button", name="Discard changes").click()
            await owner.locator(".app-toast").get_by_text("Changes discarded.").wait_for()
            for prompt in FIRST:
                await owner.get_by_role("button", name=f"Remove {prompt}").wait_for()
            await publication.get_by_text("In the community catalogue").wait_for()
            # ...and the edit again, this time to publish.
            await _replace_prompts(owner, UPDATED, FIRST)
            await publication.get_by_text("Unpublished changes").wait_for()

            await stranger.goto(BASE_URL)
            await use_guest_name(stranger, f"Stranger{uuid4().hex[:6]}")
            offered = await _choices_in_a_new_room(stranger, owner, list_id)
            assert offered and offered <= FIRST, offered

            # Publish update says what it changes before it does it.
            await _open_my_list(owner, "Shore words")
            await publication.get_by_role("button", name="Publish update").click()
            dialog = owner.get_by_role("alertdialog")
            await dialog.get_by_text("Added (3)").wait_for()
            await dialog.get_by_text("Removed (3)", exact=False).wait_for()
            await dialog.get_by_role("button", name="Publish update").click()
            await owner.locator(".app-toast").get_by_text("Update published.").wait_for()
            await publication.get_by_text("In the community catalogue").wait_for()

            offered = await _choices_in_a_new_room(stranger, owner, list_id)
            assert offered and offered <= UPDATED, offered
        finally:
            await owner_context.close()
            await stranger_context.close()
            await browser.close()
