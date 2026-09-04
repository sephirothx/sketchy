"""What an uploaded avatar may be, and how one is named (#573).

The client crops and re-encodes a picture to a 256×256 WebP - or a PNG where
the browser cannot encode WebP - before sending it, so the server never
decodes an image: it reads the fixed-position header of either format, checks
the picture is exactly that size and under the cap, and serves the bytes back
only ever as the image type it found, with sniffing disabled. A modified
client can send any valid WebP or PNG up to the cap and nothing more, which is
the whole surface.

WebP rather than PNG alone because a photograph at 256×256 is ~136 KiB as a
lossless PNG - over the cap - and ~22 KiB as WebP, and the primary database is
where these bytes live until object storage (#471) exists. PNG stays accepted
because it is what an older Safari produces from a canvas.

Keys are content-addressed - the SHA-256 of the bytes, plus the extension -
so the same picture has one URL for ever and a changed picture is a new URL.
That is what lets every avatar be cached as immutable. The other shape a key
takes is `doodle:<name>`: one of this deployment's own drawings
(avatar_doodles.py), which is served from the frontend's sprite and never
stored as bytes at all.
"""
from __future__ import annotations

import hashlib
import re
import struct
from datetime import timedelta

from app.auth.avatar_doodles import DOODLE_KEY_PREFIX, doodle_name

AVATAR_SIZE = 256
MAX_AVATAR_BYTES = 128 * 1024
# Content type → the extension its key carries. Both are read from a fixed
# header below; nothing else is an avatar.
AVATAR_FORMATS = {"image/webp": "webp", "image/png": "png"}
# How long an account waits after a moderator removed its picture.
AVATAR_REUPLOAD_BLOCK = timedelta(days=7)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_NOT_A_PICTURE = "That is not a WebP or PNG picture."
AVATAR_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}\.(webp|png)$")


class AvatarError(ValueError):
    """An upload that is not an avatar this deployment takes."""


def validate_avatar_key(value: str | None) -> str | None:
    """A stored key: the content address of an uploaded picture, or nothing."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Avatar key must be a string.")
    key = value.strip().lower()
    if not key:
        return None
    if key.startswith(DOODLE_KEY_PREFIX):
        if doodle_name(key) is None:
            raise ValueError("Unknown doodle.")
        return key
    if not AVATAR_KEY_PATTERN.fullmatch(key):
        raise ValueError("Unknown avatar key.")
    return key


def avatar_url(key: str | None) -> str | None:
    """Where the picture behind `key` is drawn from; None for no picture.

    A doodle points into the sprite the frontend ships, by fragment, which is
    what lets the client draw it with the disc's own ink.
    """
    if not key:
        return None
    name = doodle_name(key)
    if name is not None:
        return f"/avatars/doodles.svg#{name}"
    return f"/api/avatars/{key}"


def avatar_key_for(payload: bytes, content_type: str) -> str:
    return f"{hashlib.sha256(payload).hexdigest()}.{AVATAR_FORMATS[content_type]}"


def _png_dimensions(payload: bytes) -> tuple[int, int] | None:
    """The IHDR chunk always comes first, so width and height sit at 16..24."""
    if len(payload) < 33 or payload[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", payload[16:24])


def _webp_dimensions(payload: bytes) -> tuple[int, int] | None:
    """A WebP is a RIFF container whose first chunk names one of three layouts.

    `VP8X` (extended: alpha, animation) keeps the canvas size as two 24-bit
    little-endian values minus one; `VP8L` (lossless) packs two 14-bit values
    minus one after a signature byte; `VP8 ` (lossy) holds them as 14 bits of
    a 16-bit little-endian pair after the key-frame start code. Every one is
    at a fixed offset, so none needs the bitstream read.
    """
    if len(payload) < 30 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
        return None
    chunk = payload[12:16]
    if chunk == b"VP8X":
        width = int.from_bytes(payload[24:27], "little") + 1
        height = int.from_bytes(payload[27:30], "little") + 1
        return width, height
    if chunk == b"VP8L":
        if payload[20] != 0x2F:
            return None
        bits = int.from_bytes(payload[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8 ":
        if payload[23:26] != b"\x9d\x01\x2a":
            return None
        width, height = struct.unpack("<HH", payload[26:30])
        return width & 0x3FFF, height & 0x3FFF
    return None


def inspect_avatar(payload: bytes) -> tuple[str, int, int]:
    """Refuse anything but a WebP or PNG of exactly AVATAR_SIZE square under the cap.

    Returns the content type it found with the dimensions. Reads only the
    fixed-position header of either format - which is the shape check a
    browser would make before drawing it - without handing untrusted bytes to
    a decoder.
    """
    if len(payload) > MAX_AVATAR_BYTES:
        raise AvatarError(
            f"That picture is too large: {MAX_AVATAR_BYTES // 1024} KiB at most."
        )
    if payload.startswith(_PNG_SIGNATURE):
        content_type, dimensions = "image/png", _png_dimensions(payload)
    else:
        content_type, dimensions = "image/webp", _webp_dimensions(payload)
    if dimensions is None:
        raise AvatarError(_NOT_A_PICTURE)
    if dimensions != (AVATAR_SIZE, AVATAR_SIZE):
        raise AvatarError(f"A picture has to be {AVATAR_SIZE} by {AVATAR_SIZE} pixels.")
    return content_type, *dimensions
