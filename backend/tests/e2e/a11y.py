"""Accessibility helpers for Playwright e2e tests.

Known exceptions are listed next to the scan that needs them rather than
disabled globally. Color contrast on user-chosen player name colors is
excluded because those values are not under our control.
"""

from pathlib import Path

from playwright.async_api import Page

REPO_ROOT = Path(__file__).resolve().parents[3]
AXE_SOURCE = REPO_ROOT / "frontend" / "node_modules" / "axe-core" / "axe.min.js"

# A path the server has no file at, answered by a route the check installs
# for exactly as long as the script tag takes to load.
AXE_ROUTE = "__e2e__/axe.min.js"
FAILING_IMPACTS = {"critical", "serious"}
# User-chosen name colors can fail contrast; the rest of the UI is in scope.
DEFAULT_DISABLED_RULES = ("color-contrast",)


async def assert_no_axe_violations(
    page: Page,
    context_name: str,
    *,
    disabled_rules=DEFAULT_DISABLED_RULES,
):
    if not AXE_SOURCE.is_file():
        raise FileNotFoundError(
            f"axe-core not found at {AXE_SOURCE}. Run npm ci in frontend/."
        )
    # Served from the page's own origin rather than injected inline: the page
    # is under the Content-Security-Policy production sends (#467), which
    # admits scripts from 'self' and refuses an inline one, and the check is
    # worth more run under that policy than around it.
    axe_url = f"{page.url.split('/', 3)[0]}//{page.url.split('/', 3)[2]}/{AXE_ROUTE}"
    await page.route(
        f"**/{AXE_ROUTE}",
        lambda route: route.fulfill(path=str(AXE_SOURCE), content_type="application/javascript"),
    )
    try:
        await page.add_script_tag(url=axe_url)
    finally:
        await page.unroute(f"**/{AXE_ROUTE}")
    results = await page.evaluate(
        """async (disabledRules) => {
            return await axe.run({
                runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag22aa"] },
                rules: Object.fromEntries(
                    disabledRules.map((id) => [id, { enabled: false }])
                ),
            });
        }""",
        list(disabled_rules),
    )
    violations = [
        violation
        for violation in results.get("violations", [])
        if any(node.get("impact") in FAILING_IMPACTS for node in violation.get("nodes", []))
        or violation.get("impact") in FAILING_IMPACTS
    ]
    if not violations:
        return

    lines = [f"axe violations in {context_name}:"]
    for violation in violations:
        help_url = violation.get("helpUrl", "")
        lines.append(f"- {violation['id']}: {violation['help']} ({help_url})")
        for node in violation.get("nodes", [])[:5]:
            target = ", ".join(node.get("target", []))
            lines.append(f"    {target}: {node.get('failureSummary', '').splitlines()[0] if node.get('failureSummary') else ''}")
    raise AssertionError("\n".join(lines))
