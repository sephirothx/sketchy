#!/usr/bin/env python3
"""Would a room-state delta protocol pay for itself? Measured on a real
viewer's stream, not on adjacent snapshots (#493).

`benchmarks/room_payloads.py` compares consecutive `room_state` broadcasts
through one warm deflate context and finds a delta worth ~8%. That is the best
case for full snapshots: nothing intervenes, so the compressor's window still
holds the previous state. A real viewer's window also carries every draw frame,
chat line and sync between two room states, which is what evicts the
dictionary and what this measures. The input is one seat's inbound stream,
captured raw and in order by the load gate under the full population
(`benchmarks/run_load.sh --capture-seat`, kept under `fixtures/viewer_streams/`).

Three streams are replayed through one deflate context each, at the server's
settings (level 6, a 15-bit window, context takeover), and one without
compression, which is also the long-polling bound:

- **as captured** - full `room_state` snapshots, whatever else was between them;
- **with deltas** - every `room_state` after the first replaced by the patch
  #493 describes: the top-level keys that changed since the previous one,
  plus a version, as one `room_delta` event; the first stays a full snapshot
  because a delta has nothing to apply to (a cold join is a snapshot either
  way);
- **snapshots only** - the `room_state` messages alone through their own
  context, the adjacent-snapshot best case, for comparison with the number
  `room_payloads.py` reports.

Also reported: what `room_state` is of the whole stream on the wire, the cost
of building one (`room_state_payload` on a 16- and a 24-seat room, timed) against
how often the gate saw it emitted, and what a 4 KB and an 8 KB window would have
done to the same stream.

Usage:
  backend/.venv/bin/python benchmarks/room_state_deltas.py
  backend/.venv/bin/python benchmarks/room_state_deltas.py --stream fixtures/viewer_streams/gate-viewer-180s.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import timeit
import zlib
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.presenters import room_state_payload
from app.rooms import RoomManager

STREAM_DIR = Path(ROOT_DIR) / "fixtures" / "viewer_streams"
DEFLATE_LEVEL = 6


def load_stream(path: Path) -> list[dict]:
    messages = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record["text"] is None:
            # A binary attachment (a sync's history): its bytes are not in the
            # capture, only their count; modelled as incompressible bytes.
            record["bytes"] = b"\x00" * int(record["binaryBytes"])
            record["event"] = "<binary>"
        else:
            record["bytes"] = record["text"].encode("utf-8")
            record["event"] = event_name(record["text"])
        messages.append(record)
    return messages


def event_name(text: str) -> str:
    """The Socket.IO event a packet carries, or a label for the rest.

    The capture holds Socket.IO packets as the client's handler sees them:
    the Engine.IO type byte is already gone, so `2[...]` is an event,
    `3N[...]` an acknowledgement, `5N-[...]` a binary event's header, `0{...}`
    the connect."""
    kind = text[:1]
    if kind in ("2", "5"):
        start = text.find("[")
        if start >= 0:
            try:
                return json.loads(text[start:])[0]
            except (ValueError, IndexError):
                pass
        return "<event>"
    if kind in ("3", "6"):
        return "<ack>"
    if kind == "0":
        return "<connect>"
    return f"<{kind}>"


def room_state_of(text: str) -> dict | None:
    start = text.find("[")
    try:
        event, payload = json.loads(text[start:])[:2]
    except (ValueError, IndexError):
        return None
    return payload if event == "room_state" and isinstance(payload, dict) else None


def changed_keys(previous: dict, current: dict) -> dict:
    """The patch #493 describes: top-level keys that moved, and a version."""
    patch = {"stateVersion": 1}
    for key, value in current.items():
        if previous.get(key) != value:
            patch[key] = value
    for key in previous:
        if key not in current:
            patch[key] = None
    return patch


def with_deltas(messages: list[dict]) -> list[bytes]:
    out = []
    previous: dict | None = None
    for record in messages:
        state = room_state_of(record["text"]) if record["text"] else None
        if state is None:
            out.append(record["bytes"])
            continue
        if previous is None:
            out.append(record["bytes"])
        else:
            patch = changed_keys(previous, state)
            out.append(('2["room_delta",' + json.dumps(patch, separators=(",", ":")) + "]").encode("utf-8"))
        previous = state
    return out


def deflated(messages: list[bytes], window_bits: int = 15) -> list[int]:
    compressor = zlib.compressobj(DEFLATE_LEVEL, zlib.DEFLATED, -window_bits)
    sizes = []
    for message in messages:
        sizes.append(len(compressor.compress(message)) + len(compressor.flush(zlib.Z_SYNC_FLUSH)) - 4)
    return sizes


def build_room(players: int):
    manager = RoomManager()
    room = manager.create_room(name="Benchmark Room", max_players=players)
    for index in range(players):
        seat = manager.add_player(room, f"Player_{index}")
        seat.score = index * 37
    return room


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stream", type=Path, default=STREAM_DIR / "gate-viewer-180s.jsonl")
    parser.add_argument("--emits-per-second", type=float, default=1446 / 180, help="room_state emits the gate saw server-wide, per second (default: the 180 s capture run, 1446 in 180 s)")
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    messages = load_stream(args.stream)
    duration = messages[-1]["atMs"] / 1000 if messages else 0.0
    raw = [record["bytes"] for record in messages]
    events = [record["event"] for record in messages]
    is_state = [event == "room_state" for event in events]
    delta_raw = with_deltas(messages)

    wire = deflated(raw)
    wire_delta = deflated(delta_raw)
    states_only = deflated([record["bytes"] for record in messages if record["event"] == "room_state"])
    uncompressed = [len(m) for m in raw]
    uncompressed_delta = [len(m) for m in delta_raw]

    def total(sizes, mask=None):
        return sum(size for size, keep in zip(sizes, mask or [True] * len(sizes)) if keep)

    state_count = sum(is_state)
    report = {
        "stream": str(args.stream.relative_to(ROOT_DIR)) if args.stream.is_relative_to(ROOT_DIR) else str(args.stream),
        "seconds": duration,
        "messages": len(messages),
        "roomStates": state_count,
        "byEvent": {},
        "asCaptured": {"uncompressed": total(uncompressed), "wire": total(wire), "roomStateWire": total(wire, is_state), "roomStateUncompressed": total(uncompressed, is_state)},
        "withDeltas": {"uncompressed": total(uncompressed_delta), "wire": total(wire_delta), "roomStateWire": total(wire_delta, is_state), "roomStateUncompressed": total(uncompressed_delta, is_state)},
        "snapshotsOnlyWire": sum(states_only),
        "coldFirstStateWire": next((size for size, keep in zip(wire, is_state) if keep), 0),
        "windows": {},
        "buildCost": {},
    }
    for event in sorted(set(events)):
        mask = [e == event for e in events]
        report["byEvent"][event] = {"count": sum(mask), "uncompressed": total(uncompressed, mask), "wire": total(wire, mask)}
    for bits in (12, 13, 15):
        report["windows"][f"{bits}bits"] = {"asCaptured": sum(deflated(raw, bits)), "withDeltas": sum(deflated(delta_raw, bits))}
    for players in (8, 16, 24):
        room = build_room(players)
        seconds = timeit.timeit(lambda room=room: room_state_payload(room), number=2000) / 2000
        report["buildCost"][players] = {"microseconds": seconds * 1e6, "bytes": len(json.dumps(room_state_payload(room), separators=(",", ":")))}

    a, d = report["asCaptured"], report["withDeltas"]
    saving_wire = (a["wire"] - d["wire"]) / a["wire"] * 100 if a["wire"] else 0.0
    saving_raw = (a["uncompressed"] - d["uncompressed"]) / a["uncompressed"] * 100 if a["uncompressed"] else 0.0
    per_second = (a["wire"] - d["wire"]) / duration if duration else 0.0
    report["savingWirePercent"] = saving_wire
    report["savingUncompressedPercent"] = saving_raw
    report["savingWireBytesPerSecondPerSeat"] = per_second
    at_400 = per_second * 400
    report["savingWireBytesPerSecondAt400Seats"] = at_400
    build16 = report["buildCost"][16]["microseconds"]
    report["buildCpuPercentAtGateRate"] = args.emits_per_second * build16 / 1e6 * 100

    print(f"\nRoom-state deltas on a real viewer's stream: {report['stream']}, {duration:.0f} s, {len(messages)} messages, {state_count} room_state")
    print(f"  {'':<28}{'uncompressed':>14}{'on the wire':>13}{'room_state wire':>17}")
    print(f"  {'as captured':<28}{a['uncompressed']:>13,} B{a['wire']:>12,} B{a['roomStateWire']:>16,} B")
    print(f"  {'with deltas (#493 patch)':<28}{d['uncompressed']:>13,} B{d['wire']:>12,} B{d['roomStateWire']:>16,} B")
    print(f"  saving: {saving_raw:.1f}% uncompressed (the polling bound), {saving_wire:.1f}% on the wire = "
          f"{per_second:.1f} B/s per seat, {at_400 / 1000:.1f} KB/s at 400 seats")
    print(f"  room_state share of the stream on the wire: {100 * a['roomStateWire'] / a['wire']:.1f}%; "
          f"first (cold) room_state {report['coldFirstStateWire']:,} B; "
          f"snapshots alone through their own context {report['snapshotsOnlyWire']:,} B "
          f"({report['snapshotsOnlyWire'] / max(1, state_count):.0f} B each, the adjacent best case)")
    print("  by event on the wire:")
    for event, item in sorted(report["byEvent"].items(), key=lambda kv: -kv[1]["wire"])[:8]:
        print(f"    {event:<24}{item['count']:>6}{item['uncompressed']:>10,} B{item['wire']:>10,} B")
    print("  windows: " + ", ".join(f"{bits}: {w['asCaptured']:,} -> {w['withDeltas']:,} B" for bits, w in report["windows"].items()))
    print("  building room_state: " + ", ".join(f"{p} seats {c['microseconds']:.0f} us ({c['bytes']:,} B)" for p, c in report["buildCost"].items())
          + f"; at the gate's {args.emits_per_second:.1f} emits/s that is {report['buildCpuPercentAtGateRate']:.2f}% of one core")
    if args.json_output:
        args.json_output.write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
