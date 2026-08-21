"""Compact, versioned drawing-history models and wire encoding."""
from __future__ import annotations

import math
import struct
import sys
import zlib
from array import array
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from dataclasses import field
from typing import TypeAlias

CANVAS_HISTORY_VERSION = 1
BINARY_HISTORY_MAGIC = b"SKCH"
CANVAS_WIDTH = 800
CANVAS_HEIGHT = 600
MAX_BRUSH_WIDTH = 64
MAX_NORMALIZED_COORDINATE_MAGNITUDE = 8
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

    def wire_actions(self) -> list[list]:
        """Decode packed records directly into the compact JSON wire schema."""
        actions = []
        for index, start in enumerate(self.offsets):
            end = (
                self.offsets[index + 1]
                if index + 1 < len(self)
                else len(self.data)
            )
            tag = self.data[start]
            if tag == PATH_TAG:
                _, color, width = _PATH_HEADER.unpack_from(self.data, start)
                encoded = [PATH_TAG, _unpacked_color(color), width]
                for offset in range(
                    start + _PATH_HEADER.size,
                    end,
                    _PATH_POINT.size,
                ):
                    x, y = _PATH_POINT.unpack_from(self.data, offset)
                    encoded.extend(
                        (
                            _unpack_coordinate(x, CANVAS_WIDTH),
                            _unpack_coordinate(y, CANVAS_HEIGHT),
                        )
                    )
                actions.append(encoded)
            elif tag == SHAPE_TAG:
                _, shape_id, color, width, start_x, start_y, end_x, end_y = (
                    _SHAPE_ACTION.unpack_from(self.data, start)
                )
                actions.append(
                    [
                        SHAPE_TAG,
                        shape_id,
                        _unpacked_color(color),
                        width,
                        _unpack_coordinate(start_x, CANVAS_WIDTH),
                        _unpack_coordinate(start_y, CANVAS_HEIGHT),
                        _unpack_coordinate(end_x, CANVAS_WIDTH),
                        _unpack_coordinate(end_y, CANVAS_HEIGHT),
                    ]
                )
            elif tag == FILL_TAG:
                _, color, x, y = _FILL_ACTION.unpack_from(self.data, start)
                actions.append([FILL_TAG, _unpacked_color(color), x, y])
            else:
                actions.append([CLEAR_TAG])
        return actions

    def wire_payload(self) -> dict:
        return {
            "v": CANVAS_HISTORY_VERSION,
            "a": self.wire_actions(),
        }

    def binary_payload(self) -> bytes:
        """Return one versioned, self-delimiting binary synchronization frame."""
        payload = bytearray(
            _BINARY_HEADER.pack(
                BINARY_HISTORY_MAGIC,
                CANVAS_HISTORY_VERSION,
                len(self),
            )
        )
        table = self.offsets[:]
        table.append(len(self.data))
        if _OFFSETS_ARE_WIRE_LAYOUT:
            payload.extend(table.tobytes())
        else:
            for offset in table:
                payload.extend(_BINARY_OFFSET.pack(offset))
        payload.extend(self.data)
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

def encode_canvas_action(action: CanvasAction) -> list:
    if isinstance(action, PathAction):
        encoded = [PATH_TAG, action.color, action.width]
        for x, y in action.points:
            encoded.extend((x, y))
        return encoded
    if isinstance(action, ShapeAction):
        return [
            SHAPE_TAG,
            SHAPE_IDS[action.shape],
            action.color,
            action.width,
            action.start[0],
            action.start[1],
            action.end[0],
            action.end[1],
        ]
    if isinstance(action, FillAction):
        return [FILL_TAG, action.color, action.x, action.y]
    return [CLEAR_TAG]


def encode_canvas_history(actions: Sequence[CanvasAction]) -> dict:
    if isinstance(actions, PackedCanvasHistory):
        return actions.wire_payload()
    return {
        "v": CANVAS_HISTORY_VERSION,
        "a": [encode_canvas_action(action) for action in actions],
    }


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
            for current, following in zip(
                offsets_with_end,
                offsets_with_end[1:],
            )
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


def _number(value, *, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("canvas action contains a non-number")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError("canvas action number is out of bounds")
    return number


def _integer(value, *, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError("canvas action contains an invalid integer")
    return value


def _color(value) -> int:
    return _integer(value, low=0, high=0xFFFFFF)


def _coordinate(value) -> float:
    return _number(
        value,
        low=-MAX_NORMALIZED_COORDINATE_MAGNITUDE,
        high=MAX_NORMALIZED_COORDINATE_MAGNITUDE,
    )


def _width(value) -> int:
    return _integer(value, low=1, high=MAX_BRUSH_WIDTH)


def decode_canvas_action(encoded) -> CanvasAction:
    if not isinstance(encoded, list) or not encoded:
        raise ValueError("canvas action must be a non-empty list")
    tag = _integer(encoded[0], low=PATH_TAG, high=CLEAR_TAG)
    if tag == PATH_TAG:
        if len(encoded) < 5 or (len(encoded) - 3) % 2:
            raise ValueError("path action has invalid length")
        if (len(encoded) - 3) // 2 > MAX_CANVAS_POINTS:
            raise ValueError("path action contains too many points")
        points = [
            (_coordinate(encoded[index]), _coordinate(encoded[index + 1]))
            for index in range(3, len(encoded), 2)
        ]
        return PathAction(points=points, color=_color(encoded[1]), width=_width(encoded[2]))
    if tag == SHAPE_TAG:
        if len(encoded) != 8:
            raise ValueError("shape action has invalid length")
        shape_id = _integer(encoded[1], low=0, high=len(SHAPE_NAMES) - 1)
        return ShapeAction(
            shape=SHAPE_NAMES[shape_id],
            color=_color(encoded[2]),
            width=_width(encoded[3]),
            start=(_coordinate(encoded[4]), _coordinate(encoded[5])),
            end=(_coordinate(encoded[6]), _coordinate(encoded[7])),
        )
    if tag == FILL_TAG:
        if len(encoded) != 4:
            raise ValueError("fill action has invalid length")
        return FillAction(
            color=_color(encoded[1]),
            x=_integer(encoded[2], low=0, high=CANVAS_WIDTH - 1),
            y=_integer(encoded[3], low=0, high=CANVAS_HEIGHT - 1),
        )
    if len(encoded) != 1:
        raise ValueError("clear action has invalid length")
    return ClearAction()


def decode_canvas_history(payload) -> list[CanvasAction]:
    if (
        not isinstance(payload, dict)
        or set(payload) != {"v", "a"}
        or payload["v"] != CANVAS_HISTORY_VERSION
        or not isinstance(payload["a"], list)
    ):
        raise ValueError("invalid canvas history envelope")
    if len(payload["a"]) > MAX_CANVAS_ACTIONS:
        raise ValueError("canvas history contains too many actions")
    actions = [decode_canvas_action(action) for action in payload["a"]]
    if (
        sum(len(action.points) for action in actions if isinstance(action, PathAction))
        > MAX_CANVAS_POINTS
    ):
        raise ValueError("canvas history contains too many path points")
    return actions
