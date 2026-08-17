"""Minimal valid PNG bytes for canvas checkpoint tests (signature only)."""
from __future__ import annotations

import struct
import zlib


def tiny_png(*, width: int = 1, height: int = 1, rgb: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    """Return a lossless RGB PNG. The server validates signature and size, not pixels."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
