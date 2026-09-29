"""A real PNG of any size, built without an image library, for upload tests."""
from __future__ import annotations

import struct
import zlib


def _chunk(kind: bytes, body: bytes) -> bytes:
    return (
        struct.pack(">I", len(body))
        + kind
        + body
        + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    )


def png_bytes(
    width: int = 256, height: int = 256, *, seed: int = 0, alpha: int | None = None
) -> bytes:
    """An RGB PNG: `seed` changes the pixels, so two pictures hash differently.
    With `alpha`, an RGBA one whose every pixel has that opacity."""
    channels = 3 if alpha is None else 4
    pixels = bytes((x * 7 + seed) % 256 for x in range(width * 3))
    if alpha is not None:
        pixels = b"".join(pixels[i : i + 3] + bytes([alpha]) for i in range(0, len(pixels), 3))
    row = bytes([0]) + pixels
    raw = row * height
    colour_type = 2 if channels == 3 else 6
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )
