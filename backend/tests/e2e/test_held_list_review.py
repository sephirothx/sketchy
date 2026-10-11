"""A held list's decision refused, and the refusal still on screen.

A moderator decides on the version they read (R-LIST-13's `expectedVersion`).
When the owner publishes again first, or withdraws the list, the server
refuses the decision with 409 and the page pulls the queue again so it shows
what is now there. That reload used to clear the page's error the moment it
landed, so the refusal flashed and was gone, and the moderator was left with a
list that had quietly not been released.
"""
import asyncio
from uuid import uuid4

from playwright.async_api import async_playwright, expect

from app.domain_values import UserRole
from tests.e2e.lobby_helpers import register_account, use_guest_name
from tests.e2e.publishing_helpers import confirm_email, hold_for_review
from tests.e2e.staff_helpers import set_role

BASE_URL = "http://localhost:8000"

#: Run in the owner's page; throws on any answer that is not a success, so a
#: refused edit fails here rather than as a decision that was not refused.
OWNER_FETCH = """async ({path, method, body}) => {
  const response = await fetch(path, {method, headers: {'content-type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)});
  if (!response.ok) throw new Error(`${method} ${path}: ${response.status}`);
  return await response.json();
}"""


async def _owner_fetch(owner, method: str, path: str, body=None):
    return await owner.evaluate(OWNER_FETCH, {"path": path, "method": method, "body": body})


async def _a_held_list_open_for_review(browser):
    """An owner with one held list, and a moderator reading it."""
    owner = await (await browser.new_context()).new_page()
    moderator = await (await browser.new_context()).new_page()
    for page in (owner, moderator):
        page.set_default_timeout(15000)
    # Unique per run: the accounts and the list outlive it in the server's
    # database, and the queue is server-wide.
    tag = uuid4().hex[:8]
    name = f"Held {tag}"
    author = f"Owner{tag}"
    await owner.goto(BASE_URL)
    await register_account(owner, author)
    await confirm_email(author)
    created = await _owner_fetch(
        owner, "POST", "/api/prompt-lists/mine",
        {"name": name, "language": "en", "prompts": [{"prompt": "otter"}]},
    )
    await _owner_fetch(owner, "POST", f"/api/prompt-lists/mine/{created['id']}/publish")
    await hold_for_review(created["id"])

    reviewer = f"Mod{tag}"
    await moderator.goto(BASE_URL)
    await use_guest_name(moderator, reviewer)
    await register_account(moderator, reviewer)
    await set_role(reviewer, UserRole.MODERATOR.value)
    await moderator.goto(f"{BASE_URL}/moderation")
    case = moderator.locator(".mod-queue-item", has_text=name)
    await case.click()
    await moderator.get_by_text("This decides version 1.").wait_for()
    return owner, moderator, created, case


async def _release_refused(moderator, list_id: str, note: str) -> None:
    await moderator.locator(".mod-note textarea").fill(note)
    async with moderator.expect_response(
        lambda response: response.request.method == "PATCH"
        and f"/api/moderation/prompt-lists/{list_id}" in response.url
    ) as answer:
        await moderator.locator(".mod-actions").get_by_role("button", name="Release").click()
    assert (await answer.value).status == 409


async def test_a_stale_held_decision_keeps_its_refusal_after_the_reload():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        try:
            owner, moderator, created, _ = await _a_held_list_open_for_review(browser)

            # The owner publishes again while the moderator reads: what they
            # read is no longer what a release would put out.
            list_id = created["id"]
            await _owner_fetch(
                owner, "PUT", f"/api/prompt-lists/mine/{list_id}",
                {"expectedVersion": created["version"], "name": created["name"],
                 "description": "", "prompts": [{"prompt": "badger"}]},
            )
            await _owner_fetch(owner, "POST", f"/api/prompt-lists/mine/{list_id}/publish")
            await hold_for_review(list_id)

            await _release_refused(moderator, list_id, "Read it, it is fine.")

            # The reload the refusal starts, and the re-read after it, have
            # both landed once the new version is on screen - and the refusal
            # is still there to say why.
            await moderator.get_by_text("This decides version 2.").wait_for()
            refusal = moderator.get_by_role("alert").filter(
                has_text="This list changed after you opened it."
            )
            await expect(refusal).to_have_count(1)

            # Acting again is what clears it, and this time the decision takes.
            await moderator.locator(".mod-note textarea").fill("Read it again, still fine.")
            await moderator.locator(".mod-actions").get_by_role("button", name="Release").click()
            await moderator.get_by_role("status").filter(
                has_text="Released into the community catalogue."
            ).wait_for()
            await expect(refusal).to_have_count(0)
        finally:
            await browser.close()


async def test_a_decision_on_a_withdrawn_list_keeps_its_refusal():
    """The list leaves the queue with the reload, and its re-read is refused
    too: neither may take the decision's refusal with it."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        try:
            owner, moderator, created, case = await _a_held_list_open_for_review(browser)
            await _owner_fetch(
                owner, "POST", f"/api/prompt-lists/mine/{created['id']}/unpublish"
            )

            # The queue's reload is held back a moment, so the list's own
            # re-read - refused too, since the list is no longer held - lands
            # first. That order is the one where the reload landing last took
            # the refusal off screen; left to chance, the run usually took the
            # other.
            async def slow_queue(route):
                await asyncio.sleep(1.5)
                await route.continue_()

            await moderator.route(
                lambda url: url.split("?")[0].endswith("/api/moderation/prompt-lists"),
                slow_queue,
            )
            await _release_refused(moderator, created["id"], "Read it, it is fine.")

            # Gone from the queue means the reload has landed.
            await case.wait_for(state="detached")
            await expect(
                moderator.get_by_role("alert").filter(
                    has_text="That prompt list is not awaiting review."
                )
            ).to_have_count(1)
        finally:
            await browser.close()
