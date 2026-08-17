"""Compact, versioned drawing-history models and wire encoding."""
from __future__ import annotations

import base64
import math
import os
import struct
import zlib
from array import array
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from dataclasses import field
from typing import TypeAlias

CANVAS_HISTORY_VERSION = 2
BINARY_HISTORY_MAGIC = b"SKCH"
CANVAS_WIDTH = 800
CANVAS_HEIGHT = 600
MAX_BRUSH_WIDTH = 64
MAX_NORMALIZED_COORDINATE_MAGNITUDE = 8
COORDINATE_SCALE = 4
MIN_PACKED_COORDINATE = -(2**15)
MAX_PACKED_COORDINATE = 2**15 - 1
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


# Replay-work costs are calibrated to Phase 4 Chromium 149 timings *after*
# PR #256's scanline fill. One live fill got ~79% faster; authoritative replay
# of N fills is still N full-canvas getImageData/flood/putImageData passes
# (~6.5 ms desktop / ~26 ms at 4× CPU per fill). 50 worst-case fills ≈ 1.3 s
# on 4× mobile, which is the live window budget—not a lifetime cap.
PATH_WORK = 1
SHAPE_WORK = 1
FILL_WORK = 200
CLEAR_WORK = 0
CHECKPOINT_WORK = 0
MAX_WINDOW_WORK = _env_int("SKETCHY_MAX_WINDOW_WORK", 10_000)
MAX_WINDOW_ACTIONS = _env_int("SKETCHY_MAX_WINDOW_ACTIONS", 256)
MAX_CANVAS_POINTS = 25_000
MAX_SYNC_BYTES = 524_288
MAX_CHECKPOINT_PNG = 400_000
# Decoder/session still use this name for the maximum packed record count
# (optional checkpoint + semantic window).
MAX_CANVAS_ACTIONS = MAX_WINDOW_ACTIONS + 1

PATH_TAG = 0
SHAPE_TAG = 1
FILL_TAG = 2
CLEAR_TAG = 3
CHECKPOINT_TAG = 4

SHAPE_IDS = {"rectangle": 0, "ellipse": 1, "triangle": 2}
SHAPE_NAMES = tuple(SHAPE_IDS)

_PATH_HEADER = struct.Struct("<B3sB")
_PATH_POINT = struct.Struct("<hh")
_SHAPE_ACTION = struct.Struct("<BB3sBhhhh")
_FILL_ACTION = struct.Struct("<B3sHH")
_CLEAR_ACTION = struct.Struct("<B")
_CHECKPOINT_HEADER = struct.Struct("<BI")
_BINARY_HEADER = struct.Struct("<4sBH")
_BINARY_OFFSET = struct.Struct("<I")
_HASH_RECORD_LENGTH = struct.Struct("<I")

# Largest window *without* a PNG: every action slot is a shape except one
# fat path that holds every point. Checkpoint PNGs are bounded separately.
MAX_WINDOW_BINARY_BYTES = (
    _BINARY_HEADER.size
    + (MAX_WINDOW_ACTIONS + 1) * _BINARY_OFFSET.size
    + MAX_WINDOW_ACTIONS * _SHAPE_ACTION.size
    + MAX_CANVAS_POINTS * _PATH_POINT.size
    + _PATH_HEADER.size
    - _SHAPE_ACTION.size
)
MAX_BINARY_CANVAS_HISTORY_BYTES = MAX_WINDOW_BINARY_BYTES + MAX_CHECKPOINT_PNG

HISTORY_HASH_INITIAL = 0


def action_replay_work(tag: int) -> int:
    if tag == PATH_TAG:
        return PATH_WORK
    if tag == SHAPE_TAG:
        return SHAPE_WORK
    if tag == FILL_TAG:
        return FILL_WORK
    if tag == CLEAR_TAG:
        return CLEAR_WORK
    if tag == CHECKPOINT_TAG:
        return CHECKPOINT_WORK
    raise ValueError("unknown canvas action tag")


def validate_checkpoint_png(png: bytes | bytearray | memoryview) -> bytes:
    raw = bytes(png)
    if len(raw) > MAX_CHECKPOINT_PNG:
        raise ValueError("checkpoint PNG is too large")
    if not raw.startswith(PNG_SIGNATURE):
        raise ValueError("checkpoint is not a PNG")
    return raw


def _checkpoint_record(png: bytes) -> bytes:
    return _CHECKPOINT_HEADER.pack(CHECKPOINT_TAG, len(png)) + png


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


@dataclass(slots=True)
class CheckpointAction:
    png: bytes


CanvasAction: TypeAlias = PathAction | ShapeAction | FillAction | ClearAction | CheckpointAction


@dataclass(frozen=True, slots=True)
class PoppedCanvasAction:
    tag: int
    point_count: int = 0
    work_units: int = 0


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
        if tag == CHECKPOINT_TAG:
            _, length = _CHECKPOINT_HEADER.unpack_from(self.data, start)
            return CheckpointAction(png=bytes(self.data[start + _CHECKPOINT_HEADER.size:start + _CHECKPOINT_HEADER.size + length]))
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

    def append_checkpoint(self, png: bytes) -> None:
        record = _checkpoint_record(validate_checkpoint_png(png))
        self.offsets.append(len(self.data))
        self.data.extend(record)

    def has_checkpoint(self) -> bool:
        return bool(self) and self.data[self.offsets[0]] == CHECKPOINT_TAG

    def semantic_start(self) -> int:
        return 1 if self.has_checkpoint() else 0

    def semantic_count(self) -> int:
        return len(self) - self.semantic_start()

    def last_is_clear(self) -> bool:
        return bool(self) and self.data[self.offsets[-1]] == CLEAR_TAG

    def last_is_checkpoint(self) -> bool:
        return bool(self) and self.data[self.offsets[-1]] == CHECKPOINT_TAG

    def tag_at(self, index: int) -> int:
        if index < 0:
            index += len(self)
        return self.data[self.offsets[index]]

    def point_count(self) -> int:
        total = 0
        for index, start in enumerate(self.offsets):
            if self.data[start] != PATH_TAG:
                continue
            end = self.offsets[index + 1] if index + 1 < len(self) else len(self.data)
            total += (end - start - _PATH_HEADER.size) // _PATH_POINT.size
        return total

    def replay_work(self) -> int:
        return sum(action_replay_work(self.data[start]) for start in self.offsets)

    def compact_prefix(self, png: bytes, folded_count: int) -> None:
        """Replace checkpoint (if any) plus the next folded_count semantic actions."""
        start = self.semantic_start()
        if folded_count < 1 or start + folded_count > len(self):
            raise ValueError("checkpoint fold count is invalid")
        keep_from = start + folded_count
        record = _checkpoint_record(validate_checkpoint_png(png))
        remaining = bytearray()
        remaining_offsets: array = array("I")
        if keep_from < len(self):
            remaining_start = self.offsets[keep_from]
            remaining.extend(self.data[remaining_start:])
            for offset in self.offsets[keep_from:]:
                remaining_offsets.append(len(record) + (offset - remaining_start))
        self.data = bytearray(record) + remaining
        self.offsets = array("I", [0])
        self.offsets.extend(remaining_offsets)

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
            elif tag == CHECKPOINT_TAG:
                _, length = _CHECKPOINT_HEADER.unpack_from(self.data, start)
                png = bytes(
                    self.data[start + _CHECKPOINT_HEADER.size:start + _CHECKPOINT_HEADER.size + length]
                )
                actions.append([CHECKPOINT_TAG, base64.b64encode(png).decode("ascii")])
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
        for offset in self.offsets:
            payload.extend(_BINARY_OFFSET.pack(offset))
        payload.extend(_BINARY_OFFSET.pack(len(self.data)))
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
        return PoppedCanvasAction(
            tag=tag,
            point_count=point_count,
            work_units=action_replay_work(tag),
        )


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
    if isinstance(action, CheckpointAction):
        return [CHECKPOINT_TAG, base64.b64encode(action.png).decode("ascii")]
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
    if len(view) > MAX_SYNC_BYTES:
        raise ValueError("binary canvas history exceeds the sync budget")

    data_start = (
        _BINARY_HEADER.size
        + (action_count + 1) * _BINARY_OFFSET.size
    )
    if data_start > len(view):
        raise ValueError("binary canvas history offset table is truncated")
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
    replay_work = 0
    seen_checkpoint = False
    semantic_count = 0
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
            semantic_count += 1
        elif tag == SHAPE_TAG:
            if record_length != _SHAPE_ACTION.size:
                raise ValueError("packed shape action has invalid length")
            _, shape_id, _, width, *_ = _SHAPE_ACTION.unpack_from(data, start)
            if (
                shape_id >= len(SHAPE_NAMES)
                or not 1 <= width <= MAX_BRUSH_WIDTH
            ):
                raise ValueError("packed shape action is invalid")
            semantic_count += 1
        elif tag == FILL_TAG:
            if record_length != _FILL_ACTION.size:
                raise ValueError("packed fill action has invalid length")
            _, _, x, y = _FILL_ACTION.unpack_from(data, start)
            if x >= CANVAS_WIDTH or y >= CANVAS_HEIGHT:
                raise ValueError("packed fill action is out of bounds")
            semantic_count += 1
        elif tag == CLEAR_TAG:
            if record_length != _CLEAR_ACTION.size:
                raise ValueError("packed clear action has invalid length")
            semantic_count += 1
        elif tag == CHECKPOINT_TAG:
            if index != 0 or seen_checkpoint:
                raise ValueError("packed checkpoint must be the first history record")
            if record_length < _CHECKPOINT_HEADER.size:
                raise ValueError("packed checkpoint has invalid length")
            _, length = _CHECKPOINT_HEADER.unpack_from(data, start)
            if length != record_length - _CHECKPOINT_HEADER.size:
                raise ValueError("packed checkpoint length is invalid")
            validate_checkpoint_png(
                data[start + _CHECKPOINT_HEADER.size:start + record_length]
            )
            seen_checkpoint = True
        else:
            raise ValueError("packed canvas action has an invalid tag")
        replay_work += action_replay_work(tag)
        if semantic_count > MAX_WINDOW_ACTIONS:
            raise ValueError("binary canvas history contains too many actions")
        if replay_work > MAX_WINDOW_WORK:
            raise ValueError("binary canvas history exceeds the replay-work budget")

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
    tag = _integer(encoded[0], low=PATH_TAG, high=CHECKPOINT_TAG)
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
    if tag == CHECKPOINT_TAG:
        if len(encoded) != 2 or not isinstance(encoded[1], str):
            raise ValueError("checkpoint action has invalid length")
        try:
            png = base64.b64decode(encoded[1], validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError("checkpoint action is not valid base64") from error
        return CheckpointAction(png=validate_checkpoint_png(png))
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
    semantic = [action for action in actions if not isinstance(action, CheckpointAction)]
    if any(isinstance(action, CheckpointAction) for action in actions[1:]):
        raise ValueError("checkpoint must be the first history record")
    if len(semantic) > MAX_WINDOW_ACTIONS:
        raise ValueError("canvas history contains too many actions")
    if (
        sum(len(action.points) for action in semantic if isinstance(action, PathAction))
        > MAX_CANVAS_POINTS
    ):
        raise ValueError("canvas history contains too many path points")
    work = 0
    for action in actions:
        if isinstance(action, PathAction):
            work += PATH_WORK
        elif isinstance(action, ShapeAction):
            work += SHAPE_WORK
        elif isinstance(action, FillAction):
            work += FILL_WORK
        elif isinstance(action, ClearAction):
            work += CLEAR_WORK
    if work > MAX_WINDOW_WORK:
        raise ValueError("canvas history exceeds the replay-work budget")
    return actions


def needed_fold_count(
    history: PackedCanvasHistory,
    *,
    extra_work: int,
    extra_points: int,
    extra_actions: int,
    foldable_count: int | None = None,
) -> int | None:
    """Return the smallest semantic prefix to fold, or None if extra already fits.

    Returns -1 when even folding every foldable action cannot make room.
    """
    start = history.semantic_start()
    semantic = history.semantic_count()
    if foldable_count is None:
        foldable_count = semantic
    foldable_count = min(foldable_count, semantic)
    work = history.replay_work()
    points = history.point_count()
    if (
        work + extra_work <= MAX_WINDOW_WORK
        and semantic + extra_actions <= MAX_WINDOW_ACTIONS
        and points + extra_points <= MAX_CANVAS_POINTS
    ):
        return None
    folded_work = 0
    folded_points = 0
    for folded in range(1, foldable_count + 1):
        index = start + folded - 1
        tag = history.tag_at(index)
        folded_work += action_replay_work(tag)
        if tag == PATH_TAG:
            start_offset = history.offsets[index]
            end_offset = (
                history.offsets[index + 1]
                if index + 1 < len(history)
                else len(history.data)
            )
            folded_points += (
                end_offset - start_offset - _PATH_HEADER.size
            ) // _PATH_POINT.size
        remaining_semantic = semantic - folded
        if (
            work - folded_work + extra_work <= MAX_WINDOW_WORK
            and remaining_semantic + extra_actions <= MAX_WINDOW_ACTIONS
            and points - folded_points + extra_points <= MAX_CANVAS_POINTS
        ):
            return folded
    return -1
