"""What an uploaded avatar may be, and how one is named (#573).

The client crops and re-encodes a picture to a 256×256 PNG before sending it,
so the server never decodes an image: it checks the bytes are a PNG of exactly
that size and under the cap, and serves them back only ever as `image/png`
with sniffing disabled. A modified client can send any valid PNG up to the cap
and nothing more, which is the whole surface.

Keys are content-addressed - the SHA-256 of the bytes, plus the extension -
so the same picture has one URL for ever and a changed picture is a new URL.
That is what lets every avatar be cached as immutable.
"""
from __future__ import annotations

import hashlib
import re
import struct
from datetime import timedelta

AVATAR_SIZE = 256
MAX_AVATAR_BYTES = 128 * 1024
AVATAR_CONTENT_TYPE = "image/png"
# How long an account waits after a moderator removed its picture.
AVATAR_REUPLOAD_BLOCK = timedelta(days=7)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
AVATAR_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}\.png$")


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
    if not AVATAR_KEY_PATTERN.fullmatch(key):
        raise ValueError("Unknown avatar key.")
    return key


def avatar_url(key: str | None) -> str | None:
    """Where the picture behind `key` is served from; None for no picture."""
    return f"/api/avatars/{key}" if key else None


def avatar_key_for(payload: bytes) -> str:
    return f"{hashlib.sha256(payload).hexdigest()}.png"


def inspect_avatar(payload: bytes) -> tuple[int, int]:
    """Refuse anything but a PNG of exactly AVATAR_SIZE square under the cap.

    Reads only the fixed-position header - signature, then the IHDR chunk's
    width and height - which is the shape check a browser would make before
    drawing it, without handing untrusted bytes to a decoder.
    """
    if len(payload) > MAX_AVATAR_BYTES:
        raise AvatarError(
            f"That picture is too large: {MAX_AVATAR_BYTES // 1024} KiB at most."
        )
    if len(payload) < 33 or not payload.startswith(_PNG_SIGNATURE):
        raise AvatarError("That is not a PNG picture.")
    if payload[12:16] != b"IHDR":
        raise AvatarError("That is not a PNG picture.")
    width, height = struct.unpack(">II", payload[16:24])
    if (width, height) != (AVATAR_SIZE, AVATAR_SIZE):
        raise AvatarError(f"A picture has to be {AVATAR_SIZE} by {AVATAR_SIZE} pixels.")
    return width, height
