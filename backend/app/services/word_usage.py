"""Turn a finished game's turns into the counters its word lists record.

Kept apart from `GameFlowService` for the same reason as `game_history`: it is
pure. No sockets, no database, no timers - just the mapping from what the game
remembers to the increments a `WordListRepository` applies.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from app.game import CompletedTurnStats
from app.repositories.interfaces import WordPickTotals, WordUsage


def _stored_form(word: str) -> str:
    """Match how `upsert_bundled` stores a word, so rows can be found by text."""
    return word.strip().lower()


def tally_word_usage(turns: Iterable[CompletedTurnStats]) -> WordUsage:
    """Aggregate every turn's offers and picks into one set of increments.

    Aggregating rather than replaying turn by turn is what lets a whole game
    be written in a few statements. It also has to be aggregation rather than
    a set: the same word can be offered in several turns, and a pool too small
    to keep excluding what it has already used can have it chosen twice too.

    Words that no list contains - a room's custom words, which live only in
    memory - simply match no row, so they cost nothing to include here.
    """
    offers: Counter[str] = Counter()
    picks: Counter[str] = Counter()
    correct_guesses: Counter[str] = Counter()
    total_guessers: Counter[str] = Counter()

    for turn in turns:
        for offered in turn.offered_words:
            word = _stored_form(offered)
            if word:
                offers[word] += 1
        chosen = _stored_form(turn.chosen_word)
        if not chosen:
            continue
        picks[chosen] += 1
        correct_guesses[chosen] += turn.correct_guess_count
        total_guessers[chosen] += turn.total_guesser_count

    return WordUsage(
        offers=dict(offers),
        picks={
            word: WordPickTotals(
                picks=count,
                correct_guesses=correct_guesses[word],
                total_guessers=total_guessers[word],
            )
            for word, count in picks.items()
        },
    )
