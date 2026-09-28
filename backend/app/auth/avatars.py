"""What an uploaded avatar may be, and how one is named (#573).

The client crops and re-encodes a picture to a 256×256 WebP before sending
it - or, in a browser that cannot encode WebP, a JPEG, or a PNG when the crop
has transparency - so the server never decodes an image: it reads the header
of each format, checks the picture is exactly that size and under the cap, and
serves the bytes back only ever as the image type it found, with sniffing
disabled. A modified client can send any valid WebP, PNG or JPEG up to the cap
and nothing more, which is the whole surface.

WebP rather than PNG alone because a photograph at 256×256 is ~136 KiB as a
lossless PNG - over the cap - and ~22 KiB as WebP, and the primary database is
where these bytes live; #471 measured the blobs and kept them inline (N-18).
JPEG because WebKit - every iPhone browser, and Safari on a Mac - cannot encode
WebP from a canvas and silently hands back a PNG: 10 of 14 real photographs
came out over the cap and were refused as "too detailed", where as JPEG at
0.85 the same 14 are 13-43 KiB (#1263). PNG stays for a crop with
transparency, the one thing JPEG cannot carry.

Keys are content-addressed - the SHA-256 of the bytes, plus the extension -
so the same picture has one URL for ever and a changed picture is a new URL.
That is what lets every avatar be cached as immutable. The other shape a key
takes is `doodle:<name>`: one of this deployment's own drawings
(`avatar_doodles.py`), served from the frontend's sprite and never stored as
bytes at all.
"""
from __future__ import annotations

import hashlib
import re
import struct
from datetime import timedelta

from app.auth.avatar_doodles import DOODLE_KEY_PREFIX, doodle_name

AVATAR_SIZE = 256
MAX_AVATAR_BYTES = 128 * 1024
# Content type → the extension its key carries. Each is read from its header
# below; nothing else is an avatar.
AVATAR_FORMATS = {"image/webp": "webp", "image/png": "png", "image/jpeg": "jpg"}
# How long an account waits before it may upload again, by how many pictures
# a moderator has taken down from it. The first costs nothing: a picture can
# be wrong without its owner meaning anything by it, and a removal they are
# told about is already the correction. Doing it again is a pattern rather
# than a misjudgement, so the wait starts and then grows.
#
# It stops at ninety days rather than becoming permanent. A fourth removal is
# no longer really an avatar problem, and the remedy that fits it is a
# suspension a moderator decides on - not a block that quietly never lifts and
# that nothing in the app can lift for them.
AVATAR_REUPLOAD_BLOCKS = (
    timedelta(0),
    timedelta(days=7),
    timedelta(days=30),
    timedelta(days=90),
)


def avatar_reupload_block(prior_removals: int) -> timedelta:
    """The wait after a moderator removes a picture, given how many they have
    removed from this account before this one.

    `prior_removals` counts only removals a moderator carried out. Taking your
    own picture down is not a punishment (R-AVA-04) and must never move an
    account up this ladder.
    """
    index = min(max(prior_removals, 0), len(AVATAR_REUPLOAD_BLOCKS) - 1)
    return AVATAR_REUPLOAD_BLOCKS[index]

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Start of image, then the first marker's own 0xFF.
_JPEG_SIGNATURE = b"\xff\xd8\xff"
NOT_A_PICTURE = "That is not a WebP, PNG or JPEG picture."
AVATAR_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}\.(webp|png|jpg)$")


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
    what lets the client draw it through `<use>` in the disc's own ink.
    """
    if not key:
        return None
    name = doodle_name(key)
    if name is not None:
        return f"/avatars/doodles.svg#{name}"
    return f"/api/avatars/{key}"


def uploaded_avatar_key(key: str | None) -> str | None:
    """`key` if it names a picture somebody uploaded, otherwise None.

    What moderation reads. A doodle is this deployment's own drawing, so it is
    not player-submitted content: it cannot be reported, and a removal has
    nothing to take down in it (R-AVA-09).
    """
    return key if key and AVATAR_KEY_PATTERN.fullmatch(key) else None


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


# Frame headers a browser draws: baseline and progressive Huffman. The other
# SOF kinds - extended, lossless, hierarchical, arithmetic-coded - are ones a
# canvas never writes and not every browser decodes.
_JPEG_FRAMES = {0xC0, 0xC2}
# The only segments that may come before the frame header: application data
# (JFIF, Exif, ...), quantisation and Huffman tables, the restart interval,
# arithmetic-coding conditioning and comments. Everything else is refused,
# because it is where the walk and a decoder could part ways: a decoder reads
# `FF 00` as a stuffed byte to skip and scans on for the next marker, so a
# walk that took it for a segment with a length could be steered onto a fake
# 256x256 frame header inside an APP1 that the decoder skips whole - reading
# the real one after it, 4400 x 4400 (review of #1263).
_JPEG_BEFORE_FRAME = {*range(0xE0, 0xF0), 0xDB, 0xC4, 0xDD, 0xCC, 0xFE}


def _jpeg_dimensions(payload: bytes) -> tuple[int, int] | None:
    """A JPEG keeps its size in the frame header, after however many segments
    the encoder chose to write first (JFIF, quantisation tables, ...).

    So the header is walked rather than read at an offset: each segment is a
    marker and a big-endian length that counts itself, and the walk stops at
    the first frame header - 8-bit, one or three components, exactly as long
    as that many components make it, `_JPEG_FRAMES` only. It refuses a marker
    outside `_JPEG_BEFORE_FRAME`, a byte where a marker should be, and anything
    that runs past the end. Still no decoder: the bytes after the frame header
    are never read, only the end-of-image marker that closes every file a
    canvas writes, which is what refuses a truncated upload.
    """
    if not payload.startswith(_JPEG_SIGNATURE) or not payload.endswith(b"\xff\xd9"):
        return None
    index = 2
    while index + 4 <= len(payload):
        if payload[index] != 0xFF:
            return None
        marker = payload[index + 1]
        if marker == 0xFF:
            # A fill byte before the marker proper.
            index += 1
            continue
        if marker not in _JPEG_BEFORE_FRAME and marker not in _JPEG_FRAMES:
            return None
        length = int.from_bytes(payload[index + 2 : index + 4], "big")
        if length < 2 or index + 2 + length > len(payload):
            return None
        if marker in _JPEG_FRAMES:
            if length < 8:
                return None
            precision = payload[index + 4]
            height, width = struct.unpack(">HH", payload[index + 5 : index + 9])
            components = payload[index + 9]
            if precision != 8 or components not in (1, 3) or length != 8 + 3 * components:
                return None
            return width, height
        index += 2 + length
    return None


def image_dimensions(payload: bytes) -> tuple[int, int] | None:
    """Width and height of a PNG, JPEG or WebP, read from its header without
    decoding anything; None when it is none of them."""
    if payload.startswith(_PNG_SIGNATURE):
        return _png_dimensions(payload)
    if payload.startswith(_JPEG_SIGNATURE):
        return _jpeg_dimensions(payload)
    return _webp_dimensions(payload)


def inspect_avatar(payload: bytes) -> tuple[str, int, int]:
    """Refuse anything but a WebP, PNG or JPEG of exactly AVATAR_SIZE square
    under the cap.

    Returns the content type it found with the dimensions. Reads only the
    header of each format - which is the shape check a browser would make
    before drawing it - without handing untrusted bytes to a decoder.
    """
    if len(payload) > MAX_AVATAR_BYTES:
        raise AvatarError(
            f"That picture is too large: {MAX_AVATAR_BYTES // 1024} KiB at most."
        )
    if payload.startswith(_PNG_SIGNATURE):
        content_type, dimensions = "image/png", _png_dimensions(payload)
    elif payload.startswith(_JPEG_SIGNATURE):
        content_type, dimensions = "image/jpeg", _jpeg_dimensions(payload)
    else:
        content_type, dimensions = "image/webp", _webp_dimensions(payload)
    if dimensions is None:
        raise AvatarError(NOT_A_PICTURE)
    if dimensions != (AVATAR_SIZE, AVATAR_SIZE):
        raise AvatarError(f"A picture has to be {AVATAR_SIZE} by {AVATAR_SIZE} pixels.")
    return content_type, *dimensions
