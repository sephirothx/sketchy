"""Public pages at an address per interface language (#1462).

`/de/rules` is the rules in German whatever the reader's own language is, the
links between public pages keep the language, nothing is remembered, and the
language picker on a public page moves to that page's address in the choice.
"""
from __future__ import annotations

import re
import secrets
import urllib.error
import urllib.request

from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import use_guest_name

BASE_URL = "http://localhost:8000"


def test_english_has_one_address():
    request = urllib.request.Request(BASE_URL + "/en/rules", method="HEAD")

    class Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    try:
        urllib.request.build_opener(Stay).open(request)
        raise AssertionError("/en/rules answered without a redirect")
    except urllib.error.HTTPError as answer:
        assert answer.code == 301 and answer.headers["Location"] == "/rules"


async def test_a_language_address_reads_that_page_in_that_language_only():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(locale="en-US")
        page = await context.new_page()
        try:
            await page.goto(BASE_URL + "/de/rules")
            await page.get_by_role("heading", name="Regeln", exact=True).wait_for()
            assert await page.evaluate("document.documentElement.lang") == "de"
            assert await page.title() == "Regeln · Sketchy"

            # A link between public pages keeps the address's language.
            stats = page.locator('.site-nav a[href="/de/prompt-lists"]')
            await stats.click()
            await page.wait_for_url("**/de/prompt-lists")
            assert await page.evaluate("document.documentElement.lang") == "de"

            # Nothing was remembered: a page with one address is read in the
            # reader's own language again.
            assert await page.evaluate("localStorage.getItem('sketchy_locale')") is None
            await page.goto(BASE_URL + "/create")
            await page.wait_for_function("() => document.documentElement.lang === 'en'")
        finally:
            await context.close()
            await browser.close()


async def test_the_picker_on_a_public_page_moves_to_its_address_in_the_choice():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(locale="en-US", viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        try:
            await page.goto(BASE_URL + "/rules")
            trigger = page.locator(".lobby-header .picker-trigger")
            await trigger.click()
            await page.get_by_role("option", name=re.compile("français", re.I)).click()
            await page.wait_for_url("**/fr/rules")
            await page.wait_for_function("() => document.documentElement.lang === 'fr'")
            # The choice is the reader's own from now on, as anywhere else.
            assert await page.evaluate("localStorage.getItem('sketchy_locale')") == "fr"

            await trigger.click()
            await page.get_by_role("option", name=re.compile("^English")).click()
            await page.wait_for_url(re.compile(r"/rules$"))
            await page.wait_for_function("() => document.documentElement.lang === 'en'")
            assert await page.evaluate("localStorage.getItem('sketchy_locale')") == "en"
        finally:
            await context.close()
            await browser.close()


async def test_a_filter_on_a_language_address_keeps_the_language():
    # Review of #1462: the page table sees the address without its prefix, and
    # a relative navigation - a filter's search params - used to drop it.
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(locale="en-US", viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        try:
            await page.goto(BASE_URL + "/de/prompt-lists/english_standard")
            sort = page.locator("#prompt-stats-sort")
            await sort.click()
            await page.get_by_role("option").nth(1).click()
            await page.wait_for_url(re.compile(r"/de/prompt-lists/english_standard\?.+"))
            assert await page.evaluate("document.documentElement.lang") == "de"
        finally:
            await context.close()
            await browser.close()


async def test_an_account_made_on_a_language_address_keeps_the_reader_s_own_language():
    # Review of #1462: an account is created with the reader's language, not
    # the one a page's address put in force for that page.
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(locale="en-US")
        page = await context.new_page()
        try:
            await page.goto(BASE_URL + "/de")
            await page.locator(".first-run").wait_for()
            await page.click(".first-run-signup")
            # Not the play-languages question a new identity is asked next.
            dialog = page.locator(".modal-card:not(.play-languages-question)")
            await dialog.wait_for(state="visible")
            inputs = dialog.locator("input")
            await inputs.nth(0).fill(f"url_{secrets.token_hex(4)}")
            await inputs.nth(1).fill("a-good-password")
            await dialog.locator('button[type="submit"]').click()
            await dialog.wait_for(state="hidden")
            await page.wait_for_function("() => !document.querySelector('.first-run')")
            settings = await page.evaluate(
                'async () => (await fetch("/api/users/me/settings")).json()'
            )
            assert settings["locale"] == "en", settings
            assert await page.evaluate("localStorage.getItem('sketchy_locale')") != "de"
            # Still German here, where the address says so.
            assert await page.evaluate("document.documentElement.lang") == "de"
        finally:
            await context.close()
            await browser.close()


async def test_settings_over_a_language_address_move_the_page_behind_them():
    # Review of #1462: Settings opened over /de/rules is drawn over the German
    # page, and choosing French there moves the page to /fr/rules.
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(locale="en-US", viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        try:
            await page.goto(BASE_URL + "/de/rules")
            await page.locator(".header-settings-button").click()
            await page.wait_for_url(re.compile(r"/settings"))
            # The page behind is still read in German.
            assert await page.evaluate("document.documentElement.lang") == "de"
            # The interface language is on the Appearance tab.
            await page.locator(".settings-tab-button").nth(1).click()
            await page.wait_for_url(re.compile(r"/settings/appearance"))
            await page.locator(".settings-modal-card .picker-trigger").first.click()
            await page.get_by_role("option", name=re.compile("français", re.I)).click()
            await page.wait_for_function("() => document.documentElement.lang === 'fr'")
            # The page behind moves once the switch has worked, just after it.
            await page.wait_for_function("() => history.state?.usr?.overlayMoved === true")
            # Closing lands on the page in the language chosen, not back on
            # the German address it was opened from.
            await page.keyboard.press("Escape")
            await page.wait_for_url("**/fr/rules")
            assert await page.evaluate("document.documentElement.lang") == "fr"
        finally:
            await context.close()
            await browser.close()


async def test_settings_over_a_filtered_language_address_keep_the_page_and_its_language():
    # Review of #1462: the overlay's background carries the page's query, and
    # it used to stop the prefix being read - the not-found page behind
    # Settings, in the reader's own language.
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(locale="en-US", viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        try:
            await page.goto(BASE_URL + "/de/prompt-lists?window=30d")
            await page.locator(".prompt-stats-page").wait_for()
            await page.locator(".header-settings-button").click()
            await page.wait_for_url(re.compile(r"/settings"))
            await page.locator(".settings-modal-card").wait_for()
            assert await page.locator(".prompt-stats-page").count() == 1
            assert await page.evaluate("document.documentElement.lang") == "de"
        finally:
            await context.close()
            await browser.close()


async def test_a_language_that_cannot_be_fetched_changes_neither_page_nor_choice():
    # Review of #1462: the address and the remembered choice follow only a
    # switch that worked, as R-I18N-06 asks of every switch.
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(locale="en-US", viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        try:
            await page.goto(BASE_URL + "/rules")
            await page.evaluate("localStorage.setItem('sketchy_locale', 'en')")
            await page.route(re.compile(r"/assets/de-[\w-]+\.js$"), lambda route: route.abort())
            await page.locator(".lobby-header .picker-trigger").click()
            await page.get_by_role("option", name=re.compile("Deutsch")).click()
            await page.wait_for_timeout(1500)
            assert page.url.endswith("/rules"), page.url
            assert await page.evaluate("document.documentElement.lang") == "en"
            assert await page.evaluate("localStorage.getItem('sketchy_locale')") == "en"
        finally:
            await context.close()
            await browser.close()


async def test_the_account_menu_keeps_the_address_s_language():
    # Review of #1462: on a phone the account menu is a named player's way to
    # the rules and the stats, and it too keeps the page's language.
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(locale="en-US", viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        try:
            await page.goto(BASE_URL + "/de")
            await use_guest_name(page, f"Menu{secrets.token_hex(3)}")
            await page.goto(BASE_URL + "/de/terms")
            await page.locator(".identity-chip").click()
            await page.get_by_role("menuitem", name="Regeln").click()
            await page.wait_for_url("**/de/rules")
            assert await page.evaluate("document.documentElement.lang") == "de"
        finally:
            await context.close()
            await browser.close()
