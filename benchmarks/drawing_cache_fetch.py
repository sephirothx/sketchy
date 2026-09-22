#!/usr/bin/env python3
"""What one drawing fetch costs the event loop, cold and warm (#979).

Every fetch used to read the stored blob, decode it back to wire bytes and let
the response middleware gzip the result - all three on the loop every room
shares, for bytes that never change. The cache holds the decoded pair, so the
second fetch of a drawing pays a dictionary lookup.

The stored blob is served from memory here: the point is the CPU a fetch
spends, and a benchmark that also measured SQLite would bury it. Two figures
per column: the loop thread's own CPU, and the process's - the decode runs on
a worker thread, so only the first is what a room shares.
Both columns are read off one run: **cold** is a checksum never seen before -
what every fetch costs when the cache misses - and **warm** is the second and
later fetch of one drawing, which is what a shelf everybody opens does. Before
this change every fetch was a cold one *and* ran on the loop thread, so the
loop figure there is this run's process column.

Usage:
  backend/.venv/bin/python benchmarks/drawing_cache_fetch.py --fetches 40
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
from time import process_time, thread_time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from fastapi import FastAPI, Request  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.api.profiles import serve_drawing  # noqa: E402
from app.canvas_history import PackedCanvasHistory  # noqa: E402
from app.compression import SelectiveGZipMiddleware  # noqa: E402
from app.repositories.interfaces import TurnDrawingDetail  # noqa: E402


def drawing(strokes: int, points: int, *, seed: int = 0) -> bytes:
    """A stored drawing of a given size, in the wire form the store keeps.

    `seed` only shifts the colour, which is enough to give every drawing its
    own checksum without changing what decoding it costs.
    """
    history = PackedCanvasHistory()
    for stroke in range(strokes):
        history.append_path(
            [((step % 97) / 97, (step // 97 + stroke) / max(1, strokes)) for step in range(points)],
            color=0x223344 + seed,
            width=3,
        )
    return history.binary_payload()


def app_for(payloads: list[bytes]) -> FastAPI:
    """One route over a fixed set of drawings, addressed by index.

    Distinct drawings are how the cold path is measured more than once: every
    one of them is a miss, because a checksum is only ever seen once.
    """
    details = [
        TurnDrawingDetail(
            turn_id=f"turn-{index}",
            payload=payload,
            checksum_sha256=hashlib.sha256(payload).hexdigest(),
        )
        for index, payload in enumerate(payloads)
    ]

    app = FastAPI()
    app.add_middleware(SelectiveGZipMiddleware, minimum_size=500)

    @app.get("/drawing/{index}")
    async def route(index: int, request: Request):
        detail = details[index]

        async def checksum_of() -> str:
            return detail.checksum_sha256

        async def drawing_of() -> TurnDrawingDetail:
            return detail

        return await serve_drawing(
            request, detail.turn_id, checksum_of=checksum_of, drawing_of=drawing_of
        )

    return app


async def fetch_all(http, paths: list[str]) -> tuple[float, float]:
    """Per fetch: milliseconds of CPU on the **loop's own thread**, and of the
    whole process.

    The two differ because the decode runs on a worker thread: the loop's
    figure is what a room shares, the process's is what the machine pays. A
    benchmark that reported only the second would call a thread's work the
    loop's.
    """
    started_loop, started_all = thread_time(), process_time()
    for path in paths:
        answer = await http.get(path, headers={"Accept-Encoding": "gzip"})
        assert answer.status_code == 200, answer.status_code
    count = len(paths)
    return (
        (thread_time() - started_loop) * 1000 / count,
        (process_time() - started_all) * 1000 / count,
    )


async def measure(name: str, shape: tuple[int, int], fetches: int) -> None:
    strokes, points = shape
    cold_payloads = [drawing(strokes, points, seed=index) for index in range(fetches)]
    app = app_for(cold_payloads)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://bench") as http:
        await http.get("/drawing/0", headers={"Accept-Encoding": "gzip"})  # warm the stack
        cold_loop, cold_all = await fetch_all(
            http, [f"/drawing/{index}" for index in range(1, fetches)]
        )
        warm_loop, warm_all = await fetch_all(http, ["/drawing/0"] * fetches)
    print(
        f"{name:<28} | {len(cold_payloads[0]):>9} | {cold_loop:>7.2f} | {cold_all:>7.2f} | "
        f"{warm_loop:>7.2f} | {warm_all:>7.2f}"
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetches", type=int, default=40, help="warm fetches per drawing")
    arguments = parser.parse_args()

    print(f"{'Drawing':<28} | {'stored B':>9} | {'cold ms':>7} | {'  (all)':>7} | "
          f"{'warm ms':>7} | {'  (all)':>7}")
    print("-" * 82)
    await measure("Ordinary (6 strokes)", (6, 120), arguments.fetches)
    await measure("Stroke-heavy (60 strokes)", (60, 400), arguments.fetches)
    await measure("Very heavy (240 strokes)", (240, 600), arguments.fetches)


if __name__ == "__main__":
    asyncio.run(main())
