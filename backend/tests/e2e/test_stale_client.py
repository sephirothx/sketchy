"""A tab whose bundle is older than the server (#476).

A stale client cannot be built from the current tree, so the diagnostics build
lets a page claim an older protocol version from `sessionStorage`; from the
server's side that is a build from before the last deploy, and everything
downstream is real: the upgrade notice, the reload it triggers, the refusals,
the timed close, the reload-once rule, and the banner when the reload did not
help. Here the claim survives the reload, which is exactly the stuck case - a
proxy ignoring `no-cache`, a service worker serving the old shell.
"""
import pytest
from playwright.async_api import async_playwright, expect

from tests.e2e.lobby_helpers import room_code, use_guest_name

BASE_URL = "http://localhost:8000"

# The override is applied on every load until the test says it has done its
# part; the banner's Reload is then a reload onto the current build.
CLAIM_STALE = """
if (!sessionStorage.getItem('sketchy:e2e-stale-done')) {
  sessionStorage.setItem('sketchy:protocol-override', '1');
}
"""


@pytest.mark.asyncio
async def test_a_stale_tab_reloads_once_then_says_it_is_out_of_date_and_recovers_by_hand():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(10000)
        await page.add_init_script(CLAIM_STALE)
        try:
            await page.goto(BASE_URL)
            # The notice reloads the page once; the reload comes back just as
            # stale, and the second notice is the one that must not reload
            # again but say so instead.
            banner = page.get_by_role("alert").filter(has_text="out of date")
            await expect(banner).to_be_visible(timeout=15000)
            reloads = await page.evaluate(
                "() => sessionStorage.getItem('sketchy:upgrade-reload')"
            )
            assert reloads is not None, "the automatic reload was never spent"

            # The socket is down for good: the server was closing it anyway,
            # and reconnecting would only be told the same thing again.
            await page.wait_for_function(
                "() => { const s = window.__SKETCHY_SOCKET__;"
                " return !!s && !s.connected && !s.io.reconnection(); }",
                timeout=8000,
            )

            # Recovery is the player's: with the bundle fixed (the override
            # gone), the banner's Reload lands on a tab that plays.
            await page.evaluate(
                "() => { sessionStorage.setItem('sketchy:e2e-stale-done', '1');"
                " sessionStorage.removeItem('sketchy:protocol-override'); }"
            )
            await banner.get_by_role("button", name="Reload").click()
            await page.wait_for_selector(".first-run, .identity-chip")
            await expect(page.get_by_role("alert").filter(has_text="out of date")).to_have_count(0)
            await use_guest_name(page, "StaleTab")
            await page.click('button:has-text("Create room")')
            await page.click('button:has-text("Create room")')
            await page.wait_for_selector('[data-testid="waiting-room"]')
            assert len(await room_code(page)) > 0
        finally:
            await context.close()
            await browser.close()
