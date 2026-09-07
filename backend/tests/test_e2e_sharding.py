"""The CI partitions must cover every parametrized case exactly once."""

from pathlib import Path

import pytest

from tests.e2e_sharding import shard_spec

pytest_plugins = ["pytester"]


@pytest.mark.parametrize("value", ["", "1", "a/2", "1/2/3", "0/2", "3/2", "1/0", "-1/2"])
def test_invalid_shard_is_an_error(value):
    with pytest.raises(pytest.UsageError):
        shard_spec(value)


def test_shards_cover_parametrizations_and_new_files_once(pytester):
    plugin = Path(__file__).with_name("e2e_sharding.py").read_text()
    pytester.makeconftest(plugin)
    pytester.makepyfile(
        test_first="""
        import pytest

        @pytest.mark.parametrize("value", range(5))
        def test_case(value):
            pass
        """,
        test_added_later="def test_new(): pass",
    )

    def collected(*args):
        result = pytester.runpytest("--collect-only", "-q", *args)
        assert result.ret == 0
        return {line for line in result.outlines if line.startswith("test_") and "::" in line}

    whole = collected()
    assert len(whole) == 6
    for total in (1, 2, 3):
        shards = [collected(f"--e2e-shard={index}/{total}") for index in range(1, total + 1)]
        assert set.union(*shards) == whole
        assert sum(map(len, shards)) == len(whole)


def test_shards_work_with_xdist_and_propagate_failures(pytester):
    pytester.makeconftest(Path(__file__).with_name("e2e_sharding.py").read_text())
    pytester.makepyfile("""
        import pytest

        @pytest.mark.parametrize("value", range(6))
        def test_case(value):
            assert value != 3
    """)
    first = pytester.runpytest_subprocess("-n", "2", "--e2e-shard=1/2")
    first.assert_outcomes(passed=3)
    assert first.ret == 0
    second = pytester.runpytest_subprocess("-n", "2", "--e2e-shard=2/2")
    second.assert_outcomes(passed=2, failed=1)
    assert second.ret == 1


def test_weights_balance_the_shards_and_unknown_cases_still_run():
    from tests.e2e_sharding import partition

    cases = [f"tests/e2e/test_{n}.py::test_it" for n in "abcdefgh"]
    durations = {cases[0]: 20.0, cases[1]: 20.0, cases[2]: 20.0, cases[3]: 1.0, cases[4]: 1.0}
    assignment = partition(cases, 3, durations)
    assert set(assignment) == set(cases)
    # The three heavy cases land on three different shards, not as modulo would have it.
    assert len({assignment[c] for c in cases[:3]}) == 3
    # Nothing in the file about the rest - they weigh the median and are still placed.
    assert all(assignment[c] in range(3) for c in cases[5:])
    # Every runner computes the same split.
    assert partition(list(reversed(cases)), 3, durations) == assignment
    # Without weights the split is round-robin over sorted IDs, as before.
    assert partition(cases, 3, {}) == {c: i % 3 for i, c in enumerate(cases)}
