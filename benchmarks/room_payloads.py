#!/usr/bin/env python3
"""What the room-scoped JSON events actually cost on the wire.

The point of this benchmark is that the obvious measurement is misleading.
`room_state` is a few kilobytes and is broadcast to every socket on every
join, vote, and AFK toggle, which makes an explicit delta protocol look like
an enormous win. But the deployment negotiates permessage-deflate with context
takeover, and consecutive `room_state` payloads are nearly identical - so a
socket's compressor has already seen almost every byte of the next one.

Whether a delta protocol is worth building depends entirely on the gap between
those two numbers, so this measures both, and measures an explicit delta the
same way for comparison.

Each connection gets its own compressor, and a broadcast is compressed
separately per socket, so a single warm stream is the right model for one
viewer's experience of a sequence of room events.

Usage:
  backend/.venv/bin/python benchmarks/room_payloads.py
  backend/.venv/bin/python benchmarks/room_payloads.py --players 16
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import zlib
from itertools import pairwise
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.rooms import RoomManager


def json_bytes(value) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def event_message(event: str, payload) -> bytes:
    """One Socket.IO text packet, as it reaches the WebSocket."""
    return b"42" + json_bytes([event, payload])


def deflated_stream_bytes(messages: list[bytes]) -> list[int]:
    """Per-message wire cost through one permessage-deflate context."""
    compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
    return [
        len(compressor.compress(message) + compressor.flush(zlib.Z_SYNC_FLUSH))
        for message in messages
    ]


def build_room(players: int):
    manager = RoomManager()
    room = manager.create_room(name="Benchmark Room", max_players=players)
    for index in range(players):
        seat = manager.add_player(room, f"Player_{index}")
        seat.score = index * 37
    return manager, room


def room_event_sequence(manager, room, rounds: int = 12) -> list[dict]:
    """A plausible run of room churn: votes, AFK flags, scores, a join."""
    states = [room.to_state_payload()]
    seats = room.player_list()
    for step in range(rounds):
        target = seats[step % len(seats)]
        voter = seats[(step + 1) % len(seats)]
        if step % 4 == 0:
            target.kick_votes.add(voter.id)
        elif step % 4 == 1:
            target.is_afk = not target.is_afk
        elif step % 4 == 2:
            target.score += 120
        else:
            target.connected = not target.connected
        states.append(room.to_state_payload())
    return states


def changed_keys(previous: dict, current: dict) -> dict:
    """The delta #417 would send: only top-level keys that actually moved."""
    delta = {"stateVersion": 1}
    for key, value in current.items():
        if previous.get(key) != value:
            delta[key] = value
    return delta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=int, default=12)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    manager, room = build_room(args.players)
    states = room_event_sequence(manager, room)

    full_messages = [event_message("room_state", state) for state in states]
    delta_messages = [full_messages[0]] + [
        event_message("room_delta", changed_keys(previous, current))
        for previous, current in pairwise(states)
    ]

    full_raw = [len(message) for message in full_messages]
    delta_raw = [len(message) for message in delta_messages]
    full_wire = deflated_stream_bytes(full_messages)
    delta_wire = deflated_stream_bytes(delta_messages)

    # The first broadcast is a cold context and is paid either way, so the
    # steady-state comparison is what matters for a delta protocol.
    steady = slice(1, None)
    rows = [
        ("full room_state, uncompressed", sum(full_raw[steady]), len(full_raw[steady])),
        ("full room_state, on the wire", sum(full_wire[steady]), len(full_wire[steady])),
        ("room_delta, uncompressed", sum(delta_raw[steady]), len(delta_raw[steady])),
        ("room_delta, on the wire", sum(delta_wire[steady]), len(delta_wire[steady])),
    ]

    print(f"Room payload benchmark - {args.players} players, "
          f"{len(full_raw) - 1} churn events")
    print(f"first broadcast: {full_raw[0]:,} B uncompressed, "
          f"{full_wire[0]:,} B on the wire\n")
    print(f"{'':<32}{'total':>10}{'per event':>12}")
    print("-" * 54)
    for label, total, count in rows:
        print(f"{label:<32}{total:>9,}B{total / count:>11,.0f}B")

    full_steady = sum(full_wire[steady]) / len(full_wire[steady])
    delta_steady = sum(delta_wire[steady]) / len(delta_wire[steady])
    print("-" * 54)
    print(f"compression on full state : "
          f"{(1 - sum(full_wire[steady]) / sum(full_raw[steady])) * 100:.1f}%")
    print(f"delta saves, uncompressed : "
          f"{(1 - sum(delta_raw[steady]) / sum(full_raw[steady])) * 100:.1f}%")
    print(f"delta saves, on the wire  : "
          f"{(1 - delta_steady / full_steady) * 100:.1f}%   <- what #417 is worth")

    audience = max(0, args.players - 1)
    print(f"\nper churn event, broadcast to {audience} other sockets:")
    print(f"  full state on the wire : {full_steady * audience:>8,.0f} B")
    print(f"  delta on the wire      : {delta_steady * audience:>8,.0f} B")

    if args.json_output:
        args.json_output.write_text(json.dumps({
            "players": args.players,
            "full_raw": full_raw, "full_wire": full_wire,
            "delta_raw": delta_raw, "delta_wire": delta_wire,
        }, indent=2) + "\n")
        print(f"\nWrote JSON results to {args.json_output}")


if __name__ == "__main__":
    main()
