#!/usr/bin/env python3
"""Which permessage-deflate window the server should compress with.

The window is the compressor's memory of what it already sent on that
connection. Bigger means more back-references - a `room_state` that resembles
the last one costs tens of bytes instead of kilobytes - and more zlib state
held per connection for the life of the socket. Smaller is the reverse. The
choice is a trade between bytes on the wire and memory (and a little CPU) on
the server at full occupancy, so this measures both on one plausible viewer
session rather than on a payload in isolation.

The session, per viewer connection, in order: join a 16-seat room (a
`room_state`), late-join the drawing (`sync_strokes` of a realistic history),
then a turn of recorded drawing (`fixtures/live_strokes/`) with the room's
other events between strokes - room churn (votes, AFK, scores, a join) as
`room_state` broadcasts, chat lines, correct guesses - a turn end, and a
second turn from another trace. Compressed exactly as wsproto does it: zlib
level 6, memLevel 8, the four-byte sync-flush suffix removed, one context per
connection with takeover.

Memory is measured, not only computed: 400 compressors (the #461 seat count)
are created per window and the process's resident size read before and
after, next to zlib's own formula. CPU is the wall time to deflate the whole
session, which at 25 draw frames a second per drawer is the cost that scales.

Usage:
  backend/.venv/bin/python benchmarks/deflate_windows.py
  backend/.venv/bin/python benchmarks/deflate_windows.py --seats 400 --json-output out.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import resource
import sys
import time
import zlib
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "benchmarks"))

from canvas_history import realistic_history  # noqa: E402
from live_drawing import (  # noqa: E402
    SYNC_FLUSH_SUFFIX,
    event_messages,
    load_trace,
    rebroadcast_messages,
    session_frames,
)
from room_payloads import build_room, room_event_sequence  # noqa: E402

TRACES = Path(ROOT_DIR) / "fixtures" / "live_strokes"
DEFLATE_LEVEL = zlib.Z_DEFAULT_COMPRESSION  # what wsproto passes
MEM_LEVEL = 8  # zlib's default, which wsproto leaves alone
# (window bits, memLevel) pairs worth knowing about. memLevel sizes the hash
# table zlib matches with: 1 << (memLevel + 9) bytes, so 128 KB at 8 and
# 16 KB at 5 - which is most of a context's memory once the window is small.
CANDIDATES = ((12, 8), (13, 8), (14, 8), (15, 8), (15, 6), (15, 5), (13, 5), (12, 5))


def zlib_state_bytes(window_bits: int, mem_level: int = MEM_LEVEL) -> int:
    """zlib's own formula for one deflate context plus one inflate context."""
    deflate = (1 << (window_bits + 2)) + (1 << (mem_level + 9))
    inflate = (1 << window_bits) + 7 * 1024
    return deflate + inflate


def rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return usage if sys.platform == "darwin" else usage * 1024


def measured_state_bytes(window_bits: int, count: int, mem_level: int = MEM_LEVEL) -> int:
    """Resident growth from `count` live compressors, per compressor.

    ru_maxrss is a high-water mark, so the windows are measured in a child
    process each, smallest last, to keep one measurement from hiding the next.
    """
    import subprocess

    code = f"""
import resource, sys, zlib
def rss():
    u = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return u if sys.platform == "darwin" else u * 1024
seed = bytes(range(256)) * 16
before = rss()
keep = []
for _ in range({count}):
    c = zlib.compressobj({DEFLATE_LEVEL}, zlib.DEFLATED, -{window_bits}, {mem_level})
    c.compress(seed); c.flush(zlib.Z_SYNC_FLUSH)
    d = zlib.decompressobj(-{window_bits})
    keep.append((c, d))
print((rss() - before) // {count})
"""
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return int(out.stdout.strip())


# --- the session ------------------------------------------------------------

def json_event(event: str, payload) -> list[bytes]:
    return event_messages(event, payload)


def chat_line(rng: random.Random, index: int) -> list[bytes]:
    words = ["is it a", "snail", "no wait", "a boat?", "house", "cat", "definitely a dog", "lol", "hurry"]
    return json_event(
        "chat_message",
        {
            "id": f"m{rng.getrandbits(40)}",
            "playerId": f"p{index % 15}",
            "nickname": f"Player_{index % 15}",
            "nameColor": "#7c4dff",
            "text": rng.choice(words),
            "kind": "chat",
            "createdAt": 1_757_000_000_000 + index * 1_300,
        },
    )


def build_session(seed: int, *, long_names: bool) -> dict[str, list[bytes]]:
    """Messages in order, each tagged by kind, for one viewer's connection."""
    rng = random.Random(seed)
    manager, room = build_room(16)
    if long_names:
        for index, seat in enumerate(room.player_list()):
            seat.nickname = f"Playername_{index:02d}"[:16]
    churn = room_event_sequence(manager, room, rounds=12)
    history = realistic_history()
    sync = event_messages(
        "sync_strokes", history.binary_payload(), len(history), 1, len(history), rng.getrandbits(32)
    )
    traces = {p.stem: session_frames(load_trace(p)) for p in sorted(TRACES.glob("*.json"))}
    first = traces.get("hand-long") or next(iter(traces.values()))
    second = traces.get("hand-short") or first

    tagged: list[tuple[str, bytes]] = []

    def add(kind: str, messages: list[bytes]) -> None:
        tagged.extend((kind, m) for m in messages)

    add("room_state", json_event("room_state", churn[0]))
    add("sync_strokes", sync)
    add("turn", json_event("turn_started", {"turnId": "01a0", "drawerId": "p0", "maskedPrompt": "_ _ _ _ _", "roundNumber": 1, "totalRounds": 3, "seconds": 80, "hintCost": 20, "letterPrices": [30, 60, 90], "hintSpend": 0, "maxHintSpend": 120}))

    def turn(frames: list[dict], churn_states: list[dict], chat_from: int) -> None:
        draw = rebroadcast_messages(frames, random.Random(seed))
        # Re-associate messages to frames: one message per frame here since
        # recorded frames are all base64 or int (checked by the fixture test).
        stroke = 0
        chat = chat_from
        churn_index = 0
        for frame, message in zip(frames, draw):
            add("draw", [message])
            if frame["event"] in {"draw_end", "draw_fill", "draw_shape", "clear_canvas"}:
                stroke += 1
                if stroke % 2 == 0:
                    add("chat", chat_line(rng, chat)); chat += 1
                if stroke % 4 == 0 and churn_index < len(churn_states):
                    add("room_state", json_event("room_state", churn_states[churn_index])); churn_index += 1
                if stroke % 9 == 0:
                    add("guess", json_event("correct_guess", {"playerId": f"p{stroke}", "nickname": f"Player_{stroke}", "points": 140}))

    turn(first, churn[1:7], 0)
    add("turn", json_event("turn_ended", {"prompt": "snail", "drawerId": "p0", "scores": [{"playerId": f"p{i}", "points": i * 37} for i in range(16)], "reason": "time"}))
    add("turn", json_event("turn_started", {"turnId": "01a1", "drawerId": "p1", "maskedPrompt": "_ _ _ _", "roundNumber": 1, "totalRounds": 3, "seconds": 80, "hintCost": 20, "letterPrices": [30, 60, 90], "hintSpend": 0, "maxHintSpend": 120}))
    turn(second, churn[7:], 40)
    add("turn", json_event("turn_ended", {"prompt": "boat", "drawerId": "p1", "scores": [{"playerId": f"p{i}", "points": i * 41} for i in range(16)], "reason": "all_guessed"}))
    by_kind: dict[str, list[bytes]] = {}
    for kind, message in tagged:
        by_kind.setdefault(kind, []).append(message)
    by_kind["__order__"] = [m for _, m in tagged]
    by_kind["__kinds__"] = [k.encode() for k, _ in tagged]
    return by_kind


def deflate_session(messages: list[bytes], kinds: list[bytes], window_bits: int, *, takeover: bool = True, mem_level: int = MEM_LEVEL) -> dict:
    compressor = zlib.compressobj(DEFLATE_LEVEL, zlib.DEFLATED, -window_bits, mem_level)
    per_kind: dict[str, int] = {}
    total = 0
    started = time.perf_counter()
    for kind, message in zip(kinds, messages):
        if not takeover:
            compressor = zlib.compressobj(DEFLATE_LEVEL, zlib.DEFLATED, -window_bits, mem_level)
        out = compressor.compress(message) + compressor.flush(zlib.Z_SYNC_FLUSH)
        size = len(out) - len(SYNC_FLUSH_SUFFIX)
        total += size
        per_kind[kind.decode()] = per_kind.get(kind.decode(), 0) + size
    elapsed = time.perf_counter() - started
    return {"bytes": total, "by_kind": per_kind, "cpu_ms": elapsed * 1000}


def measure(*, seats: int, seed: int, long_names: bool) -> dict:
    session = build_session(seed, long_names=long_names)
    messages, kinds = session["__order__"], session["__kinds__"]
    raw_by_kind = {k: sum(len(m) for m in v) for k, v in session.items() if not k.startswith("__")}
    raw_total = sum(len(m) for m in messages)
    rows = {}
    for bits, mem_level in CANDIDATES:
        best = min((deflate_session(messages, kinds, bits, mem_level=mem_level) for _ in range(5)), key=lambda r: r["cpu_ms"])
        rows[f"takeover_{bits}_{mem_level}"] = {
            "label": f"{bits}-bit window ({1 << bits >> 10} KB), memLevel {mem_level}",
            "window_bits": bits,
            "mem_level": mem_level,
            **best,
            "state_bytes_formula": zlib_state_bytes(bits, mem_level),
            "state_bytes_measured": measured_state_bytes(bits, seats, mem_level),
        }
    cold = deflate_session(messages, kinds, 15, takeover=False)
    rows["no_takeover"] = {"label": "15-bit, no context takeover", "window_bits": 15, **cold,
                           "state_bytes_formula": 0, "state_bytes_measured": 0}
    rows["none"] = {"label": "no compression", "window_bits": 0, "bytes": raw_total, "by_kind": raw_by_kind,
                    "cpu_ms": 0.0, "state_bytes_formula": 0, "state_bytes_measured": 0}
    return {"seats": seats, "long_names": long_names, "messages": len(messages), "raw_bytes": raw_total,
            "raw_by_kind": raw_by_kind, "rows": rows}


def print_report(result: dict) -> None:
    seats = result["seats"]
    kinds = ["room_state", "sync_strokes", "draw", "chat", "guess", "turn"]
    print(f"One viewer's session: {result['messages']} messages, {result['raw_bytes']:,} B uncompressed"
          f"{' (16-character nicknames)' if result['long_names'] else ''}")
    print(f"{'':<42} {'total':>9} " + " ".join(f"{k:>12}" for k in kinds) + f" {'cpu':>7} {'state/conn':>10} {'at ' + str(seats) + ' seats':>12}")
    print("-" * 140)
    for row in result["rows"].values():
        by = row["by_kind"]
        state = row["state_bytes_measured"] or row["state_bytes_formula"]
        print(f"{row['label']:<42} {row['bytes']:>7,} B " + " ".join(f"{by.get(k, 0):>10,} B" for k in kinds)
              + f" {row['cpu_ms']:>5.1f}ms {state / 1024:>7.0f} KB {state * seats / 1_048_576:>9.1f} MB")
    print()
    print("  'state/conn' is resident memory per connection measured from live zlib contexts")
    print("  (one deflate + one inflate); 'cpu' is wall time to deflate the whole session once.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seats", type=int, default=400)
    parser.add_argument("--seed", type=int, default=561)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    results = {
        "plain": measure(seats=args.seats, seed=args.seed, long_names=False),
        "long_names": measure(seats=args.seats, seed=args.seed, long_names=True),
    }
    print_report(results["plain"])
    print()
    print_report(results["long_names"])
    if args.json_output:
        args.json_output.write_text(json.dumps(results, indent=2) + "\n")
        print(f"\nWrote {args.json_output}")


if __name__ == "__main__":
    main()
