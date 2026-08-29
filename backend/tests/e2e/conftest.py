"""Fixtures and collection rules shared by the Playwright E2E suite."""
import os

import pytest


SHARD_COUNT_VAR = "E2E_SHARD_COUNT"
SHARD_VAR = "E2E_SHARD"


def _shard_setting(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise pytest.UsageError(f"{name} must be a whole number, not {raw!r}") from error


def pytest_collection_modifyitems(config, items):
    """Keep only this shard's share of the suite.

    The suite is browser-bound rather than server-bound - one run leaves the
    server using well under a third of a core - so the ceiling is how much
    browser a runner can drive at once. More xdist workers on one runner does
    not lift that ceiling: past the core count the browsers contend, tests that
    wait on a phase start timing out, and the run gets slower as well as
    flakier. A second runner with its own server and its own database does lift
    it, which is what these two variables are for.

    Sharding is per test rather than per file on purpose: the files differ by
    an order of magnitude in how long they take, and a per-file split would
    leave one shard holding the long ones.

    The order has to be identical in the xdist controller and in every worker,
    or they disagree about which tests exist and the run dies before it starts.
    Hence the sort by node id rather than trusting collection order.
    """
    count = _shard_setting(SHARD_COUNT_VAR, 1)
    if count <= 1:
        return

    shard = _shard_setting(SHARD_VAR, 1)
    if not 1 <= shard <= count:
        raise pytest.UsageError(
            f"{SHARD_VAR} must be between 1 and {SHARD_COUNT_VAR} ({count}), got {shard}"
        )

    # Dealt round-robin over a stable order, then filtered back into collection
    # order, which is the order xdist and the reporters expect.
    ordered = sorted(items, key=lambda item: item.nodeid)
    mine = {id(item) for item in ordered[shard - 1 :: count]}
    dropped = [item for item in items if id(item) not in mine]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = [item for item in items if id(item) in mine]


@pytest.fixture
def assert_input_contract():
    async def assert_contract(locator, expected):
        contract = await locator.evaluate(
            """(input) => ({
                type: input.type,
                role: input.getAttribute("role"),
                inputMode: input.inputMode,
                autoComplete: input.getAttribute("autocomplete"),
                autoCapitalize: input.getAttribute("autocapitalize"),
                spellCheck: input.spellcheck,
                autoCorrect: input.getAttribute("autocorrect"),
                enterKeyHint: input.enterKeyHint,
            })"""
        )
        assert {key: contract[key] for key in expected} == expected

    return assert_contract
