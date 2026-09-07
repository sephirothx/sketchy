"""Compact, versioned drawing-history models and wire encoding."""
from __future__ import annotations

import struct
import sys
import zlib
from array import array
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from dataclasses import field
from itertools import pairwise
from typing import TypeAlias

CANVAS_HISTORY_VERSION = 1
BINARY_HISTORY_MAGIC = b"SKCH"
CANVAS_WIDTH = 800
CANVAS_HEIGHT = 600
MAX_BRUSH_WIDTH = 64
MAX_CANVAS_ACTIONS = 20_000
MAX_CANVAS_POINTS = 25_000
COORDINATE_SCALE = 4
MIN_PACKED_COORDINATE = -(2**15)
MAX_PACKED_COORDINATE = 2**15 - 1

PATH_TAG = 0
SHAPE_TAG = 1
FILL_TAG = 2
CLEAR_TAG = 3

SHAPE_IDS = {"rectangle": 0, "ellipse": 1, "triangle": 2}
SHAPE_NAMES = tuple(SHAPE_IDS)

_PATH_HEADER = struct.Struct("<B3sB")
_PATH_POINT = struct.Struct("<hh")
_SHAPE_ACTION = struct.Struct("<BB3sBhhhh")
_FILL_ACTION = struct.Struct("<B3sHH")
_CLEAR_ACTION = struct.Struct("<B")
_BINARY_HEADER = struct.Struct("<4sBH")
_BINARY_OFFSET = struct.Struct("<I")
# array("I") is the wire layout for the offset table already, so the table can
# move as one block instead of one struct call per action - as long as the
# platform agrees on width and byte order.
_OFFSETS_ARE_WIRE_LAYOUT = (
    array("I").itemsize == _BINARY_OFFSET.size and sys.byteorder == "little"
)
_HASH_RECORD_LENGTH = struct.Struct("<I")

# The largest valid history uses all 20,000 action slots, puts all 25,000
# points in one path, and fills the remaining slots with the larger fixed-size
# shape record. This is an invariant of the binary layout, not a target size.
MAX_BINARY_CANVAS_HISTORY_BYTES = (
    _BINARY_HEADER.size
    + (MAX_CANVAS_ACTIONS + 1) * _BINARY_OFFSET.size
    + MAX_CANVAS_ACTIONS * _SHAPE_ACTION.size
    + MAX_CANVAS_POINTS * _PATH_POINT.size
    + _PATH_HEADER.size
    - _SHAPE_ACTION.size
)

HISTORY_HASH_INITIAL = 0


@dataclass(slots=True)
class PathAction:
    points: list[tuple[float, float]]
    color: int
    width: int


@dataclass(slots=True)
class ShapeAction:
    shape: str
    start: tuple[float, float]
    end: tuple[float, float]
    color: int
    width: int


@dataclass(slots=True)
class FillAction:
    x: int
    y: int
    color: int


@dataclass(slots=True)
class ClearAction:
    pass


CanvasAction: TypeAlias = PathAction | ShapeAction | FillAction | ClearAction


@dataclass(frozen=True, slots=True)
class PoppedCanvasAction:
    tag: int
    point_count: int = 0


def _packed_color(color: int) -> bytes:
    return color.to_bytes(3, "big")


def _unpacked_color(color: bytes) -> int:
    return int.from_bytes(color, "big")


def _pack_coordinate(value: float, canvas_size: int) -> int:
    packed = round(value * canvas_size * COORDINATE_SCALE)
    if not MIN_PACKED_COORDINATE <= packed <= MAX_PACKED_COORDINATE:
        raise ValueError("canvas coordinate is outside packed range")
    return packed


def _unpack_coordinate(value: int, canvas_size: int) -> float:
    return value / (canvas_size * COORDINATE_SCALE)


@dataclass(slots=True)
class PackedCanvasHistory(Sequence[CanvasAction]):
    """Canvas actions stored in one packed byte buffer.

    Offsets contain one unsigned 32-bit start position per action, preserving
    constant-time semantic Undo without a Python object graph per point.
    """

    data: bytearray = field(default_factory=bytearray)
    offsets: array = field(default_factory=lambda: array("I"))

    def __len__(self) -> int:
        return len(self.offsets)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[position] for position in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError("canvas action index out of range")
        start = self.offsets[index]
        end = self.offsets[index + 1] if index + 1 < len(self) else len(self.data)
        tag = self.data[start]
        if tag == PATH_TAG:
            _, color, width = _PATH_HEADER.unpack_from(self.data, start)
            points = [
                (
                    _unpack_coordinate(x, CANVAS_WIDTH),
                    _unpack_coordinate(y, CANVAS_HEIGHT),
                )
                for x, y in (
                    _PATH_POINT.unpack_from(self.data, offset)
                    for offset in range(
                        start + _PATH_HEADER.size,
                        end,
                        _PATH_POINT.size,
                    )
                )
            ]
            return PathAction(
                points=points,
                color=_unpacked_color(color),
                width=width,
            )
        if tag == SHAPE_TAG:
            _, shape_id, color, width, start_x, start_y, end_x, end_y = (
                _SHAPE_ACTION.unpack_from(self.data, start)
            )
            return ShapeAction(
                shape=SHAPE_NAMES[shape_id],
                start=(
                    _unpack_coordinate(start_x, CANVAS_WIDTH),
                    _unpack_coordinate(start_y, CANVAS_HEIGHT),
                ),
                end=(
                    _unpack_coordinate(end_x, CANVAS_WIDTH),
                    _unpack_coordinate(end_y, CANVAS_HEIGHT),
                ),
                color=_unpacked_color(color),
                width=width,
            )
        if tag == FILL_TAG:
            _, color, x, y = _FILL_ACTION.unpack_from(self.data, start)
            return FillAction(x=x, y=y, color=_unpacked_color(color))
        return ClearAction()

    def __iter__(self) -> Iterator[CanvasAction]:
        for index in range(len(self)):
            yield self[index]

    def __eq__(self, other) -> bool:
        if isinstance(other, PackedCanvasHistory):
            return self.data == other.data and self.offsets == other.offsets
        if isinstance(other, Sequence):
            return list(self) == list(other)
        return NotImplemented

    def clear(self) -> None:
        self.data.clear()
        del self.offsets[:]

    def record_bytes(self, index: int) -> memoryview:
        """Return the canonical packed bytes for one semantic action."""
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError("canvas action index out of range")
        start = self.offsets[index]
        end = self.offsets[index + 1] if index + 1 < len(self) else len(self.data)
        return memoryview(self.data)[start:end]

    def append_path(
        self,
        points: Sequence[tuple[float, float]],
        *,
        color: int,
        width: int,
    ) -> int:
        record = bytearray(
            _PATH_HEADER.pack(PATH_TAG, _packed_color(color), width)
        )
        for x, y in points:
            record.extend(
                _PATH_POINT.pack(
                    _pack_coordinate(x, CANVAS_WIDTH),
                    _pack_coordinate(y, CANVAS_HEIGHT),
                )
            )
        self.offsets.append(len(self.data))
        self.data.extend(record)
        return len(self) - 1

    def last_path_point(self, index: int) -> tuple[float, float]:
        """The last point of the path at `index`, in normalized coordinates.

        What a relative `draw_move` frame (#559) is resolved against: the
        record's final four bytes, read in place rather than by decoding
        the path.
        """
        if index != len(self) - 1 or self.data[self.offsets[index]] != PATH_TAG:
            raise ValueError("only the active final path has a last point")
        x, y = _PATH_POINT.unpack_from(self.data, len(self.data) - _PATH_POINT.size)
        return (
            _unpack_coordinate(x, CANVAS_WIDTH),
            _unpack_coordinate(y, CANVAS_HEIGHT),
        )

    def extend_path(
        self,
        index: int,
        points: Sequence[tuple[float, float]],
    ) -> None:
        if index != len(self) - 1 or self.data[self.offsets[index]] != PATH_TAG:
            raise ValueError("only the active final path can be extended")
        packed_points = bytearray()
        for x, y in points:
            packed_points.extend(
                _PATH_POINT.pack(
                    _pack_coordinate(x, CANVAS_WIDTH),
                    _pack_coordinate(y, CANVAS_HEIGHT),
                )
            )
        self.data.extend(packed_points)

    def append_shape(
        self,
        *,
        shape: str,
        start: tuple[float, float],
        end: tuple[float, float],
        color: int,
        width: int,
    ) -> None:
        record = _SHAPE_ACTION.pack(
            SHAPE_TAG,
            SHAPE_IDS[shape],
            _packed_color(color),
            width,
            _pack_coordinate(start[0], CANVAS_WIDTH),
            _pack_coordinate(start[1], CANVAS_HEIGHT),
            _pack_coordinate(end[0], CANVAS_WIDTH),
            _pack_coordinate(end[1], CANVAS_HEIGHT),
        )
        self.offsets.append(len(self.data))
        self.data.extend(record)

    def append_fill(self, *, x: int, y: int, color: int) -> None:
        self.offsets.append(len(self.data))
        self.data.extend(
            _FILL_ACTION.pack(FILL_TAG, _packed_color(color), x, y)
        )

    def append_clear(self) -> None:
        self.offsets.append(len(self.data))
        self.data.extend(_CLEAR_ACTION.pack(CLEAR_TAG))

    def last_is_clear(self) -> bool:
        return bool(self) and self.data[self.offsets[-1]] == CLEAR_TAG

    def binary_payload(self, start: int = 0) -> bytes:
        """Return one versioned, self-delimiting binary synchronization frame.

        `start` drops the actions before it, so a client that already holds a
        verified prefix can be sent only what it is missing. The frame is
        otherwise identical, which is what lets the same decoder read both.
        """
        if not 0 <= start <= len(self):
            raise IndexError("canvas history slice is out of range")
        base = self.offsets[start] if start < len(self) else len(self.data)
        payload = bytearray(
            _BINARY_HEADER.pack(
                BINARY_HISTORY_MAGIC,
                CANVAS_HISTORY_VERSION,
                len(self) - start,
            )
        )
        table = array("I", (offset - base for offset in self.offsets[start:]))
        table.append(len(self.data) - base)
        if _OFFSETS_ARE_WIRE_LAYOUT:
            payload.extend(table.tobytes())
        else:
            for offset in table:
                payload.extend(_BINARY_OFFSET.pack(offset))
        payload.extend(memoryview(self.data)[base:])
        return bytes(payload)

    def pop(self) -> PoppedCanvasAction:
        if not self:
            raise IndexError("pop from empty canvas history")
        start = self.offsets[-1]
        tag = self.data[start]
        point_count = (
            (len(self.data) - start - _PATH_HEADER.size) // _PATH_POINT.size
            if tag == PATH_TAG
            else 0
        )
        self.offsets.pop()
        del self.data[start:]
        return PoppedCanvasAction(tag=tag, point_count=point_count)


def extend_history_hash(previous: int, record: bytes | bytearray | memoryview) -> int:
    """Hash one length-delimited canonical action onto a history prefix."""
    value = zlib.crc32(_HASH_RECORD_LENGTH.pack(len(record)), previous)
    return zlib.crc32(record, value)


def canvas_history_hash(history: PackedCanvasHistory) -> int:
    value = HISTORY_HASH_INITIAL
    for index in range(len(history)):
        value = extend_history_hash(value, history.record_bytes(index))
    return value


def color_to_int(color: str) -> int:
    return int(color.removeprefix("#"), 16)


def color_to_hex(color: int) -> str:
    return f"#{color:06x}"

def decode_binary_canvas_history(payload) -> PackedCanvasHistory:
    """Validate and decode a packed synchronization frame."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ValueError("binary canvas history must be bytes")
    view = memoryview(payload)
    if len(view) < _BINARY_HEADER.size + _BINARY_OFFSET.size:
        raise ValueError("binary canvas history is truncated")
    magic, version, action_count = _BINARY_HEADER.unpack_from(view)
    if magic != BINARY_HISTORY_MAGIC or version != CANVAS_HISTORY_VERSION:
        raise ValueError("unsupported binary canvas history")
    if action_count > MAX_CANVAS_ACTIONS:
        raise ValueError("binary canvas history contains too many actions")

    data_start = (
        _BINARY_HEADER.size
        + (action_count + 1) * _BINARY_OFFSET.size
    )
    if data_start > len(view):
        raise ValueError("binary canvas history offset table is truncated")
    if _OFFSETS_ARE_WIRE_LAYOUT:
        table = array("I")
        table.frombytes(view[_BINARY_HEADER.size:data_start])
        offsets_with_end = table.tolist()
    else:
        offsets_with_end = [
            _BINARY_OFFSET.unpack_from(
                view,
                _BINARY_HEADER.size + index * _BINARY_OFFSET.size,
            )[0]
            for index in range(action_count + 1)
        ]
    data_length = len(view) - data_start
    if (
        offsets_with_end[0] != 0
        or offsets_with_end[-1] != data_length
        or any(
            current >= following
            for current, following in pairwise(offsets_with_end)
        )
    ):
        if action_count == 0 and offsets_with_end == [0] and data_length == 0:
            return PackedCanvasHistory()
        raise ValueError("binary canvas history contains invalid offsets")

    data = bytearray(view[data_start:])
    point_count = 0
    for index in range(action_count):
        start = offsets_with_end[index]
        end = offsets_with_end[index + 1]
        record_length = end - start
        tag = data[start]
        if tag == PATH_TAG:
            if (
                record_length < _PATH_HEADER.size + _PATH_POINT.size
                or (record_length - _PATH_HEADER.size) % _PATH_POINT.size
            ):
                raise ValueError("packed path action has invalid length")
            _, _, width = _PATH_HEADER.unpack_from(data, start)
            if not 1 <= width <= MAX_BRUSH_WIDTH:
                raise ValueError("packed path action has invalid width")
            point_count += (
                record_length - _PATH_HEADER.size
            ) // _PATH_POINT.size
            if point_count > MAX_CANVAS_POINTS:
                raise ValueError("packed canvas history contains too many points")
        elif tag == SHAPE_TAG:
            if record_length != _SHAPE_ACTION.size:
                raise ValueError("packed shape action has invalid length")
            _, shape_id, _, width, *_ = _SHAPE_ACTION.unpack_from(data, start)
            if (
                shape_id >= len(SHAPE_NAMES)
                or not 1 <= width <= MAX_BRUSH_WIDTH
            ):
                raise ValueError("packed shape action is invalid")
        elif tag == FILL_TAG:
            if record_length != _FILL_ACTION.size:
                raise ValueError("packed fill action has invalid length")
            _, _, x, y = _FILL_ACTION.unpack_from(data, start)
            if x >= CANVAS_WIDTH or y >= CANVAS_HEIGHT:
                raise ValueError("packed fill action is out of bounds")
        elif tag == CLEAR_TAG:
            if record_length != _CLEAR_ACTION.size:
                raise ValueError("packed clear action has invalid length")
        else:
            raise ValueError("packed canvas action has an invalid tag")

    return PackedCanvasHistory(
        data=data,
        offsets=array("I", offsets_with_end[:-1]),
    )


