"""Durable storage policy for finished drawings.

A drawing on the wire only has to be understood by the client on the other end
of a connection that is open right now, so both ends deploy together and a
version bump is coordinated by definition. A drawing in the database has to be
readable by every future decoder, forever. This module is the boundary between
those two commitments, and it owns exactly two rules:

1. Every format ever written keeps its entry in ``_STORED_DECODERS``. An entry
   is added when a format starts being written and is never removed, because
   removing one makes existing rows unreadable.
2. A decoder returns bytes in the *current wire format*. Clients therefore
   never learn that a stored format exists, and the wire format stays free to
   change without a migration.

Today a stored drawing is a byte-identical SKCH frame, so its decoder is the
identity function and storing costs nothing but a checksum. Should a
storage-only encoding ever be worth it - varint coordinate deltas measure
roughly four times smaller - it declares its own magic, registers its decoder,
and coexists with every row already written. The magic at offset 0 is the
discriminator, which is why no envelope is needed to tell the formats apart.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import struct

from app.canvas_history import (
    BINARY_HISTORY_MAGIC,
    CANVAS_HISTORY_VERSION,
    decode_binary_canvas_history,
)


_FORMAT_HEADER = struct.Struct("<4sB")
STORED_DRAWING_HEADER_SIZE = _FORMAT_HEADER.size


class UnsupportedStoredDrawingError(ValueError):
    """The blob names a format this build has no decoder for."""


class CorruptStoredDrawingError(ValueError):
    """The blob does not match the checksum recorded beside it."""


def _identity(blob: bytes) -> bytes:
    """SKCH v1 is stored exactly as it travels, so reading it is a no-op."""

    return blob


# Never remove an entry. See the module docstring.
_STORED_DECODERS: dict[tuple[bytes, int], Callable[[bytes], bytes]] = {
    (BINARY_HISTORY_MAGIC, CANVAS_HISTORY_VERSION): _identity,
}


def stored_drawing_format(blob: bytes) -> tuple[bytes, int]:
    """Return the ``(magic, version)`` the blob declares for itself."""

    if len(blob) < STORED_DRAWING_HEADER_SIZE:
        raise UnsupportedStoredDrawingError("stored drawing is too short to identify")
    magic, version = _FORMAT_HEADER.unpack_from(blob, 0)
    return magic, version


def stored_drawing_checksum(blob: bytes) -> str:
    """Return the hex digest recorded beside the blob to detect corruption."""

    return hashlib.sha256(blob).hexdigest()


def stored_drawing_wire_payload(blob: bytes, *, checksum: str | None = None) -> bytes:
    """Decode a stored drawing into current-wire-format bytes.

    ``checksum`` is the digest stored in the metadata row. Verification lives
    here rather than in the caller so that no read path can forget it.
    """

    if checksum is not None and stored_drawing_checksum(blob) != checksum:
        raise CorruptStoredDrawingError("stored drawing failed its checksum")
    key = stored_drawing_format(blob)
    decoder = _STORED_DECODERS.get(key)
    if decoder is None:
        magic, version = key
        raise UnsupportedStoredDrawingError(
            f"no decoder for stored drawing format {magic!r} version {version}"
        )
    return decoder(blob)


def prepare_stored_drawing(payload: bytes) -> tuple[bytes, bytes, int, str]:
    """Validate a wire payload for storage and describe what will be written.

    Structural validation happens here, on ingest, and never on retrieval: a
    blob that cannot be decoded must not reach the database, and one that
    already has will be decoded by the client anyway.

    Returns ``(blob, magic, version, checksum)``.
    """

    decode_binary_canvas_history(payload)
    magic, version = stored_drawing_format(payload)
    if (magic, version) not in _STORED_DECODERS:
        raise UnsupportedStoredDrawingError(
            f"refusing to store unreadable format {magic!r} version {version}"
        )
    return payload, magic, version, stored_drawing_checksum(payload)
