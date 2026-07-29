"""Compact, versioned binary frames for live drawing Socket.IO events."""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

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

_HEADER_VERSION_SHIFT = 4
_HEADER_TAG_MASK = 0x0F
_POINT = struct.Struct("<hh")
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
        frame = bytearray((_header(PATH_POINTS_TAG),))
        for point in points:
            if not isinstance(point, dict):
                raise ValueError("invalid path point")
            frame.extend(
                _POINT.pack(
                    _pack_coordinate(point.get("x"), CANVAS_WIDTH),
                    _pack_coordinate(point.get("y"), CANVAS_HEIGHT),
                )
            )
        return bytes(frame)
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
    """Validate and decode one binary action or numeric control payload."""
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
        if (
            len(frame) <= 1
            or (len(frame) - 1) % _POINT.size
            or (len(frame) - 1) // _POINT.size > MAX_POINTS_PER_FRAME
        ):
            raise ValueError("invalid path-points frame size")
        points = [
            {
                "x": _unpack_coordinate(x, CANVAS_WIDTH),
                "y": _unpack_coordinate(y, CANVAS_HEIGHT),
            }
            for x, y in (
                _POINT.unpack_from(frame, offset)
                for offset in range(1, len(frame), _POINT.size)
            )
        ]
        return LiveDrawingPacket("draw_move", {"points": points})
    if tag == PATH_END_TAG:
        if len(frame) != 1:
            raise ValueError("invalid path-end frame size")
        return LiveDrawingPacket("draw_end", {})
    if tag == SHAPE_TAG:
        if len(frame) != _SHAPE.size:
            raise ValueError("invalid shape frame size")
        _, shape_id, color, width, start_x, start_y, end_x, end_y = _SHAPE.unpack(frame)
        if shape_id >= len(SHAPE_NAMES) or not 1 <= width <= MAX_BRUSH_WIDTH:
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
                "x": x / CANVAS_WIDTH,
                "y": y / CANVAS_HEIGHT,
                "color": _unpack_color(color),
            },
        )
    if tag == CLEAR_TAG:
        if len(frame) != 1:
            raise ValueError("invalid clear frame size")
        return LiveDrawingPacket("clear_canvas", {})
    raise ValueError("unknown live drawing tag")
