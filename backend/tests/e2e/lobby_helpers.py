"""Shared lobby interactions for E2E tests."""
from __future__ import annotations

BASE_URL = "http://localhost:8000"


async def use_guest_name(page, name: str) -> None:
    """Give this page's guest a specific name.

    Sets it through the account, the same way the UI does, so tests that assert
    on a particular name do not each have to walk the first-run block. That
    block, and renaming from Settings, are covered by test_auth_accounts.py.
    """
    # On a page that has one loaded, wait for the app's own provisioning to
    # finish first. Setting the name while GET /api/auth/me is still in flight
    # races it: both calls create an account, and whichever cookie lands
    # second wins - usually discarding the name that was just set. The
    # first-run block is what proves it has landed.
    named_before_any_page = page.url.startswith("about:")
    if not named_before_any_page:
        await page.wait_for_selector(".first-run, .identity-chip")

    # Through the browser context's own cookie jar rather than from inside the
    # page. It is the same request the page would make and lands in the same
    # jar, and it needs no document - which is what lets a test name its
    # player *before* the first load and skip the reload below entirely.
    response = await page.request.post(
        f"{BASE_URL}/api/auth/display-name", data={"displayName": name}
    )
    assert response.status == 200, (
        f"could not set guest name {name!r}: HTTP {response.status}"
    )
    if named_before_any_page:
        # Nothing to reload: the first navigation this page makes will carry
        # the cookie and render the name.
        return
    # The store caches the account, so a reload is what picks the name up.
    # The identity chip appears in every header once a name exists, so this
    # works on the lobby, the invite screen, and the create-room page alike.
    #
    # `domcontentloaded`, not the default `load`: the thing being waited for
    # is the chip on the next line, and the app draws it as soon as its own
    # bundle has run, where `load` waits for every last font and image too.
    #
    # Retried once, because this is the step in the suite that has run out of
    # its timeout twice on CI. A shard is eight workers against one server on
    # a two-core runner; a navigation that does not come back inside a minute
    # there is a starved machine rather than a broken page, and the second
    # attempt has always been enough. What is asserted is unchanged - the chip
    # still has to appear, so a name that never arrives still fails.
    for attempt in (1, 2):
        try:
            await page.reload(timeout=60_000, wait_until="domcontentloaded")
            break
        except Exception:
            if attempt == 2:
                raise
    await page.wait_for_selector(".identity-chip", timeout=60_000)


async def register_account(page, username: str, password: str = "a-good-password") -> None:
    """Claim the current guest account through the header control.

    Registering keeps the same user id, so the player holds their seat and
    simply stops being a guest on it.
    """
    # The claim dialog is reached from the identity chip once a guest is named,
    # or from the first-run block before that. Outside a room the chip opens a
    # menu first, since a guest has a profile to reach as well; the compact chip
    # inside a room still goes straight to the dialog.
    if await page.locator(".identity-chip").count():
        await page.click(".identity-chip")
        claim = page.get_by_role("menuitem", name="Create account")
        if await claim.count():
            await claim.click()
    else:
        await page.click(".first-run-signup")
    dialog = page.locator(".modal-card").filter(has_text="Password")
    await dialog.wait_for(state="visible")
    inputs = dialog.locator("input")
    await inputs.nth(0).fill(username)
    await inputs.nth(1).fill(password)
    await dialog.locator('button[type="submit"]').click()
    await dialog.wait_for(state="hidden")
    # The unclaimed dot disappearing is the signal, and it works whether the
    # chip is showing its name or collapsed to the avatar inside a room.
    await page.wait_for_function("() => !document.querySelector('.identity-unclaimed')")


async def room_code(page) -> str:
    """The current room's code, read from the header's copy control.

    Prefers the stable data-room-code attribute so the helper survives header
    redesigns; falls back to parsing the visible "Code: XXXXXX" label.
    """
    button = page.locator(".room-copy-button").first
    await button.wait_for()
    attr = await button.get_attribute("data-room-code")
    if attr:
        return attr.strip()
    text = await button.inner_text()
    return text.split("Code:")[1].strip()


async def open_room_settings(page) -> None:
    """Open the host's room-settings editor, which lives in a modal."""
    await page.locator(".waiting-settings-row").click()
    await page.wait_for_selector(".room-settings-editor")


async def open_settings_section(page, name: str) -> None:
    """Expand one of the editor's collapsible sections by its heading.

    The editor is the creation form now, so its fields live under Basics,
    Prompts, Drawing, and Scoring and hints rather than one "Advanced
    settings" block."""
    await page.locator(
        f'.room-settings-editor details:has(h2:text-is("{name}")) > summary'
    ).click()


async def save_room_settings(page) -> None:
    """Submit the draft. The editor holds changes until this is pressed, and
    closes itself once the room has taken them."""
    await page.locator(".room-settings-save").click()
    await page.locator(".room-settings-editor").wait_for(state="detached")


async def close_room_settings(page) -> None:
    """Close the room-settings modal (Escape) and wait for it to unmount.
    Discards anything unsaved."""
    await page.keyboard.press("Escape")
    await page.locator(".room-settings-editor").wait_for(state="detached")


async def join_by_code(page, code: str, *, spectate: bool = False) -> None:
    """Enter a room from the lobby by its code.

    The lobby's entry controls live in the header and open the code sheet, so
    this is three steps rather than two. Worth a helper rather than 26 copies
    of them: the last two lobby layout changes each had to rewrite every one
    of those copies, and the step that is actually interesting to a test is
    "this player joined that room".
    """
    # The header says "Join by code"; a phone has no header actions and its
    # thumb dock says "Join with a code". Whichever is on screen is the one.
    await page.locator(
        'button:visible:has-text("Join by code"), button:visible:has-text("Join with a code")'
    ).first.click()
    await page.wait_for_selector('[data-testid="lobby-code-sheet"]')
    await page.fill('input[placeholder="ABC123"]', code)
    await page.click(
        'button:has-text("Watch without playing")'
        if spectate
        else 'button:has-text("Join the room")'
    )
