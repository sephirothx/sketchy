"""What a stored drawing promises: readable forever, and never a wire format."""

from __future__ import annotations

import json
import random
import struct
import zlib
from pathlib import Path

import pytest

from app.canvas_history import (
    BINARY_HISTORY_MAGIC,
    CANVAS_HISTORY_VERSION,
    MAX_BINARY_CANVAS_HISTORY_BYTES,
    MAX_CANVAS_ACTIONS,
    PackedCanvasHistory,
    decode_binary_canvas_history,
)
from app.canvas_storage import (
    _DELTA_HEADER,
    _STORED_DECODERS,
    STORED_DELTA_MAGIC,
    STORED_DELTA_VERSION,
    CorruptStoredDrawingError,
    UnsupportedStoredDrawingError,
    _walk_frame,
    prepare_stored_drawing,
    stored_drawing_checksum,
    stored_drawing_format,
    stored_drawing_wire_payload,
)


FIXTURES_DIR = Path(__file__).parents[2] / "fixtures"
# The cross-language wire fixtures: what every stored format has to decode to.
WIRE = json.loads((FIXTURES_DIR / "canvas_protocol_v1.json").read_text())
GOLDEN = [bytes.fromhex(entry["binary"]) for entry in WIRE["histories"]]
# Blobs as the SKCD v1 encoder wrote them on the day the format was cut,
# beside the wire frame each decodes to. A stored format is frozen: this
# file may gain entries and must never lose one, and a decoder change that
# stops reading one of these has broken a row somebody holds (R-HIST-18).
STORED = json.loads((FIXTURES_DIR / "stored_drawings_v1.json").read_text())


def _stroke_history(seed: int, *, strokes: int = 40, points: int = 60) -> PackedCanvasHistory:
    """A drawing of the shape a player makes: strokes of small movements,
    with the odd shape, fill and clear, over the whole coordinate range."""
    rng = random.Random(seed)
    history = PackedCanvasHistory()
    for stroke in range(strokes):
        x, y = rng.uniform(-8, 8), rng.uniform(-8, 8)
        # A hand moves with momentum: the direction drifts, the speed stays.
        dx, dy = rng.uniform(-0.01, 0.01), rng.uniform(-0.01, 0.01)
        trail = []
        for _ in range(points):
            dx = min(0.02, max(-0.02, dx + rng.uniform(-0.002, 0.002)))
            dy = min(0.02, max(-0.02, dy + rng.uniform(-0.002, 0.002)))
            x = min(8.0, max(-8.0, x + dx))
            y = min(8.0, max(-8.0, y + dy))
            trail.append((x, y))
        history.append_path(trail, color=rng.randrange(1 << 24), width=rng.randint(1, 64))
        if stroke % 7 == 3:
            history.append_shape(
                shape=rng.choice(("rectangle", "ellipse", "triangle")),
                start=(rng.uniform(0, 1), rng.uniform(0, 1)),
                end=(rng.uniform(0, 1), rng.uniform(0, 1)),
                color=rng.randrange(1 << 24),
                width=rng.randint(1, 64),
            )
        if stroke % 11 == 5:
            history.append_fill(x=rng.randrange(800), y=rng.randrange(600), color=rng.randrange(1 << 24))
        if stroke == 20:
            history.append_clear()
    return history


def _extreme_history() -> PackedCanvasHistory:
    """Points that jump across the whole packed range, so a delta between
    two of them does not fit a signed 16-bit value and the modular recoding
    is what keeps it lossless."""
    history = PackedCanvasHistory()
    corners = [(-10.24, -10.24), (10.2, 13.6), (-10.24, 13.6), (10.2, -10.24), (0.0, 0.0)]
    history.append_path(corners * 40, color=0xFF00FF, width=3)
    return history


@pytest.mark.parametrize("frame", GOLDEN)
def test_a_golden_wire_history_survives_a_storage_round_trip(frame):
    stored, magic, version, checksum = prepare_stored_drawing(frame)

    assert (magic, version) in _STORED_DECODERS
    assert stored_drawing_format(stored) == (magic, version)
    assert len(stored) <= len(frame), "a stored drawing is never larger than its wire frame"
    assert stored_drawing_wire_payload(stored, checksum=checksum) == frame


@pytest.mark.parametrize("entry", STORED["drawings"], ids=lambda entry: entry["name"])
def test_a_blob_written_on_the_day_the_format_was_cut_still_decodes(entry):
    """The stored fixture is decode-only on purpose: deflate's exact output
    may move between zlib versions, the frame it inflates to may not."""
    blob = bytes.fromhex(entry["stored"])

    assert stored_drawing_format(blob) == (STORED_DELTA_MAGIC, STORED_DELTA_VERSION)
    assert stored_drawing_checksum(blob) == entry["checksum"]
    assert stored_drawing_wire_payload(blob, checksum=entry["checksum"]) == bytes.fromhex(entry["wire"])


@pytest.mark.parametrize("seed", range(12))
def test_a_stroke_drawing_is_stored_compressed_and_comes_back_exact(seed):
    frame = _stroke_history(seed).binary_payload()
    stored, magic, version, checksum = prepare_stored_drawing(frame)

    assert (magic, version) == (STORED_DELTA_MAGIC, STORED_DELTA_VERSION)
    # Exactness is the promise here; the ratio a real drawing reaches is
    # the benchmark's business (4.5x on its realistic frame).
    assert len(stored) < len(frame) * 0.7, f"{len(frame)} -> {len(stored)}"
    assert stored_drawing_wire_payload(stored, checksum=checksum) == frame
    assert decode_binary_canvas_history(stored_drawing_wire_payload(stored)) == decode_binary_canvas_history(frame)


def test_deltas_that_overflow_a_signed_coordinate_round_trip():
    frame = _extreme_history().binary_payload()
    recoded = _walk_frame(frame, undo=False)

    assert recoded != frame
    assert _walk_frame(recoded, undo=True) == frame
    stored, *_ = prepare_stored_drawing(frame)
    assert stored_drawing_wire_payload(stored) == frame


def test_a_frame_too_small_to_earn_deflate_is_stored_as_it_travels():
    frame = PackedCanvasHistory().binary_payload()
    stored, magic, version, checksum = prepare_stored_drawing(frame)

    assert stored == frame
    assert (magic, version) == (BINARY_HISTORY_MAGIC, CANVAS_HISTORY_VERSION)
    assert stored_drawing_wire_payload(stored, checksum=checksum) == frame


def test_the_first_format_is_still_read_as_it_was_written():
    """SKCH v1 rows exist; their decoder is the identity and stays."""
    frame = _stroke_history(99).binary_payload()

    assert stored_drawing_format(frame) == (BINARY_HISTORY_MAGIC, CANVAS_HISTORY_VERSION)
    assert stored_drawing_wire_payload(frame, checksum=stored_drawing_checksum(frame)) == frame


def test_the_blob_declares_its_own_format():
    assert stored_drawing_format(GOLDEN[0]) == (b"SKCH", 1)
    stored, *_ = prepare_stored_drawing(_stroke_history(1).binary_payload())
    assert stored_drawing_format(stored) == (b"SKCD", 1)


def test_a_truncated_blob_cannot_be_identified():
    with pytest.raises(UnsupportedStoredDrawingError):
        stored_drawing_format(b"SK")


def test_an_unknown_magic_is_refused_rather_than_guessed():
    blob = b"XXXX" + GOLDEN[0][4:]

    with pytest.raises(UnsupportedStoredDrawingError):
        stored_drawing_wire_payload(blob)


def test_an_unknown_version_of_a_known_magic_is_refused():
    for original in (GOLDEN[0], prepare_stored_drawing(_stroke_history(2).binary_payload())[0]):
        blob = original[:4] + bytes([99]) + original[5:]
        with pytest.raises(UnsupportedStoredDrawingError):
            stored_drawing_wire_payload(blob)


def test_a_flipped_bit_is_caught_by_the_recorded_checksum():
    for original in (GOLDEN[1], prepare_stored_drawing(_stroke_history(3).binary_payload())[0]):
        blob = bytearray(original)
        checksum = stored_drawing_checksum(bytes(blob))
        blob[-1] ^= 0x01
        with pytest.raises(CorruptStoredDrawingError):
            stored_drawing_wire_payload(bytes(blob), checksum=checksum)


def test_a_payload_that_cannot_be_decoded_never_reaches_storage():
    """Structural validation happens on ingest, so no unreadable row is written."""

    with pytest.raises(ValueError):
        prepare_stored_drawing(GOLDEN[1][:-3])


# --- what a compressed blob may claim, and where each claim is stopped -----


def _skcd(declared: int, stream: bytes) -> bytes:
    return _DELTA_HEADER.pack(STORED_DELTA_MAGIC, STORED_DELTA_VERSION, declared) + stream


def _frame_with(action_count: int, offsets: list[int], data: bytes) -> bytes:
    header = struct.pack("<4sBH", BINARY_HISTORY_MAGIC, CANVAS_HISTORY_VERSION, action_count)
    return header + b"".join(struct.pack("<I", o) for o in offsets) + data


def test_a_claim_larger_than_any_wire_frame_is_refused_before_inflating():
    """The declared length is the allocation bound; a bomb cannot get past it
    by lying upward, and it is checked before a byte of stream is read."""
    blob = _skcd(MAX_BINARY_CANVAS_HISTORY_BYTES + 1, b"this is not even a stream")

    with pytest.raises(CorruptStoredDrawingError, match="larger than any wire frame"):
        stored_drawing_wire_payload(blob)


def test_a_stream_that_inflates_past_its_claim_is_stopped_one_byte_in():
    frame = _stroke_history(4).binary_payload()
    honest = prepare_stored_drawing(frame)[0]
    lying = _skcd(len(frame) // 2, honest[_DELTA_HEADER.size :])

    with pytest.raises(CorruptStoredDrawingError, match="declared frame"):
        stored_drawing_wire_payload(lying)


def test_a_bomb_of_zeros_is_bounded_by_its_own_claim():
    """Ten million zeros deflate to a few kilobytes; the claim caps what is
    inflated, and what is inflated is then refused as no frame at all."""
    bomb = zlib.compress(bytes(10_000_000), 9)
    blob = _skcd(1_000, bomb)

    with pytest.raises(CorruptStoredDrawingError):
        stored_drawing_wire_payload(blob)


def test_a_truncated_stream_is_refused():
    frame = _stroke_history(5).binary_payload()
    honest = prepare_stored_drawing(frame)[0]

    with pytest.raises(CorruptStoredDrawingError, match="declared frame"):
        stored_drawing_wire_payload(honest[:-7])


def test_trailing_bytes_after_the_stream_are_refused():
    frame = _stroke_history(6).binary_payload()
    honest = prepare_stored_drawing(frame)[0]

    with pytest.raises(CorruptStoredDrawingError, match="declared frame"):
        stored_drawing_wire_payload(honest + b"\x00")


def test_a_stream_that_is_not_deflate_is_refused():
    with pytest.raises(CorruptStoredDrawingError, match="does not inflate"):
        stored_drawing_wire_payload(_skcd(100, b"\xff" * 100))


@pytest.mark.parametrize(
    ("name", "inner"),
    [
        ("wrong inner magic", b"NOPE" + _frame_with(0, [0], b"")[4:]),
        ("too many actions", _frame_with(MAX_CANVAS_ACTIONS + 1, [0], b"")),
        ("offset table truncated", _frame_with(3, [0], b"")),
        ("offsets not spanning data", _frame_with(1, [0, 3], b"\x00\x00\x00\x00\x00")),
        ("offsets not increasing", _frame_with(2, [0, 5, 5], b"\x00\x00\x00\x00\x00")),
        ("path shorter than a point", _frame_with(1, [0, 7], b"\x00\x00\x00\x00\x01\x00\x00")),
        ("path with a torn point", _frame_with(1, [0, 10], b"\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00")),
    ],
)
def test_an_inflated_frame_is_walked_with_the_wire_caps(name, inner):
    blob = _skcd(len(inner), zlib.compress(inner))

    with pytest.raises(CorruptStoredDrawingError):
        stored_drawing_wire_payload(blob)


def test_more_points_than_the_wire_admits_are_refused_while_walking():
    from app.canvas_history import MAX_CANVAS_POINTS

    points = b"\x00\x00\x00\x00" * (MAX_CANVAS_POINTS + 1)
    record = b"\x00\x00\x00\x00\x01" + points
    inner = _frame_with(1, [0, len(record)], record)
    blob = _skcd(len(inner), zlib.compress(inner))

    with pytest.raises(CorruptStoredDrawingError, match="too many points"):
        stored_drawing_wire_payload(blob)


def test_a_second_stored_format_is_additive(monkeypatch):
    """Registering a future storage-only encoding must not disturb the two
    that exist."""

    def _decode_v3(blob: bytes) -> bytes:
        return GOLDEN[1]

    monkeypatch.setitem(_STORED_DECODERS, (b"SKD3", 1), _decode_v3)
    future = b"SKD3" + bytes([1]) + b"whatever this codec stores"
    stored, *_ = prepare_stored_drawing(_stroke_history(7).binary_payload())

    assert stored_drawing_wire_payload(future) == GOLDEN[1]
    assert stored_drawing_wire_payload(GOLDEN[0]) == GOLDEN[0]
    assert stored_drawing_wire_payload(stored) == _stroke_history(7).binary_payload()
