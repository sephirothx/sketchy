"""What a stored drawing promises: readable forever, and never a wire format."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.canvas_history import BINARY_HISTORY_MAGIC, CANVAS_HISTORY_VERSION
from app.canvas_storage import (
    _STORED_DECODERS,
    CorruptStoredDrawingError,
    UnsupportedStoredDrawingError,
    prepare_stored_drawing,
    stored_drawing_checksum,
    stored_drawing_format,
    stored_drawing_wire_payload,
)


# Stored bytes are wire bytes today, so the cross-language wire fixtures are
# also the golden stored fixtures - and they stay one file, so no frontend test
# can start asserting on the stored format and recreate the coupling.
FIXTURES = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "canvas_protocol_v1.json").read_text()
)
GOLDEN = [bytes.fromhex(entry["binary"]) for entry in FIXTURES["histories"]]


@pytest.mark.parametrize("blob", GOLDEN)
def test_a_golden_wire_history_survives_a_storage_round_trip(blob):
    stored, magic, version, checksum = prepare_stored_drawing(blob)

    assert stored == blob, "storing must not transform the bytes"
    assert (magic, version) == (BINARY_HISTORY_MAGIC, CANVAS_HISTORY_VERSION)
    assert stored_drawing_wire_payload(stored, checksum=checksum) == blob


def test_the_blob_declares_its_own_format():
    magic, version = stored_drawing_format(GOLDEN[0])

    assert magic == b"SKCH"
    assert version == 1


def test_a_truncated_blob_cannot_be_identified():
    with pytest.raises(UnsupportedStoredDrawingError):
        stored_drawing_format(b"SK")


def test_an_unknown_magic_is_refused_rather_than_guessed():
    blob = b"XXXX" + GOLDEN[0][4:]

    with pytest.raises(UnsupportedStoredDrawingError):
        stored_drawing_wire_payload(blob)


def test_an_unknown_version_of_a_known_magic_is_refused():
    blob = GOLDEN[0][:4] + bytes([99]) + GOLDEN[0][5:]

    with pytest.raises(UnsupportedStoredDrawingError):
        stored_drawing_wire_payload(blob)


def test_a_flipped_bit_is_caught_by_the_recorded_checksum():
    blob = bytearray(GOLDEN[1])
    checksum = stored_drawing_checksum(bytes(blob))
    blob[-1] ^= 0x01

    with pytest.raises(CorruptStoredDrawingError):
        stored_drawing_wire_payload(bytes(blob), checksum=checksum)


def test_a_payload_that_cannot_be_decoded_never_reaches_storage():
    """Structural validation happens on ingest, so no unreadable row is written."""

    with pytest.raises(ValueError):
        prepare_stored_drawing(GOLDEN[1][:-3])


def test_a_second_stored_format_is_additive(monkeypatch):
    """Registering a future storage-only encoding must not disturb SKCH v1."""

    def _decode_v2(blob: bytes) -> bytes:
        # A real one would re-encode; returning a known frame is enough to
        # prove dispatch reached this decoder rather than the identity.
        return GOLDEN[1]

    monkeypatch.setitem(_STORED_DECODERS, (b"SKD2", 1), _decode_v2)
    future = b"SKD2" + bytes([1]) + b"whatever this codec stores"

    assert stored_drawing_wire_payload(future) == GOLDEN[1]
    assert stored_drawing_wire_payload(GOLDEN[0]) == GOLDEN[0]
