"""One header on every page (R-UX-11): the wordmark and the identity chip sit
in the same place whatever width the page's own content keeps."""
from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import use_guest_name
from tests.e2e.test_friends import unique

BASE_URL = "http://localhost:8000"


async def test_the_lobby_header_is_whole_and_where_every_page_has_it():
    """At a laptop's 1280 x 800 the lobby is pinned to the window, and the
    header reaches out of its 928px column to the shell. The pinned page used
    to clip everything outside the column, which cut the wordmark and the chip
    off entirely - a lobby with no way to Settings or the account menu."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        try:
            await use_guest_name(page, unique("Shell"))
            await page.goto(BASE_URL)
            chip = page.locator(".lobby-header .identity-chip")
            home = page.locator(".lobby-header .header-home-link")
            await chip.wait_for()

            # Whole, and inside the window.
            for control in (chip, home):
                box = await control.bounding_box()
                assert box is not None
                assert box["x"] >= 0 and box["x"] + box["width"] <= 1280, box

            # And answering: a click reaches it rather than a clipped nothing.
            await chip.click()
            await expect(page.locator(".account-dropdown")).to_be_visible()
            await page.keyboard.press("Escape")
            lobby_chip = await chip.bounding_box()
            lobby_home = await home.bounding_box()

            # The same place on a page with a column of another width.
            await page.goto(f"{BASE_URL}/rules")
            await page.get_by_role("heading", name="Rules", exact=True).wait_for()
            rules_chip = await chip.bounding_box()
            rules_home = await home.bounding_box()
            assert abs(rules_chip["x"] - lobby_chip["x"]) <= 1, (rules_chip, lobby_chip)
            assert abs(rules_home["x"] - lobby_home["x"]) <= 1, (rules_home, lobby_home)
        finally:
            await context.close()
            await browser.close()


async def test_the_header_links_the_site_and_marks_the_page_you_are_on():
    """The bar carries the site's pages (R-UX-11, R-UX-16): the lobby, the
    Gallery with a session, the Community catalogue, Prompt stats and Rules,
    with the current one marked - named where the names fit, as icons where
    only the icons do, and not at all where neither does. A visitor who has
    not chosen a name has no session, and the Gallery would only refuse them
    (R-GAL-02), so their bar does not offer it."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        named = await browser.new_context(viewport={"width": 1280, "height": 800})
        nameless = await browser.new_context(viewport={"width": 1280, "height": 800})
        try:
            page = await named.new_page()
            await use_guest_name(page, unique("Nav"))
            await page.goto(BASE_URL)
            await page.locator(".lobby-header .identity-chip").wait_for()
            nav = page.get_by_role("navigation", name="Pages")
            lobby = nav.get_by_role("link", name="Lobby", exact=True)
            gallery = nav.get_by_role("link", name="Gallery", exact=True)
            await expect(lobby).to_have_attribute("aria-current", "page")
            await expect(gallery).not_to_have_attribute("aria-current", "page")
            await expect(nav.get_by_role("link", name="Community catalogue")).to_be_visible()
            await expect(nav.get_by_role("link", name="Prompt stats")).to_be_visible()
            await expect(nav.get_by_role("link", name="Rules", exact=True)).to_be_visible()

            # Named at 1280: `to_be_visible` on a link passes in icon mode
            # too, so the label itself is what is checked.
            await expect(page.locator(".site-nav.is-labels")).to_have_count(1)
            await expect(lobby.locator(".site-nav-label")).to_be_visible()
            await expect(lobby.locator(".site-nav-label")).to_have_text("Lobby")
            await expect(lobby).not_to_have_attribute("title", "Lobby")

            # A click is a way there, and the mark follows.
            await gallery.click()
            await page.wait_for_url(f"{BASE_URL}/gallery")
            await expect(gallery).to_have_attribute("aria-current", "page")
            await expect(lobby).not_to_have_attribute("aria-current", "page")

            # A page nested under the Gallery marks the section, not the page.
            # The drawing need not exist: its page still draws the bar, with
            # the crumb back to the Gallery.
            await page.goto(f"{BASE_URL}/gallery/00000000-0000-0000-0000-000000000000")
            await page.locator(".lobby-header .header-crumb").wait_for()
            await expect(gallery).to_have_attribute("aria-current", "true")

            # At 960 beside the crumb the names no longer fit, but the icons
            # do (measured with a name like this one: the names need a window
            # of about 1160px here, the icons about 760px). The label is clipped to nothing - still the link's name -
            # and the tooltip says it instead.
            await page.set_viewport_size({"width": 960, "height": 800})
            await expect(page.locator(".site-nav.is-icons")).to_have_count(1)
            await expect(lobby).to_have_attribute("title", "Lobby")
            label_box = await lobby.locator(".site-nav-label").bounding_box()
            assert label_box is not None and label_box["width"] <= 1, label_box

            # On a phone the wordmark, the flag and the chip leave no room for
            # even the icons, so there is no nav: not clipped out of sight but
            # out of the accessibility tree and the tab order.
            await page.set_viewport_size({"width": 390, "height": 844})
            await page.goto(BASE_URL)
            await page.locator(".lobby-header .identity-chip").wait_for()
            await expect(page.locator(".site-nav.is-hidden")).to_have_count(1)
            await expect(nav).to_have_count(0)

            visitor = await nameless.new_page()
            await visitor.goto(BASE_URL)
            await visitor.locator(".first-run").wait_for()
            visitor_nav = visitor.get_by_role("navigation", name="Pages")
            await expect(visitor_nav.get_by_role("link", name="Rules", exact=True)).to_be_visible()
            await expect(visitor_nav.get_by_role("link", name="Gallery", exact=True)).to_have_count(0)
        finally:
            await named.close()
            await nameless.close()
            await browser.close()
