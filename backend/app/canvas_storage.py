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

Three formats exist. ``SKCH`` v1 is the wire frame stored byte for byte, the
only format written before #547; its decoder is the identity function.
``SKCD`` v1 is the same frame with every path's points recoded as deltas from
the previous point, then deflated. A stroke is a run of small movements, and
deltas turn its coordinates into the small repeated numbers deflate is good
at - the realistic benchmark frame stores 4.5 times smaller, where deflate
over the raw frame managed 1.4. Shapes, fills and clears are left as they
are; they have no runs worth recoding.

``SKCD`` v2 is what is written now (#828). A path can hold width markers
between its points, entries shaped like a point whose x is int16's floor. v1
reads and restores them exactly - it treats every entry alike - but it chains
them into the differences, so each marker becomes two large deltas: one to
reach it and one to leave. v2 copies a marker through and differences the
points either side of it against each other, as if it were not there. On a
pen drawing that is the gap between storing a third more than the same
strokes at one width and storing a tenth more (`benchmarks/path_widths.py`);
on a drawing with no markers the two walks are the same walk.

Reading a compressed blob is where the bounds live. The blob declares the
length of the frame it inflates to, which is refused before anything is
allocated if it exceeds the largest frame the wire format can express; the
stream is inflated to at most that length and must end there exactly; and the
frame is walked once more, with the wire format's own action and point caps,
while the deltas are undone. A blob that lies about any of it is corrupt, not
merely unusual. The magic at offset 0 is the discriminator, which is why no
envelope is needed to tell the formats apart.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import struct
import zlib

from app.canvas_history import (
    BINARY_HISTORY_MAGIC,
    CANVAS_HISTORY_VERSION,
    MAX_BINARY_CANVAS_HISTORY_BYTES,
    MAX_CANVAS_ACTIONS,
    MAX_CANVAS_POINTS,
    PATH_TAG,
    decode_binary_canvas_history,
)


_FORMAT_HEADER = struct.Struct("<4sB")
STORED_DRAWING_HEADER_SIZE = _FORMAT_HEADER.size

# The storage-only encoding (#547): magic, version, the inflated frame's
# length, then one deflate stream of the delta-recoded frame.
STORED_DELTA_MAGIC = b"SKCD"
#: The version written now. v1 keeps its decoder below.
STORED_DELTA_VERSION = 2
_FIRST_DELTA_VERSION = 1
_DELTA_HEADER = struct.Struct("<4sBI")
_DEFLATE_LEVEL = 6

# The wire layout the recoding walks. Kept in step with canvas_history by the
# round-trip tests rather than imported: a stored format is frozen at what it
# was when written, and the wire module is free to move.
_FRAME_HEADER = struct.Struct("<4sBH")
_FRAME_OFFSET = struct.Struct("<I")
_PATH_HEADER_SIZE = 5
_POINT = struct.Struct("<HH")
# A width marker's x (#828), as the unsigned value this walk reads, and what
# v2 recodes it to. See `_recode_path_v2`.
_WIDTH_MARKER_X = 0x8000
_RECODED_MARKER = 0xFFFF
_X_VALUES = 0xFFFF
_X_BIAS = 0x7FFF


class UnsupportedStoredDrawingError(ValueError):
    """The blob names a format this build has no decoder for."""


class CorruptStoredDrawingError(ValueError):
    """The blob does not match the checksum recorded beside it, or does not
    hold what its own header says it holds."""


def _identity(blob: bytes) -> bytes:
    """SKCH v1 is stored exactly as it travels, so reading it is a no-op."""

    return blob


def _recode_path_v1(entries: memoryview, undo: bool, out: bytearray) -> None:
    """SKCD v1: every entry differenced against the one before, modulo 2**16.

    Frozen. A width marker (#828) is an entry like any other here, which is
    exact and wasteful: see `_recode_path_v2`.
    """
    previous_x = previous_y = 0
    for x, y in _POINT.iter_unpack(entries):
        if undo:
            x, y = (previous_x + x) & 0xFFFF, (previous_y + y) & 0xFFFF
            out += _POINT.pack(x, y)
        else:
            out += _POINT.pack((x - previous_x) & 0xFFFF, (y - previous_y) & 0xFFFF)
        previous_x, previous_y = x, y


def _recode_path_v2(entries: memoryview, undo: bool, out: bytearray) -> None:
    """SKCD v2: markers stepped over, so the points either side difference
    against each other.

    For that a recoded marker has to be tellable from a recoded point, and
    modulo 2**16 it is not: every 16-bit value is some pair of points'
    difference. But a path's x has only 65,535 values - int16's floor is the
    marker - so x is differenced modulo 65,535 instead, over `x + 32767`.
    Differences then span 0..65,534, and 0xFFFF is left over to say "marker".
    Small steps are the same small numbers either way, so deflate sees what
    it saw. y has no value to spare and needs none; it stays modulo 2**16.
    The chain starts at coordinate zero, as v1's does, so a path's first
    difference is its first point.
    """
    previous_x, previous_y = _X_BIAS, 0
    for x, y in _POINT.iter_unpack(entries):
        if undo:
            if x == _RECODED_MARKER:
                out += _POINT.pack(_WIDTH_MARKER_X, y)
                continue
            previous_x, previous_y = (previous_x + x) % _X_VALUES, (previous_y + y) & 0xFFFF
            out += _POINT.pack((previous_x - _X_BIAS) & 0xFFFF, previous_y)
        else:
            if x == _WIDTH_MARKER_X:
                out += _POINT.pack(_RECODED_MARKER, y)
                continue
            # Unsigned as read; back to the signed coordinate, then biased.
            biased = (x - 0x10000 if x & 0x8000 else x) + _X_BIAS
            out += _POINT.pack((biased - previous_x) % _X_VALUES, (y - previous_y) & 0xFFFF)
            previous_x, previous_y = biased, y


def _walk_frame(
    frame: bytes | bytearray | memoryview, *, undo: bool, recode=_recode_path_v2
) -> bytes:
    """Recode every path's points in place: to deltas, or back from them.

    Coordinates are signed 16-bit on the wire and a delta between two of them
    can exceed that range, so both directions work modulo the number of values
    a coordinate has: restoring adds a delta back the way it was taken, which
    makes the recoding lossless for every value the wire admits. `recode` is
    the version's own walk over one path's entries.

    The structural checks are the wire format's own caps, applied here so a
    stored blob is bounded by what it *claims* before any of it is trusted.
    """

    view = memoryview(frame)
    if len(view) < _FRAME_HEADER.size + _FRAME_OFFSET.size:
        raise CorruptStoredDrawingError("stored frame is truncated")
    magic, version, action_count = _FRAME_HEADER.unpack_from(view)
    if magic != BINARY_HISTORY_MAGIC or version != CANVAS_HISTORY_VERSION:
        raise CorruptStoredDrawingError("stored frame is not a known wire frame")
    if action_count > MAX_CANVAS_ACTIONS:
        raise CorruptStoredDrawingError("stored frame claims too many actions")
    data_start = _FRAME_HEADER.size + (action_count + 1) * _FRAME_OFFSET.size
    if data_start > len(view):
        raise CorruptStoredDrawingError("stored frame offset table is truncated")
    offsets = [
        _FRAME_OFFSET.unpack_from(view, _FRAME_HEADER.size + index * _FRAME_OFFSET.size)[0]
        for index in range(action_count + 1)
    ]
    data_length = len(view) - data_start
    if offsets[0] != 0 or offsets[-1] != data_length:
        raise CorruptStoredDrawingError("stored frame offsets do not span its data")
    out = bytearray(view[:data_start])
    point_count = 0
    for index in range(action_count):
        start, end = data_start + offsets[index], data_start + offsets[index + 1]
        if end <= start:
            raise CorruptStoredDrawingError("stored frame offsets are not increasing")
        record = view[start:end]
        if record[0] != PATH_TAG:
            out += record
            continue
        points_length = len(record) - _PATH_HEADER_SIZE
        if points_length < _POINT.size or points_length % _POINT.size:
            raise CorruptStoredDrawingError("stored path has an invalid length")
        point_count += points_length // _POINT.size
        if point_count > MAX_CANVAS_POINTS:
            raise CorruptStoredDrawingError("stored frame claims too many points")
        out += record[:_PATH_HEADER_SIZE]
        recode(record[_PATH_HEADER_SIZE:], undo, out)
    return bytes(out)


def _encode_delta(frame: bytes) -> bytes:
    """Store a validated wire frame as SKCD v2."""

    recoded = _walk_frame(frame, undo=False)
    return _DELTA_HEADER.pack(STORED_DELTA_MAGIC, STORED_DELTA_VERSION, len(frame)) + zlib.compress(
        recoded, _DEFLATE_LEVEL
    )


def _decode_delta(blob: bytes, recode=_recode_path_v2) -> bytes:
    """Read an SKCD blob back into the wire frame it was made from."""

    if len(blob) < _DELTA_HEADER.size:
        raise CorruptStoredDrawingError("stored drawing header is truncated")
    _, _, declared = _DELTA_HEADER.unpack_from(blob)
    if declared > MAX_BINARY_CANVAS_HISTORY_BYTES:
        raise CorruptStoredDrawingError("stored drawing claims a frame larger than any wire frame")
    inflater = zlib.decompressobj()
    try:
        # One byte past the claim: an honest stream stops exactly at it, and
        # a stream that keeps going is refused without being read further.
        recoded = inflater.decompress(blob[_DELTA_HEADER.size :], declared + 1)
    except zlib.error as error:
        raise CorruptStoredDrawingError("stored drawing does not inflate") from error
    if len(recoded) != declared or not inflater.eof or inflater.unused_data:
        raise CorruptStoredDrawingError("stored drawing does not inflate to its declared frame")
    return _walk_frame(recoded, undo=True, recode=recode)


def _decode_delta_v1(blob: bytes) -> bytes:
    return _decode_delta(blob, _recode_path_v1)


# Never remove an entry. See the module docstring.
_STORED_DECODERS: dict[tuple[bytes, int], Callable[[bytes], bytes]] = {
    (BINARY_HISTORY_MAGIC, CANVAS_HISTORY_VERSION): _identity,
    (STORED_DELTA_MAGIC, _FIRST_DELTA_VERSION): _decode_delta_v1,
    (STORED_DELTA_MAGIC, STORED_DELTA_VERSION): _decode_delta,
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
    already has will be decoded by the client anyway. The blob written is the
    current SKCD encoding of the frame; the checksum is over those stored bytes, so a
    read verifies what the database holds before decoding any of it.

    Returns ``(blob, magic, version, checksum)``.
    """

    decode_binary_canvas_history(payload)
    blob = _encode_delta(payload)
    if len(blob) >= len(payload):
        # Deflate has a fixed cost that a frame of a few actions never earns
        # back; such a frame is stored as it travels. A stored drawing is
        # therefore never larger than its wire frame, and the identity
        # decoder keeps being exercised by real rows.
        return payload, BINARY_HISTORY_MAGIC, CANVAS_HISTORY_VERSION, stored_drawing_checksum(payload)
    return blob, STORED_DELTA_MAGIC, STORED_DELTA_VERSION, stored_drawing_checksum(blob)
