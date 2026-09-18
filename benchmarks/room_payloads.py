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

A second report (#871) measures the waiting room after a finished game, where
the snapshot used to carry the whole recap - scores, highlights and every
drawing's metadata with its reactions. Past the 32 KB window the previous copy
has been evicted, so a repeat stops being a back-reference and costs kilobytes;
the report shows what a waiting-room broadcast and a recap reaction cost per
seat for a range of games, against whatever `Room.to_state_payload` builds.

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

from app.rooms import DrawingRecapEntry, RoomManager
from app.services.drawing_reactions import reaction_broadcast
from app.services.game_highlights import MOST_REACTED_KIND, refresh_reaction_highlight

EMOJI = ("heart", "laugh", "wow", "clap", "fire")


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


def finished_game_room(seats: int, rounds: int):
    """A waiting room just after a `seats` x `rounds` game: every turn in the
    recap, a realistic spread of reactions (each seat on about half the
    drawings), final scores and a full set of highlight cards."""
    manager, room = build_room(seats)
    players = room.player_list()
    turn = 0
    for round_number in range(1, rounds + 1):
        for drawer in players:
            turn += 1
            turn_id = f"0192f3a0-0000-7000-8000-{turn:012d}"
            room.last_game_drawings.append(DrawingRecapEntry(
                turn_id=turn_id, round_number=round_number, turn_number=turn,
                drawer_id=drawer.id, drawer_nickname=drawer.nickname,
                drawer_name_color=drawer.name_color, prompt=f"prompt number {turn}",
                action_count=40, canvas_history=b"\x00" * 4000,
            ))
            for index, seat in enumerate(players):
                if seat is not drawer and (index + turn) % 2 == 0:
                    room.set_drawing_reaction(turn_id, seat.id, EMOJI[(index + turn) % len(EMOJI)])
    room.last_game_scores = [
        {"playerId": p.id, "nickname": p.nickname, "nameColor": p.name_color,
         "avatarUrl": None, "isAnonymous": True, "score": p.score}
        for p in sorted(players, key=lambda p: -p.score)
    ]
    room.last_game_highlights = [
        {"kind": kind, "playerId": players[0].id, "nickname": players[0].nickname,
         "nameColor": players[0].name_color, "isAnonymous": True, "value": 12, "prompt": "prompt number 3"}
        for kind in ("fastest_guess", "hardest_prompt", "best_drawer", "sharpest_guesser")
    ]
    refresh_reaction_highlight(room)
    room.state = "waiting"
    return room


def finished_game_report(seats: int, rounds: int) -> dict:
    """Per seat, on the wire: a waiting-room broadcast after the first, and a
    recap reaction - `drawing_reaction`, plus the `room_state` that followed
    it for as long as the snapshot carried the recap."""
    room = finished_game_room(seats, rounds)
    players = room.player_list()
    carries_recap = "lastGameDrawings" in room.to_state_payload()
    messages = [event_message("room_state", room.to_state_payload())]
    kinds = ["first"]
    for step in range(12):
        seat = players[step % len(players)]
        if step % 2 == 0:
            seat.is_afk = not seat.is_afk
            messages.append(event_message("room_state", room.to_state_payload()))
            kinds.append("churn")
            continue
        turn_id = room.last_game_drawings[step].turn_id
        room.set_drawing_reaction(turn_id, seat.id, "fire")
        refresh_reaction_highlight(room)
        reaction = reaction_broadcast(room, seat, turn_id, "fire")
        if not carries_recap:
            reaction["highlight"] = next(
                (h for h in room.last_game_highlights if h.get("kind") == MOST_REACTED_KIND), None
            )
        messages.append(event_message("drawing_reaction", reaction))
        kinds.append("reaction")
        if carries_recap:
            messages.append(event_message("room_state", room.to_state_payload()))
            kinds.append("reaction")
    wire = deflated_stream_bytes(messages)
    raw = [len(m) for m in messages]
    churn = [w for w, k in zip(wire, kinds) if k == "churn"]
    reaction = [w for w, k in zip(wire, kinds) if k == "reaction"]
    reactions = sum(1 for step in range(12) if step % 2 == 1)
    return {
        "seats": seats, "rounds": rounds, "carriesRecap": carries_recap,
        "stateRaw": raw[0], "stateFirstWire": wire[0],
        "churnWire": sum(churn) / len(churn),
        "reactionWire": sum(reaction) / max(reactions, 1),
        "reactionMessages": 2 if carries_recap else 1,
    }


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

    print("\nwaiting room after a finished game (#871), per seat on the wire:")
    print(f"{'game':<10}{'room_state raw':>16}{'first':>9}{'each broadcast':>16}{'per reaction':>14}{'msgs':>6}")
    finished = [finished_game_report(seats, rounds) for seats, rounds in ((8, 3), (12, 4), (16, 3), (8, 10), (16, 10))]
    for row in finished:
        print(f"{row['seats']:>2} x {row['rounds']:<5}{row['stateRaw']:>15,}B{row['stateFirstWire']:>8,}B"
              f"{row['churnWire']:>15,.0f}B{row['reactionWire']:>13,.0f}B{row['reactionMessages']:>6}")

    if args.json_output:
        args.json_output.write_text(json.dumps({
            "finishedGame": finished,
            "players": args.players,
            "full_raw": full_raw, "full_wire": full_wire,
            "delta_raw": delta_raw, "delta_wire": delta_wire,
        }, indent=2) + "\n")
        print(f"\nWrote JSON results to {args.json_output}")


if __name__ == "__main__":
    main()
