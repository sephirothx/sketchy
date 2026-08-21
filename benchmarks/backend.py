#!/usr/bin/env python3
"""Backend micro-benchmark suite for Sketchy.

Measures execution time and ops/sec for key backend operations:
- Wheel letter pricing and prompt-pool letter frequency calculations
- Room lookup by code
- Guess matching and edit-distance calculations
- Room state payload serialization

Usage:
  backend/.venv/bin/python benchmarks/backend.py
"""

from __future__ import annotations

import os
import random
import sys
import time
from typing import Callable, Any

# Ensure backend directory is in python path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.game import Game, Phase
from app.prompts import PROMPTS
from app.rooms import RoomManager


def benchmark(name: str, fn: Callable[[], Any], iterations: int = 1_000) -> float:
    """Run `fn` for `iterations` times and print timing results."""
    # Warmup
    for _ in range(min(10, iterations)):
        fn()

    start = time.perf_counter()
    for _ in range(iterations):
        fn()
    elapsed = time.perf_counter() - start

    avg_ms = (elapsed / iterations) * 1000
    ops_per_sec = iterations / elapsed if elapsed > 0 else float("inf")

    print(f"{name:<55} | {iterations:>7} | {elapsed*1000:>9.2f} ms | {avg_ms:>8.4f} ms/op | {ops_per_sec:>10.0f} ops/s")
    return elapsed


def run_all_benchmarks() -> None:
    # Keep benchmark setup deterministic. The measured operations do not use
    # randomness, but turn setup and room-code generation do.
    random.seed(0)

    print("=" * 105)
    print(f"{'Sketchy Backend Micro-Benchmark Suite':^105}")
    print("=" * 105)
    print(f"{'Benchmark Name':<55} | {'Iters':>7} | {'Total Time':>12} | {'Avg Latency':>11} | {'Throughput':>12}")
    print("-" * 105)

    # -------------------------------------------------------------------------
    # 1. Wheel Letter Prices (Issue #143 candidate)
    # -------------------------------------------------------------------------
    game_default = Game(turn_order=["p1", "p2", "p3"], prompt_pool=PROMPTS)
    default_choices = game_default.start_next_turn(canvas_generation=1)
    assert game_default.choose_prompt("p1", default_choices[0])
    assert game_default.phase == Phase.DRAWING

    benchmark(
        "1a. wheel_letter_prices (default 64-prompt pool)",
        lambda: game_default.wheel_letter_prices("p2"),
        iterations=500,
    )

    # Large custom prompt pool (5,000 prompts)
    custom_pool = [f"prompt_{i}_{prompt}" for i, prompt in enumerate(PROMPTS * 80)]
    game_large = Game(turn_order=["p1", "p2", "p3"], prompt_pool=custom_pool)
    large_choices = game_large.start_next_turn(canvas_generation=1)
    assert game_large.choose_prompt("p1", large_choices[0])
    assert game_large.phase == Phase.DRAWING

    benchmark(
        "1b. wheel_letter_prices (large 5,000-prompt pool)",
        lambda: game_large.wheel_letter_prices("p2"),
        iterations=500,
    )

    # -------------------------------------------------------------------------
    # 2. Room Code Lookups (historical issues #126/#145 evidence)
    # -------------------------------------------------------------------------
    rm_small = RoomManager()
    for i in range(10):
        rm_small.create_room(name=f"Room {i}")
    target_code_small = list(rm_small.rooms.values())[-1].code

    benchmark(
        "2a. get_room_by_code (10 rooms)",
        lambda: rm_small.get_room_by_code(target_code_small),
        iterations=5_000,
    )

    rm_large = RoomManager()
    for i in range(500):
        rm_large.create_room(name=f"Room {i}")
    target_code_large = list(rm_large.rooms.values())[-1].code

    benchmark(
        "2b. get_room_by_code (500 rooms)",
        lambda: rm_large.get_room_by_code(target_code_large),
        iterations=5_000,
    )

    # -------------------------------------------------------------------------
    # 3. Guess Evaluation & Edit-Distance Hint Calculation
    # -------------------------------------------------------------------------
    game_guess = Game(turn_order=["p1", "p2"], prompt_pool=["watermelon"])
    guess_choices = game_guess.start_next_turn(canvas_generation=1)
    assert game_guess.choose_prompt("p1", guess_choices[0])
    assert game_guess.prompt == "watermelon"
    assert game_guess.phase == Phase.DRAWING

    benchmark(
        "3a. submit_guess & guess_hint (close typo)",
        lambda: (game_guess.submit_guess("p2", "watermelnn"), game_guess.guess_hint("p2", "watermelnn")),
        iterations=2_000,
    )

    # -------------------------------------------------------------------------
    # 4. Room State Serialization (historical issue #146 evidence)
    # -------------------------------------------------------------------------
    rm_state = RoomManager()
    room = rm_state.create_room(name="State Room", max_players=12)
    for i in range(12):
        p = rm_state.add_player(room, f"Player_{i}")
        p.kick_votes.add("token_other")
        p.afk_votes.add("token_other")

    benchmark(
        "4. room.to_state_payload (12 players)",
        lambda: room.to_state_payload(),
        iterations=5_000,
    )

    print("-" * 105)


if __name__ == "__main__":
    run_all_benchmarks()
