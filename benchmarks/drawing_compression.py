"""What a storage-only compressed drawing format would save (#547).

Encodes the checked-in golden frames and the benchmark's reproducible
histories three ways - the SKCH wire bytes as stored today, plain zlib over
them, and coordinate-delta recoding of path points followed by zlib - and
reports bytes, ratio and encode/decode time per frame. Measurement only: no
format is introduced, and every decoder that exists stays (R-HIST-18).

    backend/.venv/bin/python benchmarks/drawing_compression.py
"""
from __future__ import annotations

import json
import statistics
import struct
import sys
import zlib
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "benchmarks"))

import canvas_history as bench
from app.canvas_history import (
    _BINARY_HEADER,
    _BINARY_OFFSET,
    _PATH_HEADER,
    _PATH_POINT,
    PATH_TAG,
    decode_binary_canvas_history,
)


def _frames() -> dict[str, bytes]:
    frames: dict[str, bytes] = {}
    fixtures = json.loads((ROOT / "fixtures" / "canvas_protocol_v1.json").read_text())
    for entry in fixtures["histories"]:
        frames[f"golden:{entry['name']}"] = bytes.fromhex(entry["binary"])
    for name, builder in (
        ("path_heavy", bench.path_heavy_history),
        ("shape_heavy", bench.shape_heavy_history),
        ("fill_heavy", bench.fill_heavy_history),
        ("mixed", bench.mixed_history),
        ("realistic", bench.realistic_history),
        ("theoretical_max", bench.theoretical_max_history),
    ):
        frames[name] = builder().binary_payload()
    return frames


def _delta_recode(frame: bytes) -> bytes:
    """Rewrite each path's points as deltas from the previous point, so the
    small numbers a stroke is made of compress; everything else verbatim."""
    magic, version, action_count = _BINARY_HEADER.unpack_from(frame)
    offsets = [
        _BINARY_OFFSET.unpack_from(frame, _BINARY_HEADER.size + i * _BINARY_OFFSET.size)[0]
        for i in range(action_count + 1)
    ]
    data_start = _BINARY_HEADER.size + (action_count + 1) * _BINARY_OFFSET.size
    out = bytearray(frame[:data_start])
    for i in range(action_count):
        record = frame[data_start + offsets[i] : data_start + offsets[i + 1]]
        if record and record[0] == PATH_TAG and len(record) >= _PATH_HEADER.size:
            header = record[: _PATH_HEADER.size]
            points = record[_PATH_HEADER.size:]
            prev = (0, 0)
            recoded = bytearray(header)
            for offset in range(0, len(points), _PATH_POINT.size):
                x, y = _PATH_POINT.unpack_from(points, offset)
                recoded += struct.pack("<hh", x - prev[0], y - prev[1])
                prev = (x, y)
            out += recoded
        else:
            out += record
    return bytes(out)


def _timed(function, *args, repeat: int = 20) -> tuple[bytes, float]:
    samples = []
    result = None
    for _ in range(repeat):
        started = perf_counter()
        result = function(*args)
        samples.append((perf_counter() - started) * 1000)
    return result, statistics.median(samples)


def main() -> None:
    rows = []
    for name, frame in _frames().items():
        decode_binary_canvas_history(frame)
        plain, plain_ms = _timed(zlib.compress, frame, 6)
        _, inflate_ms = _timed(zlib.decompress, plain)
        delta, delta_ms = _timed(lambda f: zlib.compress(_delta_recode(f), 6), frame)
        rows.append(
            {
                "frame": name,
                "raw_bytes": len(frame),
                "zlib_bytes": len(plain),
                "zlib_ratio": round(len(frame) / max(1, len(plain)), 2),
                "delta_zlib_bytes": len(delta),
                "delta_zlib_ratio": round(len(frame) / max(1, len(delta)), 2),
                "zlib_encode_ms": round(plain_ms, 3),
                "zlib_decode_ms": round(inflate_ms, 3),
                "delta_zlib_encode_ms": round(delta_ms, 3),
            }
        )
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
