"""Compact, versioned binary frames for live drawing Socket.IO events."""
from __future__ import annotations

import base64
import binascii
import math
import struct
from dataclasses import dataclass
from itertools import pairwise

from app.canvas_history import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    COORDINATE_SCALE,
    MAX_BRUSH_WIDTH,
    MAX_PACKED_COORDINATE,
    MIN_PACKED_COORDINATE,
    SHAPE_IDS,
    SHAPE_NAMES,
    color_to_hex,
    color_to_int,
)

LIVE_DRAWING_VERSION = 1
MAX_POINTS_PER_FRAME = 256

PATH_START_TAG = 0
PATH_POINTS_TAG = 1
PATH_END_TAG = 2
SHAPE_TAG = 3
FILL_TAG = 4
CLEAR_TAG = 5
PATH_POINTS_DELTA_TAG = 6
PATH_POINTS_RELATIVE_TAG = 7
PATH_POINTS_END_TAG = 8

_HEADER_VERSION_SHIFT = 4
_HEADER_TAG_MASK = 0x0F
_POINT = struct.Struct("<hh")
_DELTA = struct.Struct("<bb")

# Path points can travel two ways, and the encoder picks per frame.
#
# PATH_POINTS_TAG is absolute: two int16 per point, the original layout. Its
# length is always 1 + 4n, which is a free integrity check - a truncated or
# corrupted frame fails it rather than decoding into different points.
#
# PATH_POINTS_DELTA_TAG stores the first point absolute and every later point
# as a signed-byte offset from the one before it. Consecutive pointer samples
# are milliseconds apart, so that gap usually fits a byte at quarter-pixel
# scale (+/-31.75px) where an absolute coordinate needs two.
#
# It is chosen per frame because whether it wins depends on the device, not on
# the protocol. The threshold is a distance between samples, so it scales with
# the sample rate: ~3810 px/s at 120Hz, ~1905 at 60Hz, ~952 on a throttled
# 30Hz client. Past it, escapes make the delta frame *larger* than the absolute
# one - on exactly the slow devices that most need the saving. Predicting both
# sizes and sending the smaller makes the encoding never worse than it was,
# instead of a bet on how fast the user's hardware samples.
#
# The first point of a delta frame stays absolute so each frame decodes
# independently: a frame arriving late, out of order, or not at all cannot
# corrupt the points in any other.
#
# PATH_POINTS_RELATIVE_TAG (#559) goes one step further: *every* point is a
# signed-byte offset, the first from the last point of the open path - the
# `draw_start` point, or the last point of the previous frame. That drops the
# absolute pair the delta frame spends on its first point, which is most of
# a one-point frame: with the client sending one thinned sample per flush on
# a straight stroke (#560), a frame is 3 bytes instead of 5. The price is
# that the frame does not decode on its own: `decode_live_drawing` returns
# the offsets, and `resolve_relative_points` needs the predecessor, which
# both the server (the open path in `canvas_session`) and a viewer (its own
# history) already hold. A relative frame that arrives with no open path is
# dropped, the way an absolute `draw_move` with no open path already is; and
# a frame the server *dropped* (throttled) closes the path for everyone and
# tells the drawer, so a later relative frame can never be resolved against a
# predecessor the server never recorded (`handlers/drawing.py`).
#
# PATH_POINTS_END_TAG (#603) is the relative layout again, and the frame
# also closes the path: the points the drawer had buffered when the pen
# lifted and the `draw_end` used to travel as two events, sent in the same
# call, with only the second carrying the commit. One frame extends the path
# and ends it atomically - refused whole if the points do not fit, so a
# refused ending never leaves a committed prefix - and carries the commit
# the way `draw_end` did. The one-byte `draw_end` stays for a path with
# nothing buffered. Both produce the same history and hash.
#
# -128 is not a delta but the escape marker, followed by an absolute pair. It
# is what keeps an arbitrarily fast stroke representable rather than refused.
_DELTA_ESCAPE = -128
# -127 in the same position says the path's width changes (#828): one more
# byte follows, the new width, and then the record of the point it applies
# from - the segment ending at that point is the first drawn at it. A pen's
# pressure, quantized to whole pixels by the client, arrives this way.
#
# It lives inside the records because a message is what costs, not a byte. A
# frame of its own would be a second Socket.IO event per change - an envelope,
# a WebSocket header and a unit of the drawing budget, to carry one byte - and
# a width byte on every point would tax the strokes that never change width,
# which is all of them from a mouse. In-band, a change is two bytes in a frame
# that was being sent anyway, and a path with no change is byte for byte what
# it was. The price is one value of the delta range: a step of exactly -127
# quarter-pixels now escapes.
#
# The width is absolute rather than a step from the last one so that a frame
# still validates on its own, the way its points do.
_WIDTH_MARKER = -127
_MIN_DELTA = -126
_MAX_DELTA = 127
_ESCAPE_RECORD_SIZE = 1 + _POINT.size
_WIDTH_RECORD_SIZE = 2

# Above this many payload bytes, a frame travels as a binary attachment;
# at or below it, as base64 inside an ordinary text event.
#
# Socket.IO cannot put binary inside an event without the placeholder envelope:
# `51-["draw",{"_placeholder":true,"num":0}]` is 41 bytes whose entire job is to
# announce that a blob follows, and the blob is then a second WebSocket frame
# with its own header. For a 13-byte frame that is 76% overhead. Base64 expands
# the payload by a third but deletes both, which is a net win until the
# expansion overtakes the envelope it saved - measured at about 85 bytes.
#
# The client picks; the server accepts either and rebroadcasts whatever it was
# given, so the two never have to agree on the threshold. `sync_strokes` is
# untouched and stays binary: histories run to kilobytes, far past the
# crossover.
MAX_BASE64_FRAME_BYTES = 85
#: The largest frame the codec can produce: a full relative frame in which
#: every point escapes and every point changes the width. Without width
#: changes the bound is the absolute frame, 1 + 4n, since the encoder then
#: sends whichever form is smaller; a frame with them is always relative, and
#: escapes where a step is too far rather than falling back.
#: Checked by `tests/test_live_drawing.py`; `socket_server.py` refuses a binary
#: attachment past it before keeping a byte.
MAX_FRAME_BYTES = 1 + MAX_POINTS_PER_FRAME * (_ESCAPE_RECORD_SIZE + _WIDTH_RECORD_SIZE)

# The largest frame that can legitimately arrive, base64-expanded: a delta
# frame's absolute first point, then the same worst case.
_MAX_BASE64_CHARS = ((MAX_FRAME_BYTES + _POINT.size + 2) // 3) * 4
_PATH_START = struct.Struct("<B3sBhh")
_SHAPE = struct.Struct("<BB3sBhhhh")
_FILL = struct.Struct("<B3sHH")


@dataclass(frozen=True, slots=True)
class LiveDrawingPacket:
    event: str
    payload: dict


def _header(tag: int) -> int:
    return (LIVE_DRAWING_VERSION << _HEADER_VERSION_SHIFT) | tag


def _pack_color(color: str) -> bytes:
    try:
        value = color_to_int(color)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("invalid drawing color") from exc
    if not 0 <= value <= 0xFFFFFF or len(color) != 7 or not color.startswith("#"):
        raise ValueError("invalid drawing color")
    return value.to_bytes(3, "big")


def _unpack_color(color: bytes) -> str:
    return color_to_hex(int.from_bytes(color, "big"))


def _pack_coordinate(value: float, canvas_size: int) -> int:
    try:
        packed = round(float(value) * canvas_size * COORDINATE_SCALE)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid drawing coordinate") from exc
    if not MIN_PACKED_COORDINATE <= packed <= MAX_PACKED_COORDINATE:
        raise ValueError("drawing coordinate is outside packed range")
    return packed


def _unpack_coordinate(value: int, canvas_size: int) -> float:
    return value / (canvas_size * COORDINATE_SCALE)


def _is_delta(delta_x: int, delta_y: int) -> bool:
    return (
        _MIN_DELTA <= delta_x <= _MAX_DELTA
        and _MIN_DELTA <= delta_y <= _MAX_DELTA
    )


def _encode_records(
    tag: int,
    packed: list[tuple[int, int]],
    previous: tuple[int, int],
    widths: dict[int, int] | None = None,
    first_index: int = 0,
) -> bytes:
    """Offset records from `previous`, escaping to absolute where one is too far.

    `widths` maps a point's index in the frame to the width that starts
    there; `first_index` is the index `packed[0]` has in the frame.
    """
    frame = bytearray((_header(tag),))
    previous_x, previous_y = previous
    for index, (x, y) in enumerate(packed, first_index):
        if widths and index in widths:
            frame.append(_WIDTH_MARKER & 0xFF)
            frame.append(widths[index])
        delta_x = x - previous_x
        delta_y = y - previous_y
        if _is_delta(delta_x, delta_y):
            frame.extend(_DELTA.pack(delta_x, delta_y))
        else:
            frame.append(_DELTA_ESCAPE & 0xFF)
            frame.extend(_POINT.pack(x, y))
        previous_x, previous_y = x, y
    return bytes(frame)


def _encode_points(
    packed: list[tuple[int, int]],
    previous: tuple[int, int] | None = None,
    widths: dict[int, int] | None = None,
) -> bytes:
    """Pack path points whichever way is smaller for this particular frame.

    With the open path's last point in hand, the relative form is taken
    whenever its first record fits a byte: it is then the smallest of the
    three by construction (no absolute first point). A first point too far
    from the predecessor makes it the largest, so the frame falls back to
    the self-contained forms.

    A width change needs a record to sit in front of, so a frame carrying
    one is never absolute: relative when there is a predecessor, escaping if
    it must, and otherwise the delta form - whose first point is not a
    record, so the change cannot be on it.
    """
    if widths:
        if previous is not None:
            return _encode_records(PATH_POINTS_RELATIVE_TAG, packed, previous, widths)
        if 0 in widths:
            raise ValueError("a width change on the first point needs the open path's last point")
        frame = bytearray(
            _encode_records(PATH_POINTS_DELTA_TAG, packed[1:], packed[0], widths, 1)
        )
        frame[1:1] = _POINT.pack(*packed[0])
        return bytes(frame)
    if previous is not None and _is_delta(packed[0][0] - previous[0], packed[0][1] - previous[1]):
        return _encode_records(PATH_POINTS_RELATIVE_TAG, packed, previous)
    absolute_size = 1 + len(packed) * _POINT.size
    delta_size = 1 + _POINT.size + sum(
        _DELTA.size
        if _is_delta(x - previous_x, y - previous_y)
        else _ESCAPE_RECORD_SIZE
        for (previous_x, previous_y), (x, y) in pairwise(packed)
    )
    if delta_size >= absolute_size:
        frame = bytearray((_header(PATH_POINTS_TAG),))
        for x, y in packed:
            frame.extend(_POINT.pack(x, y))
        return bytes(frame)

    frame = bytearray(_encode_records(PATH_POINTS_DELTA_TAG, packed[1:], packed[0]))
    frame[1:1] = _POINT.pack(*packed[0])
    return bytes(frame)


def _width_changes(widths, point_count: int) -> dict[int, int]:
    """Validate a `widths` list: `(point index, width)` pairs, ascending."""
    if not isinstance(widths, (list, tuple)):
        raise ValueError("invalid width changes")
    changes: dict[int, int] = {}
    last_index = -1
    for change in widths:
        if not isinstance(change, (list, tuple)) or len(change) != 2:
            raise ValueError("invalid width change")
        index, width = change
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not last_index < index < point_count
            or not isinstance(width, int)
            or isinstance(width, bool)
            or not 1 <= width <= MAX_BRUSH_WIDTH
        ):
            raise ValueError("invalid width change")
        changes[index] = width
        last_index = index
    return changes


def _decode_records(
    frame: bytes, offset: int, first_index: int = 0
) -> tuple[list[tuple[int, int] | tuple[None, int, int]], list[tuple[int, int]]]:
    """Walk offset records to the end of the frame.

    Variable-length, so the frame is walked rather than divided. Every step is
    bounded by the frame it is reading and the point count is checked as it
    grows, so a malformed frame is refused rather than read past. A width
    change must be followed by the record of the point it applies from, in
    this frame: one that trails the frame, or sits beside another, is refused.
    """
    records: list[tuple[int, int] | tuple[None, int, int]] = []
    widths: list[tuple[int, int]] = []
    width_pending = False
    while offset < len(frame):
        lead = frame[offset]
        if lead == (_WIDTH_MARKER & 0xFF):
            if width_pending or offset + _WIDTH_RECORD_SIZE > len(frame):
                raise ValueError("invalid width change")
            width = frame[offset + 1]
            if not 1 <= width <= MAX_BRUSH_WIDTH:
                raise ValueError("invalid brush width")
            widths.append((first_index + len(records), width))
            width_pending = True
            offset += _WIDTH_RECORD_SIZE
            continue
        if lead == (_DELTA_ESCAPE & 0xFF):
            offset += 1
            if offset + _POINT.size > len(frame):
                raise ValueError("invalid path-points frame size")
            x, y = _POINT.unpack_from(frame, offset)
            if min(x, y) < MIN_PACKED_COORDINATE:
                raise ValueError("path point is outside packed range")
            offset += _POINT.size
            records.append((None, x, y))
        else:
            if offset + _DELTA.size > len(frame):
                raise ValueError("invalid path-points frame size")
            records.append(_DELTA.unpack_from(frame, offset))
            offset += _DELTA.size
        width_pending = False
        if first_index + len(records) > MAX_POINTS_PER_FRAME:
            raise ValueError("invalid path point count")
    if width_pending:
        raise ValueError("invalid width change")
    return records, widths


def _walk_records(
    records, x: int, y: int
) -> list[tuple[int, int]]:
    """The packed points offset records stand for, from `(x, y)`."""
    packed = []
    for record in records:
        if record[0] is None:
            x, y = record[1], record[2]
        else:
            x += record[0]
            y += record[1]
            if not (
                MIN_PACKED_COORDINATE <= x <= MAX_PACKED_COORDINATE
                and MIN_PACKED_COORDINATE <= y <= MAX_PACKED_COORDINATE
            ):
                raise ValueError("path point is outside packed range")
        packed.append((x, y))
    return packed


def _unpacked_points(packed) -> list[dict]:
    return [
        {
            "x": _unpack_coordinate(point_x, CANVAS_WIDTH),
            "y": _unpack_coordinate(point_y, CANVAS_HEIGHT),
        }
        for point_x, point_y in packed
    ]


def encode_live_drawing(event: str, payload: dict | None = None) -> bytes | int:
    """Encode one action as a binary attachment or compact numeric control."""
    payload = payload or {}
    if event == "draw_start":
        width = payload.get("width")
        if not isinstance(width, int) or isinstance(width, bool) or not 1 <= width <= MAX_BRUSH_WIDTH:
            raise ValueError("invalid brush width")
        return _PATH_START.pack(
            _header(PATH_START_TAG),
            _pack_color(payload.get("color")),
            width,
            _pack_coordinate(payload.get("x"), CANVAS_WIDTH),
            _pack_coordinate(payload.get("y"), CANVAS_HEIGHT),
        )
    if event == "draw_move":
        points = payload.get("points")
        if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS_PER_FRAME:
            raise ValueError("invalid path point count")
        packed = []
        for point in points:
            if not isinstance(point, dict):
                raise ValueError("invalid path point")
            packed.append(
                (
                    _pack_coordinate(point.get("x"), CANVAS_WIDTH),
                    _pack_coordinate(point.get("y"), CANVAS_HEIGHT),
                )
            )
        # The open path's last point, when the caller has it: unlocks the
        # relative form. Optional, so a frame can always be built alone.
        previous = payload.get("previous")
        packed_previous = None
        if previous is not None:
            if not isinstance(previous, dict):
                raise ValueError("invalid path point")
            packed_previous = (
                _pack_coordinate(previous.get("x"), CANVAS_WIDTH),
                _pack_coordinate(previous.get("y"), CANVAS_HEIGHT),
            )
        widths = _width_changes(payload.get("widths") or (), len(packed))
        if payload.get("ends"):
            # The final batch closes the path (#603): always relative, since
            # an ending has an open path to be relative to, escaping where a
            # step is too far rather than falling back.
            if packed_previous is None:
                raise ValueError("an ending batch needs the open path's last point")
            return _encode_records(PATH_POINTS_END_TAG, packed, packed_previous, widths)
        return _encode_points(packed, packed_previous, widths)
    if event == "draw_end":
        return _header(PATH_END_TAG)
    if event == "draw_shape":
        shape = payload.get("shape")
        start = payload.get("from")
        end = payload.get("to")
        width = payload.get("width")
        if (
            shape not in SHAPE_IDS
            or not isinstance(start, dict)
            or not isinstance(end, dict)
            or not isinstance(width, int)
            or isinstance(width, bool)
            or not 1 <= width <= MAX_BRUSH_WIDTH
        ):
            raise ValueError("invalid shape action")
        return _SHAPE.pack(
            _header(SHAPE_TAG),
            SHAPE_IDS[shape],
            _pack_color(payload.get("color")),
            width,
            _pack_coordinate(start.get("x"), CANVAS_WIDTH),
            _pack_coordinate(start.get("y"), CANVAS_HEIGHT),
            _pack_coordinate(end.get("x"), CANVAS_WIDTH),
            _pack_coordinate(end.get("y"), CANVAS_HEIGHT),
        )
    if event == "draw_fill":
        x = payload.get("x")
        y = payload.get("y")
        if (
            isinstance(x, bool)
            or not isinstance(x, (int, float))
            or isinstance(y, bool)
            or not isinstance(y, (int, float))
            or not math.isfinite(x)
            or not math.isfinite(y)
            or not 0 <= x < 1
            or not 0 <= y < 1
        ):
            raise ValueError("invalid fill point")
        return _FILL.pack(
            _header(FILL_TAG),
            _pack_color(payload.get("color")),
            min(CANVAS_WIDTH - 1, int(x * CANVAS_WIDTH)),
            min(CANVAS_HEIGHT - 1, int(y * CANVAS_HEIGHT)),
        )
    if event == "clear_canvas":
        return _header(CLEAR_TAG)
    raise ValueError("unknown drawing event")


def decode_live_drawing(data) -> LiveDrawingPacket:
    """Validate and decode one action, however it arrived on the wire.

    Three shapes, all carrying the same frame:

    - a bare integer for the two control actions, which is already the
      cheapest thing Socket.IO can send;
    - a base64 string, which is how ordinary small frames travel (see
      ``MAX_BASE64_FRAME_BYTES``);
    - raw bytes, for frames too large for base64 to be worth it.
    """
    if isinstance(data, str):
        # Bounded before decoding: a peer controls this length, and base64 is
        # the one input here that expands into an allocation.
        if len(data) > _MAX_BASE64_CHARS:
            raise ValueError("live drawing frame is too large")
        try:
            data = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("live drawing frame is not valid base64") from exc
    if isinstance(data, int) and not isinstance(data, bool):
        if not 0 <= data <= 0xFF:
            raise ValueError("live drawing control is outside byte range")
        frame = bytes((data,))
        if data & _HEADER_TAG_MASK not in (PATH_END_TAG, CLEAR_TAG):
            raise ValueError("data-bearing drawing actions must be binary")
    elif isinstance(data, (bytes, bytearray, memoryview)):
        frame = bytes(data)
    else:
        raise ValueError("live drawing payload has an unsupported type")
    if not frame:
        raise ValueError("live drawing frame is empty")
    version = frame[0] >> _HEADER_VERSION_SHIFT
    tag = frame[0] & _HEADER_TAG_MASK
    if version != LIVE_DRAWING_VERSION:
        raise ValueError("unsupported live drawing version")

    if tag == PATH_START_TAG:
        if len(frame) != _PATH_START.size:
            raise ValueError("invalid path-start frame size")
        _, color, width, x, y = _PATH_START.unpack(frame)
        if not 1 <= width <= MAX_BRUSH_WIDTH:
            raise ValueError("invalid brush width")
        if x < MIN_PACKED_COORDINATE or y < MIN_PACKED_COORDINATE:
            raise ValueError("path point is outside packed range")
        return LiveDrawingPacket(
            "draw_start",
            {
                "x": _unpack_coordinate(x, CANVAS_WIDTH),
                "y": _unpack_coordinate(y, CANVAS_HEIGHT),
                "color": _unpack_color(color),
                "width": width,
            },
        )
    if tag == PATH_POINTS_TAG:
        # Fixed-width records, so the length is its own integrity check: a
        # truncated or corrupted frame fails it rather than decoding into a
        # different set of points.
        if (
            len(frame) <= 1
            or (len(frame) - 1) % _POINT.size
            or (len(frame) - 1) // _POINT.size > MAX_POINTS_PER_FRAME
        ):
            raise ValueError("invalid path-points frame size")
        packed = [
            _POINT.unpack_from(frame, offset)
            for offset in range(1, len(frame), _POINT.size)
        ]
        # int16's floor is the history's width marker, not a coordinate.
        if any(min(point) < MIN_PACKED_COORDINATE for point in packed):
            raise ValueError("path point is outside packed range")
        return LiveDrawingPacket("draw_move", {"points": _unpacked_points(packed)})
    if tag == PATH_POINTS_DELTA_TAG:
        if len(frame) < 1 + _POINT.size:
            raise ValueError("invalid path-points frame size")
        x, y = _POINT.unpack_from(frame, 1)
        if min(x, y) < MIN_PACKED_COORDINATE:
            raise ValueError("path point is outside packed range")
        records, widths = _decode_records(frame, 1 + _POINT.size, first_index=1)
        payload = {"points": _unpacked_points([(x, y), *_walk_records(records, x, y)])}
        if widths:
            payload["widths"] = widths
        return LiveDrawingPacket("draw_move", payload)
    if tag in {PATH_POINTS_RELATIVE_TAG, PATH_POINTS_END_TAG}:
        # Nothing here is a point yet: the records are offsets from a
        # predecessor this frame does not carry. `resolve_relative_points`
        # turns them into points once the caller has looked the predecessor
        # up. The end tag is the same records, and the path is closed once
        # they are recorded (#603).
        records, widths = _decode_records(frame, 1)
        if not records:
            raise ValueError("invalid path-points frame size")
        payload = {"relative": records}
        if widths:
            payload["widths"] = widths
        if tag == PATH_POINTS_END_TAG:
            payload["ends"] = True
        return LiveDrawingPacket("draw_move", payload)
    if tag == PATH_END_TAG:
        if len(frame) != 1:
            raise ValueError("invalid path-end frame size")
        return LiveDrawingPacket("draw_end", {})
    if tag == SHAPE_TAG:
        if len(frame) != _SHAPE.size:
            raise ValueError("invalid shape frame size")
        _, shape_id, color, width, start_x, start_y, end_x, end_y = _SHAPE.unpack(frame)
        if (
            shape_id >= len(SHAPE_NAMES)
            or not 1 <= width <= MAX_BRUSH_WIDTH
            # One packed range for every coordinate the recorder re-packs.
            or min(start_x, start_y, end_x, end_y) < MIN_PACKED_COORDINATE
        ):
            raise ValueError("invalid shape frame")
        return LiveDrawingPacket(
            "draw_shape",
            {
                "shape": SHAPE_NAMES[shape_id],
                "from": {
                    "x": _unpack_coordinate(start_x, CANVAS_WIDTH),
                    "y": _unpack_coordinate(start_y, CANVAS_HEIGHT),
                },
                "to": {
                    "x": _unpack_coordinate(end_x, CANVAS_WIDTH),
                    "y": _unpack_coordinate(end_y, CANVAS_HEIGHT),
                },
                "color": _unpack_color(color),
                "width": width,
            },
        )
    if tag == FILL_TAG:
        if len(frame) != _FILL.size:
            raise ValueError("invalid fill frame size")
        _, color, x, y = _FILL.unpack(frame)
        if x >= CANVAS_WIDTH or y >= CANVAS_HEIGHT:
            raise ValueError("fill point is outside canvas")
        return LiveDrawingPacket(
            "draw_fill",
            {
                # The centre of the pixel, not its corner. A fill seed is an
                # integer pixel that crosses the wire and is re-quantized by
                # the recorder and again by the client's renderer, and
                # `x / CANVAS_WIDTH` does not survive that: 37 of the 800
                # columns and 26 of the 600 rows land a pixel short, because
                # `(x / w) * w` can fall just below `x` in binary floating
                # point and truncation then takes it down. Offsetting to the
                # pixel centre puts the value half a pixel clear of the
                # boundary, which is exact for every column and row.
                #
                # For a flood fill this is not a rounding nicety: one pixel
                # can be the far side of an outline, so the wrong region gets
                # painted entirely.
                "x": (x + 0.5) / CANVAS_WIDTH,
                "y": (y + 0.5) / CANVAS_HEIGHT,
                "color": _unpack_color(color),
            },
        )
    if tag == CLEAR_TAG:
        if len(frame) != 1:
            raise ValueError("invalid clear frame size")
        return LiveDrawingPacket("clear_canvas", {})
    raise ValueError("unknown live drawing tag")


def is_relative(packet: LiveDrawingPacket) -> bool:
    """Whether this `draw_move` still needs its predecessor to become points."""
    return packet.event == "draw_move" and "relative" in packet.payload


def resolve_relative_points(
    packet: LiveDrawingPacket, previous: tuple[float, float]
) -> LiveDrawingPacket:
    """The points a relative frame stands for, given the open path's last point.

    `previous` is in normalized coordinates, as the history keeps it. Every
    resolved point is range-checked the way the delta decoder checks its
    running point, so a frame cannot walk a path off the packed range.
    """
    packed = _walk_records(
        packet.payload["relative"],
        _pack_coordinate(previous[0], CANVAS_WIDTH),
        _pack_coordinate(previous[1], CANVAS_HEIGHT),
    )
    resolved: dict = {"points": _unpacked_points(packed)}
    if packet.payload.get("widths"):
        resolved["widths"] = packet.payload["widths"]
    if packet.payload.get("ends"):
        resolved["ends"] = True
    return LiveDrawingPacket("draw_move", resolved)


def ends_path(packet: LiveDrawingPacket) -> bool:
    """Whether this frame closes the open path: `draw_end`, or a final batch."""
    return packet.event == "draw_end" or (
        packet.event == "draw_move" and bool(packet.payload.get("ends"))
    )
