"""Folding a finished game's turns into prompt-list counters."""
from __future__ import annotations

from app.game import CompletedTurnStats
from app.services.prompt_usage import tally_prompt_usage


def turn(
    *,
    offered: list[str],
    chosen: str,
    correct: int = 0,
    guessers: int = 0,
    number: int = 1,
) -> CompletedTurnStats:
    return CompletedTurnStats(
        round_number=1,
        turn_number=number,
        offered_prompts=offered,
        chosen_prompt=chosen,
        correct_guess_count=correct,
        total_guesser_count=guessers,
    )


def test_a_word_offered_in_several_turns_is_counted_once_per_turn():
    usage = tally_prompt_usage([
        turn(offered=["apple", "banana", "robot"], chosen="robot", number=1),
        turn(offered=["apple", "castle", "dragon"], chosen="castle", number=2),
    ])

    assert usage.offers == {
        "apple": 2,
        "banana": 1,
        "robot": 1,
        "castle": 1,
        "dragon": 1,
    }


def test_picks_accumulate_when_a_short_pool_repeats_a_word():
    """A pool too small to keep excluding used words can draw one twice."""
    usage = tally_prompt_usage([
        turn(offered=["robot"], chosen="robot", correct=2, guessers=3, number=1),
        turn(offered=["robot"], chosen="robot", correct=1, guessers=3, number=2),
    ])

    totals = usage.picks["robot"]
    assert totals.picks == 2
    assert totals.correct_guesses == 3
    assert totals.total_guessers == 6


def test_words_are_tallied_in_the_form_the_word_lists_store():
    """`upsert_bundled` lower-cases what it stores, so matching must too."""
    usage = tally_prompt_usage([
        turn(offered=["  Apple ", "RED PANDA"], chosen="RED PANDA", correct=1, guessers=2),
    ])

    assert set(usage.offers) == {"apple", "red panda"}
    assert set(usage.picks) == {"red panda"}


def test_a_turn_nobody_finished_still_records_its_offers():
    """An abandoned prompt was still shown to the drawer, and that is the point
    of offer_count: it is the denominator for how often a prompt gets picked."""
    usage = tally_prompt_usage([turn(offered=["apple", "banana"], chosen="")])

    assert usage.offers == {"apple": 1, "banana": 1}
    assert usage.picks == {}
    assert usage, "there is still something to write"


def test_a_game_with_nothing_to_record_is_falsy():
    assert not tally_prompt_usage([])
    assert not tally_prompt_usage([turn(offered=[], chosen="")])
    # Blank entries are dropped rather than tallied under an empty key.
    assert not tally_prompt_usage([turn(offered=["  "], chosen="   ")])
