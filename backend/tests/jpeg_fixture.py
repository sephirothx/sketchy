"""A JPEG header of any size, built without an image library, for upload tests.

The server walks only the segments up to the frame header and checks the file
ends where a JPEG ends (R-AVA-01), so the segments a canvas writes before it -
JFIF, a quantisation table - a frame header with the right size, a Huffman
table, a scan header and a filler body are what that check sees of a real file.
"""
from __future__ import annotations

import struct


def _segment(marker: int, body: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(body) + 2) + body


def jpeg_bytes(
    width: int = 256,
    height: int = 256,
    *,
    seed: int = 0,
    frame: int = 0xC0,
    precision: int = 8,
    components: int = 3,
) -> bytes:
    """A JPEG with a baseline frame header (`frame=0xC2` for progressive);
    `seed` changes the filler bytes, so two pictures hash differently."""
    jfif = _segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    quantisation = _segment(0xDB, b"\x00" + bytes(range(1, 65)))
    sof = _segment(
        frame,
        struct.pack(">BHHB", precision, height, width, components)
        + b"".join(bytes([index + 1, 0x11, 0]) for index in range(components)),
    )
    huffman = _segment(0xC4, b"\x00" + b"\x01" + b"\x00" * 15 + b"\x00")
    scan = _segment(
        0xDA,
        bytes([components])
        + b"".join(bytes([index + 1, 0x00]) for index in range(components))
        + b"\x00\x3f\x00",
    )
    body = bytes((x * 29 + seed) % 255 for x in range(96))
    return b"\xff\xd8" + jfif + quantisation + sof + huffman + scan + body + b"\xff\xd9"
