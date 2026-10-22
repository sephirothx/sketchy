"""Public pages at an address per interface language (#1462).

`/de/rules` is the rules in German whatever the reader's own language is, the
links between public pages keep the language, nothing is remembered, and the
language picker on a public page moves to that page's address in the choice.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request

from playwright.async_api import async_playwright

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
