#!/usr/bin/env python3
"""What the per-socket `turn_started` fan-out actually costs (#419).

`turn_started` is emitted in a loop over every player because `maskedPrompt`,
`hintCost` and `letterPrices` are private to each viewer. At turn start they
are not: nothing has been bought yet, so every guesser's payload is byte-for-
byte identical, and only the drawer (who sees the real prompt) and any
prompt-seeing spectators differ.

The issue proposed broadcasting the guesser payload once and following with a
small private event for the few sockets that genuinely differ, and estimated
`(sockets - 1) x 200 B` saved. **That saving does not exist.** A
permessage-deflate context is per connection, so a room broadcast is compressed
separately for every socket exactly as N individual emits are; the bytes on the
wire are the same either way. What a broadcast can save is *server work*:
building one payload instead of N, and encoding one packet instead of N.

So this measures the work, not the bytes - and measures it against the thing
that matters, which is that a turn start happens once every ninety seconds.

Usage:
  backend/.venv/bin/python benchmarks/turn_start.py
  backend/.venv/bin/python benchmarks/turn_start.py --players 16 --hint-mode wheel
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import timeit

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.game import MAX_HINT_SPEND, Game
from app.rooms import RoomManager

DRAWING_SECONDS = 90


def build_room(players: int, hint_mode: str):
    manager = RoomManager()
    room = manager.create_room(name="Benchmark Room", max_players=players)
    for index in range(players):
        manager.add_player(room, f"Player_{index}")
    room.game = Game(
        turn_order=[player.id for player in room.player_list()],
        prompt_pool=["red panda"],
        hint_mode=hint_mode,
    )
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()
    return room


def turn_started_payload(room, game, player) -> dict:
    """Exactly what `_begin_drawing` builds for one socket today."""
    return {
        "drawerId": game.current_drawer,
        "maskedPrompt": game.masked_prompt(
            player.id,
            is_spectator=player.is_spectator,
            spectators_see_prompt=room.spectators_see_prompt,
        ),
        "roundNumber": game.round_number,
        "totalRounds": game.rounds_total,
        "seconds": game.drawing_seconds,
        "hintCost": game.hint_cost(player.id),
        "letterPrices": (
            game.wheel_letter_prices(player.id) if game.hint_mode == "wheel" else None
        ),
        "hintSpend": 0,
        "maxHintSpend": MAX_HINT_SPEND,
    }


def per_socket(room) -> list[dict]:
    game = room.game
    return [turn_started_payload(room, game, player) for player in room.player_list()]


def broadcast_plus_private(room) -> list[dict]:
    """One guesser-shaped payload, plus one for each socket that differs."""
    game = room.game
    guesser = next(
        player for player in room.player_list() if player.id != game.current_drawer
    )
    payloads = [turn_started_payload(room, game, guesser)]
    for player in room.player_list():
        if player.id == game.current_drawer or (
            player.is_spectator and room.spectators_see_prompt
        ):
            payloads.append(turn_started_payload(room, game, player))
    return payloads


def encode(payloads: list[dict]) -> int:
    """The packet encoding a broadcast does once and a loop does per socket."""
    return sum(
        len(b"42" + json.dumps(["turn_started", payload], separators=(",", ":")).encode())
        for payload in payloads
    )


def micros(callable_, runs: int) -> float:
    return timeit.timeit(callable_, number=runs) / runs * 1e6


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=int, default=16)
    parser.add_argument("--hint-mode", default="wheel", choices=("none", "checkpoints", "purchase", "wheel"))
    parser.add_argument("--runs", type=int, default=2000)
    args = parser.parse_args()

    room = build_room(args.players, args.hint_mode)
    today = per_socket(room)
    proposed = broadcast_plus_private(room)

    # The guesser payloads really are identical, which is the premise the whole
    # issue rests on. Assert it rather than assume it.
    guesser_payloads = [
        payload for payload, player in zip(today, room.player_list())
        if player.id != room.game.current_drawer
    ]
    assert all(payload == guesser_payloads[0] for payload in guesser_payloads), (
        "guesser payloads differ at turn start, so the broadcast premise is wrong"
    )

    build_today = micros(lambda: per_socket(room), args.runs)
    build_proposed = micros(lambda: broadcast_plus_private(room), args.runs)
    encode_today = micros(lambda: encode(today), args.runs)
    encode_proposed = micros(lambda: encode(proposed), args.runs)

    payload_bytes = len(json.dumps(today[0], separators=(",", ":")).encode())

    print(f"turn_started fan-out - {args.players} players, hint mode {args.hint_mode!r}\n")
    print(f"{'':<34}{'today':>12}{'broadcast':>12}{'saved':>10}")
    print("-" * 68)
    print(f"{'payloads built':<34}{len(today):>12}{len(proposed):>12}"
          f"{len(today) - len(proposed):>10}")
    print(f"{'building them (us)':<34}{build_today:>12.1f}{build_proposed:>12.1f}"
          f"{build_today - build_proposed:>10.1f}")
    print(f"{'encoding the packets (us)':<34}{encode_today:>12.1f}{encode_proposed:>12.1f}"
          f"{encode_today - encode_proposed:>10.1f}")
    total = (build_today + encode_today) - (build_proposed + encode_proposed)
    print(f"{'total saved per turn start (us)':<34}{'':>12}{'':>12}{total:>10.1f}")

    print(f"\none payload is {payload_bytes} B of JSON; a turn lasts "
          f"{DRAWING_SECONDS} s")
    print(f"the saving is {total / 1000:.3f} ms once every {DRAWING_SECONDS} s = "
          f"{total / (DRAWING_SECONDS * 1e6) * 100:.6f}% of one core")
    print("\non the wire: 0 B. A deflate context is per connection, so the same "
          "bytes\nare compressed for each socket whether they came from one "
          "broadcast or N emits.")


if __name__ == "__main__":
    main()
