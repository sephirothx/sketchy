"""What the stored drawing format saves, frame by frame (#547).

Encodes the checked-in golden frames and the benchmark's reproducible
histories three ways - the SKCH wire bytes as they were stored before #547,
plain zlib over them, and the SKCD encoding `app.canvas_storage` writes now
(path points recoded as deltas, then deflate) - and reports bytes, ratio and
p95 encode/decode time per frame. PostgreSQL's physical effect is a separate
measurement: `drawing_store_footprint.py`.

    backend/.venv/bin/python benchmarks/drawing_compression.py
"""
from __future__ import annotations

import json
import sys
import zlib
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "benchmarks"))

import canvas_history as bench
from app.canvas_history import decode_binary_canvas_history
from app.canvas_storage import prepare_stored_drawing, stored_drawing_wire_payload


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


def _p95(function, *args, repeat: int = 20) -> tuple[bytes, float]:
    samples = []
    result = None
    for _ in range(repeat):
        started = perf_counter()
        result = function(*args)
        samples.append((perf_counter() - started) * 1000)
    return result, sorted(samples)[max(0, int(len(samples) * 0.95) - 1)]


def main() -> None:
    rows = []
    for name, frame in _frames().items():
        decode_binary_canvas_history(frame)
        plain, plain_ms = _p95(zlib.compress, frame, 6)
        stored, encode_ms = _p95(lambda f: prepare_stored_drawing(f)[0], frame)
        wire, decode_ms = _p95(stored_drawing_wire_payload, stored)
        assert wire == frame
        rows.append(
            {
                "frame": name,
                "raw_bytes": len(frame),
                "zlib_bytes": len(plain),
                "zlib_ratio": round(len(frame) / max(1, len(plain)), 2),
                "stored_format": stored[:4].decode(),
                "stored_bytes": len(stored),
                "stored_ratio": round(len(frame) / max(1, len(stored)), 2),
                "zlib_encode_p95_ms": round(plain_ms, 3),
                "stored_encode_p95_ms": round(encode_ms, 3),
                "stored_decode_p95_ms": round(decode_ms, 3),
            }
        )
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
