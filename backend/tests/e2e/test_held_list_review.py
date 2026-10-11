"""A held list's decision refused as stale, and the refusal still on screen.

A moderator decides on the version they read (R-LIST-05's optimistic
concurrency, applied to R-LIST-13's review queue). When the owner publishes
again first, the server refuses the decision with 409 and the page pulls the
queue again so the next decision can name the new version. That reload used to
clear the page's error the moment it landed, so the refusal flashed and was
gone, and the moderator was left with a list that had quietly not been
released.
"""
from uuid import uuid4

from playwright.async_api import async_playwright, expect

from app.domain_values import UserRole
from tests.e2e.lobby_helpers import register_account, use_guest_name
from tests.e2e.publishing_helpers import confirm_email, hold_for_review
from tests.e2e.staff_helpers import set_role

BASE_URL = "http://localhost:8000"
STALE = "This list changed after you opened it."


async def test_a_stale_held_decision_keeps_its_refusal_after_the_reload():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        owner = await (await browser.new_context()).new_page()
        moderator = await (await browser.new_context()).new_page()
        for page in (owner, moderator):
            page.set_default_timeout(15000)
        try:
            # Unique per run: the accounts and the list outlive it in the
            # server's database, and the queue is server-wide.
            tag = uuid4().hex[:8]
            name = f"Held {tag}"
            author = f"Owner{tag}"
            await owner.goto(BASE_URL)
            await register_account(owner, author)
            await confirm_email(author)
            created = await owner.evaluate(
                """async (name) => {
                  const h = {'content-type': 'application/json'};
                  const list = await (await fetch('/api/prompt-lists/mine', {method: 'POST',
                    headers: h, body: JSON.stringify({name, language: 'en',
                      prompts: [{prompt: 'otter'}]})})).json();
                  await fetch(`/api/prompt-lists/mine/${list.id}/publish`, {method: 'POST'});
                  return list;
                }""",
                name,
            )
            await hold_for_review(created["id"])

            reviewer = f"Mod{tag}"
            await moderator.goto(BASE_URL)
            await use_guest_name(moderator, reviewer)
            await register_account(moderator, reviewer)
            await set_role(reviewer, UserRole.MODERATOR.value)
            await moderator.goto(f"{BASE_URL}/moderation")
            await moderator.locator(".mod-queue-item", has_text=name).click()
            await moderator.get_by_text("This decides version 1.").wait_for()

            # The owner publishes again while the moderator reads: what they
            # read is no longer what a release would put out.
            await owner.evaluate(
                """async ({id, version, name}) => {
                  const h = {'content-type': 'application/json'};
                  await fetch(`/api/prompt-lists/mine/${id}`, {method: 'PUT', headers: h,
                    body: JSON.stringify({expectedVersion: version, name, description: '',
                      prompts: [{prompt: 'badger'}]})});
                  await fetch(`/api/prompt-lists/mine/${id}/publish`, {method: 'POST'});
                }""",
                {"id": created["id"], "version": created["version"], "name": name},
            )
            await hold_for_review(created["id"])

            await moderator.locator(".mod-note textarea").fill("Read it, it is fine.")
            async with moderator.expect_response(
                lambda response: response.request.method == "PATCH"
                and f"/api/moderation/prompt-lists/{created['id']}" in response.url
            ) as refused:
                await moderator.locator(".mod-actions").get_by_role("button", name="Release").click()
            assert (await refused.value).status == 409

            # The reload the refusal starts has landed once the new version is
            # on screen - and the refusal is still there to say why.
            await moderator.get_by_text("This decides version 2.").wait_for()
            # The page's own error line: other notes on the page may be alerts too.
            alert = moderator.locator(".auth-error[role=alert]")
            await expect(alert).to_contain_text(STALE)
            # Not only at that instant: a reload could still be in flight.
            await moderator.wait_for_timeout(1000)
            await expect(alert).to_contain_text(STALE)

            # Acting again is what clears it, and this time the decision takes.
            await moderator.locator(".mod-note textarea").fill("Read it again, still fine.")
            await moderator.locator(".mod-actions").get_by_role("button", name="Release").click()
            await moderator.get_by_role("status").filter(
                has_text="Released into the community catalogue."
            ).wait_for()
            await expect(alert).to_have_count(0)
        finally:
            await browser.close()
