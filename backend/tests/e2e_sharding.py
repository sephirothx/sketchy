"""Partition collected E2E cases across CI runners, then let xdist schedule them."""

import pytest


def shard_spec(value):
    try:
        index, total = map(int, value.split("/"))
    except ValueError as exc:
        raise pytest.UsageError("--e2e-shard must be INDEX/TOTAL (for example 1/2)") from exc
    if not 1 <= index <= total:
        raise pytest.UsageError("--e2e-shard requires 1 <= INDEX <= TOTAL")
    return index, total


def pytest_addoption(parser):
    parser.addoption(
        "--e2e-shard", type=shard_spec, default=None,
        help="Run one INDEX/TOTAL partition of the collected test cases (one-based).",
    )


def pytest_report_header(config):
    shard = config.getoption("e2e_shard")
    if shard:
        return f"E2E shard: {shard[0]}/{shard[1]}"


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    shard = config.getoption("e2e_shard")
    if shard is None:
        return
    index, total = shard
    selected, deselected = [], []
    # Full node IDs include parametrizations. Sorting makes every worker and
    # runner agree without a maintained file list that can omit new tests.
    for position, item in enumerate(sorted(items, key=lambda item: item.nodeid)):
        (selected if position % total == index - 1 else deselected).append(item)
    # The real operator probe leaves urllib long-polls in executor threads;
    # process/event-loop shutdown waits roughly 45 seconds for them. Start
    # these cases early so browser scenarios overlap that wait. Do this after
    # partitioning: the two adjacent probe IDs land on different CI runners.
    if total > 1:
        selected.sort(key=lambda item: not item.nodeid.startswith("tests/e2e/test_probe.py::"))
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
