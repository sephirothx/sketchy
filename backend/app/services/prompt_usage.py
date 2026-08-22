"""Turn a finished game's turns into immutable prompt-usage facts.

Kept apart from `GameFlowService` for the same reason as `game_history`: it is
pure. No sockets, no database, no timers - just the mapping from what the game
remembers to the increments a `PromptListRepository` applies.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime

from app.game import CompletedTurnStats
from app.repositories.interfaces import PromptPickTotals, PromptUsage


def tally_prompt_usage(
    turns: Iterable[CompletedTurnStats],
    *,
    batch_id: str | None = None,
    occurred_at: datetime | None = None,
    scoring_mode: str = "default",
    hint_mode: str = "none",
) -> PromptUsage:
    """Aggregate every turn's offers and picks into one set of increments.

    Aggregating rather than replaying turn by turn is what lets a whole game
    be written in a few statements. It also has to be aggregation rather than
    a set: the same prompt can be offered in several turns, and a pool too small
    to keep excluding what it has already used can have it chosen twice too.

    Identity, never display text, decides attribution. Ephemeral room prompts
    carry null source IDs and are discarded even if their text is identical to
    a curated prompt. The display snapshots remain available to history.
    """
    offers: Counter[str] = Counter()
    picks: Counter[str] = Counter()
    correct_guesses: Counter[str] = Counter()
    total_guessers: Counter[str] = Counter()

    for turn in turns:
        for prompt_version_id in turn.offered_prompt_version_ids:
            if prompt_version_id:
                offers[prompt_version_id] += 1
        chosen = turn.chosen_prompt_version_id
        if chosen is None:
            continue
        picks[chosen] += 1
        correct_guesses[chosen] += turn.correct_guess_count
        total_guessers[chosen] += turn.total_guesser_count

    dimensions = {
        "scoring_mode": scoring_mode,
        "hint_mode": hint_mode,
        **({"batch_id": batch_id} if batch_id is not None else {}),
        **({"occurred_at": occurred_at} if occurred_at is not None else {}),
    }
    return PromptUsage(
        offers=dict(offers),
        picks={
            prompt: PromptPickTotals(
                picks=count,
                correct_guesses=correct_guesses[prompt],
                total_guessers=total_guessers[prompt],
            )
            for prompt, count in picks.items()
        },
        **dimensions,
    )
