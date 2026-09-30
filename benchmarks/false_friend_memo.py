#!/usr/bin/env python3
"""What a mixed-language game's false-friend guard keeps between turns (#1252).

In a mixed room every guess asks, in the guesser's language, whether the words
typed are another prompt of this game (`Game._other_prompts_keys`), and the
answer is memoised per prompt in play and language. This plays a whole game
- ``--seats`` seats spread over ``--languages`` languages, ``--rounds`` rounds,
every language guessing wrong once a turn - over a synthetic pool of
``--pool`` concepts with ``--aliases`` aliases per language, and reports what
the memo holds at the end: its sets, the strings in them, and their bytes.

    backend/.venv/bin/python benchmarks/false_friend_memo.py --seats 16 --languages 7 --rounds 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.game import Game, PromptForm  # noqa: E402

LANGUAGES = ("en", "de", "fr", "it", "es", "pt", "nl")


def build(args) -> Game:
    languages = LANGUAGES[: args.languages]
    concepts = [f"c{index}" for index in range(args.pool)]
    translations = {
        concept: {
            language: PromptForm(
                f"{language}word{index}",
                tuple(f"{language}alias{index}x{alias}" for alias in range(args.aliases)),
                f"v-{concept}-{language}",
            )
            for language in languages
        }
        for index, concept in enumerate(concepts)
    }
    seats = [f"s{index}" for index in range(args.seats)]
    return Game(
        turn_order=list(seats),
        rounds_total=args.rounds,
        prompt_language="mul",
        prompt_pool=list(concepts),
        prompt_answers={concept: translations[concept]["en"].answer for concept in concepts},
        prompt_version_ids={concept: f"v-{concept}-en" for concept in concepts},
        prompt_translations=translations,
        seat_languages={seat: languages[index % len(languages)] for index, seat in enumerate(seats)},
        hint_mode="checkpoints",
    )


def play(game: Game, turns: int) -> None:
    for turn in range(turns):
        game.start_next_turn(canvas_generation=turn + 1)
        assert game.choose_prompt_option(game.current_drawer, 0)
        asked = set()
        for seat, language in game.seat_languages.items():
            if seat != game.current_drawer and language not in asked:
                asked.add(language)
                game.submit_guess(seat, "not even close")
        game.snapshot_turn_participants({})
        game.end_turn(0, terminal_states={})
        game.advance_phase_after_turn()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seats", type=int, default=16)
    parser.add_argument("--languages", type=int, default=7, choices=range(2, len(LANGUAGES) + 1))
    parser.add_argument("--rounds", type=int, default=10)
    # The Standard family: 260 concepts a language and next to no aliases.
    # A 16 x 10 game draws rounds x seats x 3 = 480, so it holds all 260, and
    # each of its 160 turns plays a prompt of its own for most of the game.
    parser.add_argument("--pool", type=int, default=260, help="concepts the game drew")
    parser.add_argument("--aliases", type=int, default=0)
    args = parser.parse_args()
    game = build(args)
    play(game, args.seats * args.rounds)
    sets = list(game._taken_keys.values())
    # Each set's strings are its own: `_normalize` builds them per call.
    held = {id(value): sys.getsizeof(value) for value in sets}
    held.update({id(word): sys.getsizeof(word) for value in sets for word in value})
    print(json.dumps({
        "game": f"{args.seats} seats x {args.languages} languages x {args.rounds} rounds, pool {args.pool}",
        "memo_sets": len(sets),
        "memo_strings": sum(len(value) for value in sets),
        "memo_mb": round(sum(held.values()) / 1e6, 2),
    }, indent=2))


if __name__ == "__main__":
    main()
