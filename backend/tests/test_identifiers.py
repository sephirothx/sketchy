"""The generation policy behind every durable entity identifier.

Locked decision 4 of the #393 plan requires these properties to be pinned:
version and variant bits, clock rollback, concurrent generation, monotonic
process-local order, and uniqueness.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.identifiers import generate_uuid7


BURST = 10_000


def _embedded_milliseconds(value: uuid.UUID) -> int:
    return int.from_bytes(value.bytes[:6], "big")


def test_generated_values_carry_the_version_and_variant_bits_of_rfc_9562():
    for value in (generate_uuid7() for _ in range(1_000)):
        assert isinstance(value, uuid.UUID)
        assert value.version == 7
        assert value.bytes[6] & 0xF0 == 0x70
        assert value.bytes[8] & 0xC0 == 0x80


def test_process_local_order_is_monotonic_and_values_are_unique():
    generated = [generate_uuid7() for _ in range(BURST)]

    assert generated == sorted(generated)
    assert len(set(generated)) == len(generated)


def test_the_embedded_timestamp_stays_truthful_through_a_burst():
    """Ordering must come from a counter, not from advancing the clock.

    An implementation that separates same-millisecond values by adding a
    millisecond each time is still ordered and still unique, but it stamps a
    burst of ids seconds into the future - permanently, since the id is
    stored. Seeding the bundled prompt lists is exactly such a burst.
    """
    last = None
    for _ in range(BURST):
        last = generate_uuid7()
    drift = _embedded_milliseconds(last) - time.time_ns() // 1_000_000

    assert 0 <= drift <= 50, f"burst of {BURST} drifted {drift} ms from the clock"


def test_a_backward_clock_step_cannot_produce_a_smaller_value(monkeypatch):
    before = generate_uuid7()
    real_time_ns = time.time_ns
    monkeypatch.setattr(
        time, "time_ns", lambda: real_time_ns() - 60 * 1_000_000_000
    )

    during = [generate_uuid7() for _ in range(100)]

    monkeypatch.undo()
    after = generate_uuid7()
    assert during == sorted(during)
    assert before < during[0]
    assert during[-1] < after
    assert len(set(during)) == len(during)


def test_threaded_generation_never_repeats_a_value():
    with ThreadPoolExecutor(max_workers=8) as pool:
        batches = list(
            pool.map(lambda _: [generate_uuid7() for _ in range(2_000)], range(8))
        )

    generated = [value for batch in batches for value in batch]
    assert len(set(generated)) == len(generated)
    assert all(value.version == 7 for value in generated)


@pytest.mark.asyncio
async def test_concurrent_tasks_never_repeat_a_value():
    async def batch() -> list[uuid.UUID]:
        values = []
        for _ in range(2_000):
            values.append(generate_uuid7())
            await asyncio.sleep(0)
        return values

    batches = await asyncio.gather(*(batch() for _ in range(8)))

    generated = [value for batch_values in batches for value in batch_values]
    assert len(set(generated)) == len(generated)
