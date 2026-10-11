"""First contentful paint of a cold visit, as a phone on a slow network gets
it (#1426).

Each load is a fresh browser context - nothing cached, nothing stored - at
412 px, with the CPU slowed 4x and the network shaped to Slow 4G (150 ms,
1.6 Mbps down, 750 kbps up) through the DevTools protocol. Four visits: the
lobby and an invite link (`/room/<code>`), each for an English and a French
browser. Prints the median of ``--loads`` first contentful paints per visit,
and which language catalogues each visit downloaded.

Needs a server serving a production build (`npm run build`), e.g. the
end-to-end runner's:

    backend/.venv/bin/python benchmarks/first_paint.py --base-url http://localhost:8766
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics

from playwright.async_api import async_playwright

VISITS = {
    "lobby en": ("/", "en-US"),
    "lobby fr": ("/", "fr-FR"),
    "invite en": ("/room/BENCH1", "en-US"),
    "invite fr": ("/room/BENCH1", "fr-FR"),
}
CATALOGUE = re.compile(r"/assets/(en|de|es|fr|it|nl|pl|pt)-[\w-]+\.js$")


async def one_load(browser, base_url: str, path: str, locale: str) -> tuple[float, list[str]]:
    context = await browser.new_context(
        viewport={"width": 412, "height": 915}, locale=locale, is_mobile=True, has_touch=True
    )
    page = await context.new_page()
    catalogues: list[str] = []
    page.on("request", lambda request: catalogues.append(CATALOGUE.search(request.url).group(1)) if CATALOGUE.search(request.url) else None)
    cdp = await context.new_cdp_session(page)
    await cdp.send("Network.enable")
    await cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
    await cdp.send(
        "Network.emulateNetworkConditions",
        {"offline": False, "latency": 150, "downloadThroughput": 1_600_000 / 8, "uploadThroughput": 750_000 / 8},
    )
    await cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
    try:
        await page.goto(base_url + path, wait_until="load", timeout=60_000)
        fcp = None
        for _ in range(200):
            fcp = await page.evaluate(
                "() => performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? null"
            )
            if fcp is not None:
                break
            await page.wait_for_timeout(100)
        return float(fcp or 0), catalogues
    finally:
        await context.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--loads", type=int, default=5)
    args = parser.parse_args()
    results = {}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for name, (path, locale) in VISITS.items():
                paints, fetched = [], set()
                for _ in range(args.loads):
                    fcp, catalogues = await one_load(browser, args.base_url, path, locale)
                    paints.append(fcp)
                    fetched.update(catalogues)
                results[name] = {
                    "median_fcp_ms": round(statistics.median(paints)),
                    "catalogues": sorted(fetched),
                }
        finally:
            await browser.close()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
