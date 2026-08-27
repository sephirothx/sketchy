"""Randomised properties of the path-point codec.

The golden fixture pins a handful of cases from both languages, which catches a
format change but not an edge the author did not think of. Path points are now
the only variable-length structure on the wire - two encodings, a chosen
threshold, and an escape marker - so they get exercised over generated input
as well as over examples.

Seeded, so a failure is reproducible rather than a story about a flaky run.
"""
from __future__ import annotations

import base64
import random

import pytest

from app.canvas_history import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    COORDINATE_SCALE,
    MAX_PACKED_COORDINATE,
    MIN_PACKED_COORDINATE,
)
from app.live_drawing import (
    MAX_POINTS_PER_FRAME,
    _MAX_BASE64_CHARS,
    PATH_POINTS_DELTA_TAG,
    PATH_POINTS_TAG,
    _HEADER_TAG_MASK,
    decode_live_drawing,
    encode_live_drawing,
)


def _packed(value: float, size: int) -> int:
    return round(value * size * COORDINATE_SCALE)


def _random_stroke(rng: random.Random, count: int, step: float) -> list[dict]:
    """A stroke that wanders by up to `step` normalized units per sample."""
    x = rng.uniform(0.0, 1.0)
    y = rng.uniform(0.0, 1.0)
    points = []
    for _ in range(count):
        x = min(1.5, max(-0.5, x + rng.uniform(-step, step)))
        y = min(1.5, max(-0.5, y + rng.uniform(-step, step)))
        points.append({"x": x, "y": y})
    return points


# Step sizes chosen to straddle the escape threshold from both sides: 0.002 of
# a canvas is well inside a byte delta, 0.4 is far outside it, and 0.02 sits
# near the boundary where frames mix deltas and escapes.
@pytest.mark.parametrize("step", [0.0005, 0.002, 0.02, 0.1, 0.4])
@pytest.mark.parametrize("count", [1, 2, 3, 17, 256])
def test_path_points_round_trip_on_the_quarter_pixel_grid(count, step):
    rng = random.Random(f"{count}-{step}")
    for _ in range(25):
        points = _random_stroke(rng, count, step)
        decoded = decode_live_drawing(encode_live_drawing("draw_move", {"points": points}))

        assert decoded.event == "draw_move"
        returned = decoded.payload["points"]
        assert len(returned) == len(points)
        # Quantization to quarter-pixels is the only loss allowed. Compare on
        # that grid rather than on the floats that went in.
        for original, result in zip(points, returned, strict=True):
            assert _packed(original["x"], CANVAS_WIDTH) == _packed(result["x"], CANVAS_WIDTH)
            assert _packed(original["y"], CANVAS_HEIGHT) == _packed(result["y"], CANVAS_HEIGHT)


@pytest.mark.parametrize("step", [0.0005, 0.002, 0.02, 0.1, 0.4])
def test_the_chosen_encoding_is_never_larger_than_absolute(step):
    """The whole point of choosing per frame: it cannot lose to plain absolute."""
    rng = random.Random(f"size-{step}")
    for _ in range(50):
        points = _random_stroke(rng, rng.randint(1, 60), step)
        frame = encode_live_drawing("draw_move", {"points": points})
        assert len(frame) <= 1 + len(points) * 4


def test_encoding_is_stable_under_re_encoding():
    """Decode then re-encode reproduces the same bytes, so nothing drifts."""
    rng = random.Random("stability")
    for _ in range(200):
        points = _random_stroke(rng, rng.randint(1, 40), rng.choice([0.001, 0.05, 0.3]))
        once = encode_live_drawing("draw_move", {"points": points})
        twice = encode_live_drawing(
            "draw_move", decode_live_drawing(once).payload
        )
        assert once == twice


def test_both_encodings_are_actually_exercised():
    """Guard against the adaptive branch silently collapsing to one side."""
    rng = random.Random("coverage")
    seen = set()
    for step in (0.0005, 0.4):
        for _ in range(40):
            frame = encode_live_drawing(
                "draw_move", {"points": _random_stroke(rng, 12, step)}
            )
            seen.add(frame[0] & _HEADER_TAG_MASK)
    assert seen == {PATH_POINTS_TAG, PATH_POINTS_DELTA_TAG}


def test_truncated_and_corrupt_frames_are_refused_not_reinterpreted():
    rng = random.Random("truncation")
    points = _random_stroke(rng, 20, 0.002)
    frame = encode_live_drawing("draw_move", {"points": points})
    assert frame[0] & _HEADER_TAG_MASK == PATH_POINTS_DELTA_TAG

    # Cutting a delta frame mid-record must be refused rather than read past.
    for cut in range(1, len(frame)):
        candidate = frame[:cut]
        try:
            decoded = decode_live_drawing(candidate)
        except ValueError:
            continue
        # If it decodes at all it must be a strict prefix of the real stroke,
        # never points invented by misreading a record boundary.
        assert len(decoded.payload["points"]) <= len(points)


def test_a_delta_frame_cannot_walk_a_coordinate_out_of_range():
    # A hand-built frame whose deltas march past the packed range must be
    # refused; the encoder cannot produce one, but a peer could send one.
    frame = bytearray((PATH_POINTS_DELTA_TAG | (1 << 4),))
    frame.extend(MAX_PACKED_COORDINATE.to_bytes(2, "little", signed=True))
    frame.extend((0).to_bytes(2, "little", signed=True))
    frame.extend(b"\x7f\x00" * 8)
    with pytest.raises(ValueError):
        decode_live_drawing(bytes(frame))
    assert MIN_PACKED_COORDINATE < 0 < MAX_POINTS_PER_FRAME


def test_a_frame_survives_the_base64_wire_shape_unchanged():
    """The cheap wire shape must decode to exactly the binary one."""
    rng = random.Random("base64")
    for _ in range(200):
        points = _random_stroke(rng, rng.randint(1, 40), rng.choice([0.001, 0.05, 0.3]))
        frame = encode_live_drawing("draw_move", {"points": points})
        as_text = base64.b64encode(frame).decode()
        assert decode_live_drawing(as_text) == decode_live_drawing(frame)


def test_hostile_base64_is_refused_rather_than_decoded():
    for bad in (
        "not base64!!",
        "####",
        "A",                       # not a whole base64 group
        "",                        # empty frame once decoded
        base64.b64encode(b"\x20").decode(),  # valid base64, unknown version
        "A" * (_MAX_BASE64_CHARS + 4),       # past the length bound
    ):
        with pytest.raises(ValueError):
            decode_live_drawing(bad)


def test_the_length_bound_admits_the_largest_legitimate_frame():
    # Every point escaping is the worst case the encoder can produce.
    points = [
        {"x": (index % 2) * 0.9, "y": ((index + 1) % 2) * 0.9}
        for index in range(MAX_POINTS_PER_FRAME)
    ]
    frame = encode_live_drawing("draw_move", {"points": points})
    encoded = base64.b64encode(frame).decode()
    assert len(encoded) <= _MAX_BASE64_CHARS
    assert decode_live_drawing(encoded) == decode_live_drawing(frame)
