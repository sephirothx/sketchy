"""Every text field is 16px or more on a phone, so iOS never zooms on focus.

iOS Safari zooms the page when it focuses a field whose computed font size is
under 16px, and stays zoomed after the keyboard closes until the player
pinches out: the lobby, the waiting room and Create room were left panned
sideways, and the playing room re-laid itself out at ~356 of 393 CSS px. On
an emulated iPhone 15, 15 of 20 visible fields were under 16px - the guess
field among them, so every iPhone guesser met it on their first guess (#1264).

The fix is not `maximum-scale=1` in the viewport meta: Android Chrome honours
it, and it takes pinch-zoom away from everyone.
"""
from uuid import uuid4

from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import (
    join_by_code,
    open_create_room,
    open_player_settings,
    open_public_rooms,
    open_room_settings,
    register_account,
    room_code,
    save_room_settings,
    use_guest_name,
)

BASE_URL = "http://localhost:8000"
PHONE = {
    "viewport": {"width": 390, "height": 844},
    "is_mobile": True,
    "has_touch": True,
    "device_scale_factor": 3,
}

# Every rendered text-entry field under 16px, with enough to find it.
SMALL_FIELDS = """
() => {
  const skip = new Set(['checkbox', 'radio', 'range', 'color', 'file', 'hidden',
    'button', 'submit', 'reset', 'image']);
  return [...document.querySelectorAll('input, textarea, select')]
    .filter((field) => !skip.has((field.getAttribute('type') || 'text').toLowerCase()))
    .filter((field) => field.getClientRects().length > 0)
    .map((field) => ({
      field: `${field.tagName.toLowerCase()}${field.className ? '.' + String(field.className).trim().split(/\\s+/).join('.') : ''}`
        + (field.getAttribute('aria-label') ? `[${field.getAttribute('aria-label')}]` : '')
        + (field.getAttribute('placeholder') ? `{${field.getAttribute('placeholder')}}` : ''),
      size: parseFloat(getComputedStyle(field).fontSize),
    }))
    .filter(({ size }) => size < 16);
}
"""

# How many fields a screen shows, so a walk that found none says so.
FIELD_COUNT = """
() => [...document.querySelectorAll('input, textarea, select')]
  .filter((field) => field.getClientRects().length > 0).length
"""


async def _open_every_section(page) -> None:
    """Expand every collapsed section, so the fields inside are measured too."""
    await page.evaluate(
        "() => document.querySelectorAll('details:not([open])').forEach((d) => { d.open = true; })"
    )


async def test_every_text_field_on_a_phone_is_at_least_16px():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        # The lobby offers its room search only once enough rooms are open.
        hosts = await open_public_rooms(browser, "Sized", 6)
        contexts = [await browser.new_context(**PHONE), await browser.new_context(**PHONE)]
        page, guest = [await context.new_page() for context in contexts]
        small: dict[str, list] = {}
        counts: dict[str, int] = {}

        async def measure(screen: str) -> None:
            await page.wait_for_timeout(150)
            counts[screen] = await page.evaluate(FIELD_COUNT)
            found = await page.evaluate(SMALL_FIELDS)
            if found:
                small[screen] = found

        try:
            viewport = await page.goto(BASE_URL)
            assert viewport is not None
            meta = await page.get_attribute('meta[name="viewport"]', "content")
            # Zoom stays the player's: no cap and no lock in the meta.
            assert "maximum-scale" not in meta and "user-scalable" not in meta, meta

            name = f"Sizer{uuid4().hex[:6]}"
            await use_guest_name(page, name)
            await register_account(page, name)
            await page.wait_for_selector(".public-room-card")
            await measure("lobby")

            await page.goto(f"{BASE_URL}/prompt-lists")
            await page.wait_for_selector(".prompt-stats-controls")
            await measure("prompt lists")

            await page.goto(f"{BASE_URL}/my-prompt-lists")
            await page.wait_for_selector(".prompt-list-manager-layout")
            await measure("my prompt lists")

            # A guest renaming themselves in Settings.
            await guest.goto(BASE_URL)
            await use_guest_name(guest, f"SizeGuest{uuid4().hex[:6]}")
            await open_player_settings(guest)
            await guest.locator(".settings-you").get_by_role("button", name="Change").click()
            await guest.wait_for_selector(".settings-you-name-line input")
            found = await guest.evaluate(SMALL_FIELDS)
            if found:
                small["guest settings"] = found
            await guest.keyboard.press("Escape")

            await page.goto(BASE_URL)
            await open_create_room(page)
            await _open_every_section(page)
            await measure("create room")
            # A registered player's preset bar: the name field it focuses,
            # then the select once there is a preset to start from.
            await page.get_by_role("button", name="Save as preset").click()
            await page.locator(".room-preset-name").fill("Sized preset")
            await measure("create room, naming a preset")
            await page.locator(".room-preset-bar").get_by_role("button", name="Save").click()
            await page.locator(".room-preset-bar select").wait_for()
            await measure("create room, with a preset")
            await page.click('[role="group"][aria-label="Visibility"] button:has-text("Private")')
            await page.click('button:has-text("Create room")')
            await page.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(page)
            await measure("waiting room")
            await open_room_settings(page)
            await _open_every_section(page)
            await measure("rules editor")
            # Custom prompts, so the guest below gets the room's list to search.
            await page.locator("#custom-prompts").fill("lantern\nkettle\nharbour")
            await page.get_by_label("Only use custom prompts").check()
            await save_room_settings(page)

            await guest.goto(BASE_URL)
            await join_by_code(guest, code)
            await guest.wait_for_selector('[data-testid="waiting-room"]')
            await guest.locator("details.waiting-custom-prompts > summary").click()
            await guest.locator(".waiting-custom-prompts-search input").wait_for()
            found = await guest.evaluate(SMALL_FIELDS)
            if found:
                small["guest's waiting room"] = found
            await page.click(".waiting-start-button")
            await page.wait_for_selector('.prompt-choices, [data-testid="choosing-prompt-status"]')
            if await page.query_selector(".prompt-choices"):
                # This page is the drawer: the guest picks nothing, so swap roles
                # by letting the other side be measured as the guesser.
                await page.click(".prompt-choices button:first-child")
                page, guest = guest, page
            else:
                await guest.click(".prompt-choices button:first-child")
            await page.wait_for_selector(".chat-input input")
            await measure("guesser's room")

            assert not small, "fields under 16px:\n" + "\n".join(
                f"  {screen}: {entry['field']} {entry['size']}px"
                for screen, entries in small.items()
                for entry in entries
            )
            assert counts["lobby"] >= 2 and counts["guesser's room"] >= 1, counts
        finally:
            for context in contexts + hosts:
                await context.close()
            await browser.close()
