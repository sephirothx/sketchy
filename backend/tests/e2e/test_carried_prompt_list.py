"""A list carried from the catalogue's Play stays chosen however its read lands.

Create room reads two things on arrival: the picker's catalogue and the carried
list itself. The catalogue is reported back to the page from an effect, and if
the carried list landed after the catalogue had rendered but before that effect
ran, the report reconciled the carried selection against the language the page
had *before* the list arrived - Mixed, where a player list cannot be played - and
put Standard back. The flake behind `test_publish_update.py` on CI.

The window is a fraction of a frame wide, so this test holds it open: the page's
`fetch` keeps the carried list back until the DOM mutation that is the
catalogue's commit, and hands it over in that mutation's microtask, before
React's scheduled passive effects can run.
"""
from uuid import uuid4

from playwright.async_api import async_playwright, expect

from tests.e2e.lobby_helpers import register_account, use_guest_name
from tests.e2e.publishing_helpers import confirm_email

BASE_URL = "http://localhost:8000"

# Holds the carried list's read until the catalogue has been handed to the app
# and its render has touched the DOM, then answers in that mutation's
# microtask. `window.__carriedRace` says whether the order was arranged, so a
# pass that never opened the window cannot pass for a fix.
LAND_BETWEEN_COMMIT_AND_EFFECTS = """
(() => {
  const realFetch = window.fetch.bind(window);
  const race = (window.__carriedRace = { arranged: false });
  let carriedReady;
  const carried = new Promise((resolve) => { carriedReady = resolve; });
  let release;
  const released = new Promise((resolve) => { release = resolve; });
  const answer = (response, text) => ({
    ok: response.ok,
    status: response.status,
    headers: response.headers,
    text: () => Promise.resolve(text),
  });
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (/^\\/api\\/prompt-lists\\/community\\/[^/]+$/.test(url.pathname) && !url.search) {
      const response = await realFetch(input, init);
      const text = await response.text();
      carriedReady();
      await released;
      return answer(response, text);
    }
    if (url.pathname === "/api/prompt-lists" && !url.search) {
      const response = await realFetch(input, init);
      const text = await response.text();
      await carried;
      // The next DOM mutation is the catalogue's commit; its observer runs as
      // a microtask of the task that committed, ahead of the passive effects.
      const observer = new MutationObserver(() => {
        observer.disconnect();
        race.arranged = true;
        release();
      });
      observer.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
      return answer(response, text);
    }
    return realFetch(input, init);
  };
})();
"""


async def test_a_carried_list_landing_after_the_catalogue_render_stays_chosen():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        try:
            owner = await (await browser.new_context()).new_page()
            owner.set_default_timeout(15000)
            await owner.goto(BASE_URL)
            author = f"Author{uuid4().hex[:8]}"
            await register_account(owner, author)
            await confirm_email(author)
            list_id = await owner.evaluate(
                """async () => {
                  const created = await (await fetch('/api/prompt-lists/mine', {
                    method: 'POST', headers: {'content-type': 'application/json'},
                    body: JSON.stringify({name: 'Tide words', language: 'en',
                      prompts: [{prompt: 'lighthouse'}, {prompt: 'harbour'}, {prompt: 'seagull'}]}),
                  })).json();
                  const published = await fetch(`/api/prompt-lists/mine/${created.id}/publish`, {method: 'POST'});
                  if (!published.ok) throw new Error(`publish answered ${published.status}`);
                  return created.id;
                }"""
            )

            context = await browser.new_context()
            host = await context.new_page()
            host.set_default_timeout(15000)
            await host.goto(BASE_URL)
            await use_guest_name(host, f"Host{uuid4().hex[:6]}")
            await context.add_init_script(LAND_BETWEEN_COMMIT_AND_EFFECTS)
            await host.goto(f"{BASE_URL}/create?list={list_id}")
            await host.click('summary:has-text("Prompts")')
            await host.wait_for_function("() => window.__carriedRace?.arranged")
            # The list has arrived; its branch opens only if it is the choice.
            await host.get_by_text("From the community catalogue").wait_for()
            await expect(host.locator(".create-room-language-field")).to_contain_text("English")
            checks = host.locator(".prompt-list-check")
            await expect(checks.filter(has_text="Tide words").locator("input")).to_be_checked()
            # Nothing built-in put back beside it.
            await expect(checks.locator("input:checked")).to_have_count(1)
        finally:
            await browser.close()
