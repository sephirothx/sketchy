"""Would a lower HTTP compression threshold pay on long-polling? (#887)

Engine.IO compresses a polling response only past `compression_threshold`
(1024 B today), and a WebSocket has its own compression, so this is about the
transport that pays most for everything else. Replays a captured viewer
stream as polling responses - binary frames base64'd into the body, as the
transport does - and reports what the responses under the threshold would
cost and save at a lower one, with the CPU that buys it.

    backend/.venv/bin/python benchmarks/polling_compression.py \\
      fixtures/viewer_streams/gate-viewer-180s-869.jsonl
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import statistics
import time
from pathlib import Path

THRESHOLDS = (1024, 512, 256, 128)


def response_bodies(path: Path) -> list[bytes]:
    """One body per frame: the smallest a polling session ever sends.

    Engine.IO packs whatever is queued into one response, so a busy session
    sends fewer, larger bodies than this - which only makes the threshold
    matter less. Sizing it per frame is the case for lowering the threshold
    at its strongest.
    """
    bodies: list[bytes] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        frame = json.loads(line)
        text = frame.get("text")
        if text is not None:
            bodies.append(text.encode("utf-8"))
            continue
        size = frame.get("binaryBytes")
        if size:
            # The bytes themselves are not in the capture; base64 of that many
            # is what the body would carry, and its size is what matters here.
            bodies.append(b"b" + base64.b64encode(b"\0" * size))
    return bodies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("capture", type=Path)
    parser.add_argument("--seconds", type=float, default=180.0, help="the capture's length")
    args = parser.parse_args()

    bodies = response_bodies(args.capture)
    if not bodies:
        raise SystemExit(f"no frames in {args.capture}")
    sizes = [len(body) for body in bodies]
    report: dict = {
        "responses": len(bodies),
        "bytes_total": sum(sizes),
        "size_median": int(statistics.median(sizes)),
        "size_p95": sorted(sizes)[int(len(sizes) * 0.95) - 1],
        "thresholds": {},
    }
    for threshold in THRESHOLDS:
        compressible = [body for body in bodies if len(body) >= threshold]
        started = time.perf_counter()
        compressed = [gzip.compress(body, 6) for body in compressible]
        elapsed = time.perf_counter() - started
        before = sum(len(body) for body in compressible)
        after = sum(len(body) for body in compressed)
        grew = sum(1 for body, small in zip(compressible, compressed, strict=True) if len(small) >= len(body))
        report["thresholds"][threshold] = {
            "responses_compressed": len(compressible),
            "share_of_responses": round(len(compressible) / len(bodies), 3),
            "bytes_before": before,
            "bytes_after": after,
            "saved_bytes": before - after,
            "saved_per_second": round((before - after) / args.seconds, 1),
            "responses_that_grew": grew,
            "cpu_ms_per_1000": round(elapsed / max(1, len(compressible)) * 1_000_000, 2),
        }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
