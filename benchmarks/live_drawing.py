#!/usr/bin/env python3
"""Measure what live drawing actually costs on the wire.

The input is a recording of the production client drawing
(`fixtures/live_stroke_trace_v1.json`, made by `record_stroke.sh`): every
`draw` frame the drawer's browser put on its WebSocket, in order, with its
timestamp. Before #563 this benchmark modelled a stroke as one five-point
batch repeated twenty-five times a second, which through permessage-deflate
with context takeover is the best case that exists - the compressor has seen
every byte before - and it also kept the four-byte `00 00 ff ff` sync-flush
suffix that the extension strips from every message. Both biases are gone:
the frames are real and advancing, and the suffix is removed.

What is reported, and why each is its own number:

- **Socket.IO packet bytes** - what the server's own byte counters see
  (`socket_wire.py`), before any transport work. The denominator.
- **Compressed payload bytes**, four ways, because "compression ratio" is
  meaningless without saying which context produced it: one warm context per
  connection carrying only this drawing; the same context with the room's
  other traffic interleaved (chat, a correct guess, a `room_state`), which
  is what a real viewer's compressor has just seen; a cold context per
  message (`no_context_takeover`); and no compression at all, which is also
  what long-polling costs before its HTTP framing.
- **WebSocket frame headers**, separately: 2 B for a payload under 126 B,
  4 B up to 64 KiB, plus a 4 B mask on every client-to-server frame. They
  are added after compression, so they are a per-message floor no payload
  change can lower.
- **Two directions.** The drawer's uplink carries its identity on the
  opening frame; the rebroadcast every viewer receives is the same frame
  verbatim, plus the commit on the frame that closed the action (§7 of the
  wire document). The viewer numbers are per recipient: a deflate context is
  per connection, so a room of N costs N-1 of them.

Everything here is a local model over recorded frames: zlib at the level
uvicorn's wsproto transport uses, no TLS, no TCP, no proxy. It says which
choice is cheaper and by how much; a bandwidth bill needs a capture.

Usage:
  backend/.venv/bin/python benchmarks/live_drawing.py
  backend/.venv/bin/python benchmarks/live_drawing.py --room-size 8 --window-bits 15 12
  backend/.venv/bin/python benchmarks/live_drawing.py --trace /tmp/trace.json --json-output out.json
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import sys
import zlib
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "benchmarks"))

from app.live_drawing import MAX_BASE64_FRAME_BYTES, encode_live_drawing  # noqa: E402
from room_payloads import build_room  # noqa: E402

DEFAULT_TRACE = Path(ROOT_DIR) / "fixtures" / "live_stroke_trace_v1.json"
DEFAULT_ROOM_SIZE = 16
# zlib level 6 is what wsproto's PerMessageDeflate compresses with; memLevel
# is left at zlib's default of 8 for the same reason.
DEFLATE_LEVEL = 6
# What a message's deflate block ends with after Z_SYNC_FLUSH, and what
# permessage-deflate (RFC 7692 §7.2.1) strips before framing.
SYNC_FLUSH_SUFFIX = b"\x00\x00\xff\xff"

IDENTITY_BEARING_EVENTS = frozenset(
    {"draw_start", "draw_shape", "draw_fill", "clear_canvas"}
)


def json_bytes(value) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


# --- one Socket.IO event, as WebSocket messages ---------------------------

def event_messages(event: str, *args) -> list[bytes]:
    """The WebSocket messages one emit becomes; bytes args become attachments.

    Socket.IO sends a binary argument as a placeholder in the text packet
    plus one binary message per attachment, which is why a small frame is
    cheaper as base64 text (wire §6).
    """
    attachments: list[bytes] = []

    def placeholder(value):
        if isinstance(value, (bytes, bytearray)):
            attachments.append(bytes(value))
            return {"_placeholder": True, "num": len(attachments) - 1}
        return value

    packet = [event] + [placeholder(arg) for arg in args]
    if attachments:
        head = f"45{len(attachments)}-".encode() + json_bytes(packet)
        return [head, *attachments]
    return [b"42" + json_bytes(packet)]


def draw_frame_argument(frame: str | int):
    """How the drawer sent the frame: an int, base64 text, or raw bytes."""
    if isinstance(frame, int):
        return frame
    raw = base64.b64decode(frame)
    return frame if len(raw) <= MAX_BASE64_FRAME_BYTES else raw


def message_bytes(messages: list[bytes]) -> int:
    return sum(len(m) for m in messages)


def ws_header_bytes(payload_length: int, *, masked: bool) -> int:
    header = 2 if payload_length < 126 else 4 if payload_length < 65536 else 10
    return header + (4 if masked else 0)


# --- compression models ---------------------------------------------------

class Deflater:
    """One permessage-deflate context, as one connection holds it."""

    def __init__(self, window_bits: int = 15, *, takeover: bool = True) -> None:
        self.window_bits = window_bits
        self.takeover = takeover
        self._compressor = self._new()

    def _new(self):
        return zlib.compressobj(DEFLATE_LEVEL, zlib.DEFLATED, -self.window_bits)

    def message(self, data: bytes) -> int:
        """Compressed bytes this message occupies, flush suffix removed."""
        if not self.takeover:
            self._compressor = self._new()
        out = self._compressor.compress(data) + self._compressor.flush(zlib.Z_SYNC_FLUSH)
        assert out.endswith(SYNC_FLUSH_SUFFIX)
        return len(out) - len(SYNC_FLUSH_SUFFIX)


def stream_cost(messages: list[bytes], deflater: Deflater | None, *, masked: bool) -> dict:
    """Payload and framed bytes for a message sequence through one context."""
    payload = 0
    framed = 0
    for data in messages:
        size = deflater.message(data) if deflater else len(data)
        payload += size
        framed += size + ws_header_bytes(size, masked=masked)
    return {"messages": len(messages), "payload": payload, "framed": framed}


# --- the recorded session -------------------------------------------------

def load_trace(path: Path) -> dict:
    trace = json.loads(path.read_text())
    if trace.get("schemaVersion") != 1:
        raise SystemExit(f"{path}: unsupported trace schemaVersion {trace.get('schemaVersion')!r}")
    return trace


def session_frames(trace: dict) -> list[dict]:
    """Every recorded frame in order, tagged with its stroke."""
    frames = []
    for stroke in trace["strokes"]:
        for frame in stroke["frames"]:
            frames.append({**frame, "stroke": stroke["label"]})
    return frames


def session_seconds(trace: dict) -> float:
    """Pen-down time: what a "per second of drawing" rate divides by."""
    return sum(stroke.get("durationMs", 0) for stroke in trace["strokes"]) / 1000


def uplink_messages(frames: list[dict]) -> list[bytes]:
    """What the drawer sends: the frame, plus [generation, sequence] on openers."""
    messages = []
    for frame in frames:
        argument = draw_frame_argument(frame["frame"])
        if "identity" in frame:
            messages.extend(event_messages("draw", argument, frame["identity"]))
        else:
            messages.extend(event_messages("draw", argument))
    return messages


def rebroadcast_messages(frames: list[dict], rng: random.Random) -> list[bytes]:
    """What one viewer receives: the frame verbatim, plus the commit on the closer."""
    messages = []
    revision = 0
    for frame in frames:
        argument = draw_frame_argument(frame["frame"])
        if frame["event"] == "draw_end":
            revision += 1
            commit = [1, revision, revision, rng.getrandbits(32)]
            messages.extend(event_messages("draw", argument, commit))
        else:
            messages.extend(event_messages("draw", argument))
    return messages


def room_traffic(players: int, rng: random.Random) -> dict[str, list[bytes]]:
    """The other events a viewer's connection sees while someone draws."""
    _manager, room = build_room(players)
    room_state = room.to_state_payload()
    return {
        "chat": event_messages(
            "chat_message",
            {
                "id": "m" + str(rng.getrandbits(40)),
                "playerId": "p3",
                "nickname": "Player_3",
                "nameColor": "#7c4dff",
                "text": "is it a snail",
                "kind": "chat",
                "createdAt": 1_757_000_000_000 + rng.randrange(60_000),
            },
        ),
        "correct_guess": event_messages(
            "correct_guess", {"playerId": "p5", "nickname": "Player_5", "points": 140}
        ),
        "room_state": event_messages("room_state", room_state),
    }


def mixed_messages(frames: list[dict], traffic: dict[str, list[bytes]], rng: random.Random) -> list[bytes]:
    """The rebroadcast with the room's other events between strokes.

    A `room_state` before the drawing (the viewer just joined), a chat line
    and a correct guess after the second and third strokes. Enough that the
    context is not the drawing alone; deliberately not a flood.
    """
    messages: list[bytes] = list(traffic["room_state"])
    strokes_closed = 0
    for frame, per_frame in zip(frames, _grouped(rebroadcast_messages(frames, rng), frames)):
        messages.extend(per_frame)
        if frame["event"] == "draw_end":
            strokes_closed += 1
            if strokes_closed == 2:
                messages.extend(traffic["chat"])
            elif strokes_closed == 3:
                messages.extend(traffic["correct_guess"])
    return messages


def _grouped(messages: list[bytes], frames: list[dict]) -> list[list[bytes]]:
    """Re-associate a flat message list with the frame each came from."""
    groups: list[list[bytes]] = []
    index = 0
    for frame in frames:
        count = 2 if not isinstance(frame["frame"], int) and len(base64.b64decode(frame["frame"])) > MAX_BASE64_FRAME_BYTES else 1
        groups.append(messages[index:index + count])
        index += count
    return groups


# --- the report -----------------------------------------------------------

def per_action_table() -> list[dict]:
    """Legacy all-JSON against the hybrid protocol, per action (the #203 record)."""

    def sample_points(count: int) -> list[dict]:
        return [{"x": 0.1 + i / 800, "y": 0.2 + i / 600} for i in range(count)]

    def current(event: str, payload: dict) -> int:
        encoded = encode_live_drawing(event, payload)
        identity = [1, 1] if event in IDENTITY_BEARING_EVENTS else None
        argument = encoded if isinstance(encoded, int) else (
            base64.b64encode(encoded).decode() if len(encoded) <= MAX_BASE64_FRAME_BYTES else encoded
        )
        args = (argument, identity) if identity else (argument,)
        return message_bytes(event_messages("draw", *args))

    actions = [
        ("path start", "draw_start", {"x": 0.12375, "y": 0.45625, "color": "#aabbcc", "width": 6}),
        ("1 point", "draw_move", {"points": sample_points(1)}),
        ("6 points", "draw_move", {"points": sample_points(6)}),
        ("40 points", "draw_move", {"points": sample_points(40)}),
        ("path end", "draw_end", {}),
        ("shape", "draw_shape", {"shape": "rectangle", "from": {"x": 0.1, "y": 0.2}, "to": {"x": 0.8, "y": 0.9}, "color": "#123456", "width": 8}),
        ("fill", "draw_fill", {"x": 0.25, "y": 0.75, "color": "#fedcba"}),
        ("clear", "clear_canvas", {}),
    ]
    return [
        {
            "action": label,
            "event": event,
            "legacy_bytes": message_bytes(event_messages(event, payload)),
            "current_bytes": current(event, payload),
        }
        for label, event, payload in actions
    ]


def measure(trace: dict, *, room_size: int, window_bits: list[int], seed: int) -> dict:
    frames = session_frames(trace)
    seconds = session_seconds(trace)
    uplink = uplink_messages(frames)
    viewer = rebroadcast_messages(frames, random.Random(seed))
    traffic = room_traffic(room_size, random.Random(seed))
    mixed = mixed_messages(frames, traffic, random.Random(seed))
    mixed_other = sum(message_bytes(m) for m in traffic.values())

    cases = {}
    for bits in window_bits:
        cases[f"warm_{bits}"] = {
            "label": f"deflate, context takeover, {bits}-bit window",
            "uplink": stream_cost(uplink, Deflater(bits), masked=True),
            "viewer": stream_cost(viewer, Deflater(bits), masked=False),
            "viewer_mixed": stream_cost(mixed, Deflater(bits), masked=False),
        }
    cases["cold"] = {
        "label": "deflate, no context takeover",
        "uplink": stream_cost(uplink, Deflater(15, takeover=False), masked=True),
        "viewer": stream_cost(viewer, Deflater(15, takeover=False), masked=False),
        "viewer_mixed": stream_cost(mixed, Deflater(15, takeover=False), masked=False),
    }
    cases["none"] = {
        "label": "no compression (also polling's payload)",
        "uplink": stream_cost(uplink, None, masked=True),
        "viewer": stream_cost(viewer, None, masked=False),
        "viewer_mixed": stream_cost(mixed, None, masked=False),
    }
    points = sum(f.get("points", 0) for f in frames)
    strokes = [
        {
            "label": s["label"],
            "points": s["points"],
            "frames": len(s["frames"]),
            "durationMs": s.get("durationMs", 0),
            "uplink_bytes": message_bytes(uplink_messages(s["frames"])),
            "viewer_bytes": message_bytes(rebroadcast_messages(s["frames"], random.Random(seed))),
        }
        for s in trace["strokes"]
    ]
    return {
        "trace": trace["recorded"],
        "room_size": room_size,
        "audience": max(0, room_size - 1),
        "pen_down_seconds": round(seconds, 3),
        "frames": len(frames),
        "points": points,
        "strokes": strokes,
        "socketio_bytes": {"uplink": message_bytes(uplink), "viewer": message_bytes(viewer), "mixed_other_events": mixed_other},
        "cases": cases,
    }


def rate(total: int, seconds: float) -> int:
    return round(total / seconds) if seconds else 0


def print_report(rows: list[dict], result: dict) -> None:
    print("Live drawing Socket.IO payload benchmark")
    print("Action           JSON        Current    Reduction")
    print("-" * 52)
    for row in rows:
        before, after = row["legacy_bytes"], row["current_bytes"]
        print(f"{row['action']:<12} {before:>8,} B {after:>10,} B {(1 - after / before) * 100:>11.1f}%")

    seconds = result["pen_down_seconds"]
    audience = result["audience"]
    recorded = result["trace"]
    print()
    print(
        f"Recorded session - {recorded['how']}, "
        f"{recorded.get('pointerHz') or '?'} Hz pointer, {recorded['browser']}"
    )
    print("-" * 76)
    print(f"{'stroke':<14} {'points':>6} {'frames':>6} {'ms':>7} {'drawer->server':>15} {'server->viewer':>15}")
    for s in result["strokes"]:
        print(f"{s['label']:<14} {s['points']:>6} {s['frames']:>6} {s['durationMs']:>7.0f} {s['uplink_bytes']:>13,} B {s['viewer_bytes']:>13,} B")
    print(f"{'total':<14} {result['points']:>6} {result['frames']:>6} {seconds * 1000:>7.0f} "
          f"{result['socketio_bytes']['uplink']:>13,} B {result['socketio_bytes']['viewer']:>13,} B")

    print()
    print(f"Per second of pen-down drawing, {result['room_size']}-player room ({audience} viewers)")
    print(f"{'':<42} {'drawer up':>10} {'per viewer':>11} {'per viewer':>11} {'room egress':>12}")
    print(f"{'':<42} {'payload':>10} {'drawing':>11} {'+room chat':>11} {'framed':>12}")
    print("-" * 90)
    for case in result["cases"].values():
        up = case["uplink"]["payload"]
        viewer = case["viewer"]["payload"]
        mixed = case["viewer_mixed"]["payload"]
        egress = case["viewer"]["framed"] * audience
        print(f"{case['label']:<42} {rate(up, seconds):>8,} B/s {rate(viewer, seconds):>9,} B/s "
              f"{rate(mixed, seconds):>9,} B/s {rate(egress, seconds):>10,} B/s")
    print("-" * 90)
    print(f"{'Socket.IO packet bytes (what the counters see)':<42} "
          f"{rate(result['socketio_bytes']['uplink'], seconds):>8,} B/s "
          f"{rate(result['socketio_bytes']['viewer'], seconds):>9,} B/s")
    print()
    print("  '+room chat' is the same drawing through a context that also carried a")
    print(f"  room_state, a chat line and a correct guess ({result['socketio_bytes']['mixed_other_events']:,} B uncompressed).")
    print("  'framed' adds WebSocket headers after compression; the drawer's frames are")
    print("  masked (+4 B each). Polling would add an HTTP response per flush on top of")
    print("  the uncompressed row. Nothing here includes TLS or a proxy.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--room-size", type=int, default=DEFAULT_ROOM_SIZE)
    parser.add_argument("--window-bits", type=int, nargs="+", default=[15, 12],
                        help="permessage-deflate server window sizes to model (15 = 32 KiB, 12 = 4 KiB)")
    parser.add_argument("--seed", type=int, default=563)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    trace = load_trace(args.trace)
    rows = per_action_table()
    result = measure(trace, room_size=args.room_size, window_bits=args.window_bits, seed=args.seed)
    print_report(rows, result)
    if args.json_output:
        args.json_output.write_text(json.dumps({"per_action": rows, "session": result}, indent=2) + "\n")
        print(f"\nWrote {args.json_output}")


if __name__ == "__main__":
    main()
