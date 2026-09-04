"""A WebP header of any size, built without an image library, for upload tests.

The server reads only the header (R-AVA-01), so a container with the right
size fields and a filler body is what the header check sees of a real file.
The three layouts a browser can produce are all here, because each keeps its
size in a different place.
"""
from __future__ import annotations

import struct


def _riff(chunk: bytes, body: bytes) -> bytes:
    if len(body) % 2:
        body += b"\0"
    inner = b"WEBP" + chunk + struct.pack("<I", len(body)) + body
    return b"RIFF" + struct.pack("<I", len(inner)) + inner


def webp_bytes(
    width: int = 256, height: int = 256, *, seed: int = 0, layout: str = "VP8L"
) -> bytes:
    """A WebP header of the given layout; `seed` changes the filler bytes."""
    filler = bytes((x * 13 + seed) % 256 for x in range(64))
    if layout == "VP8L":
        bits = (width - 1) | ((height - 1) << 14)
        return _riff(b"VP8L", b"\x2f" + struct.pack("<I", bits) + filler)
    if layout == "VP8 ":
        frame_tag = b"\x00\x00\x00"  # key frame, version 0, show frame, partition size 0
        return _riff(
            b"VP8 ",
            frame_tag + b"\x9d\x01\x2a" + struct.pack("<HH", width, height) + filler,
        )
    if layout == "VP8X":
        flags = b"\x10\x00\x00\x00"  # alpha
        return _riff(
            b"VP8X",
            flags
            + (width - 1).to_bytes(3, "little")
            + (height - 1).to_bytes(3, "little")
            + filler,
        )
    raise ValueError(layout)
