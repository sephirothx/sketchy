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
    offered_ids: list[str | None] | None = None,
    chosen_id: str | None = "__auto__",
) -> CompletedTurnStats:
    return CompletedTurnStats(
        round_number=1,
        turn_number=number,
        offered_prompts=offered,
        chosen_prompt=chosen,
        correct_guess_count=correct,
        total_guesser_count=guessers,
        offered_prompt_version_ids=tuple(
            offered_ids
            if offered_ids is not None
            else [f"version:{prompt}" for prompt in offered]
        ),
        chosen_prompt_version_id=(
            f"version:{chosen}" if chosen_id == "__auto__" else chosen_id
        ) if chosen else None,
    )


def test_a_word_offered_in_several_turns_is_counted_once_per_turn():
    usage = tally_prompt_usage([
        turn(offered=["apple", "banana", "robot"], chosen="robot", number=1),
        turn(offered=["apple", "castle", "dragon"], chosen="castle", number=2),
    ])

    assert usage.offers == {
        "version:apple": 2,
        "version:banana": 1,
        "version:robot": 1,
        "version:castle": 1,
        "version:dragon": 1,
    }


def test_picks_accumulate_when_a_short_pool_repeats_a_word():
    """A pool too small to keep excluding used words can draw one twice."""
    usage = tally_prompt_usage([
        turn(offered=["robot"], chosen="robot", correct=2, guessers=3, number=1),
        turn(offered=["robot"], chosen="robot", correct=1, guessers=3, number=2),
    ])

    totals = usage.picks["version:robot"]
    assert totals.picks == 2
    assert totals.correct_guesses == 3
    assert totals.total_guessers == 6


def test_display_copy_never_decides_attribution():
    usage = tally_prompt_usage([
        turn(
            offered=["  Apple ", "RED PANDA"],
            offered_ids=["apple-v1", "panda-v4"],
            chosen="RED PANDA",
            chosen_id="panda-v4",
            correct=1,
            guessers=2,
        ),
    ])

    assert set(usage.offers) == {"apple-v1", "panda-v4"}
    assert set(usage.picks) == {"panda-v4"}


def test_a_turn_nobody_finished_still_records_its_offers():
    """An abandoned prompt was still shown to the drawer, and that is the point
    of offer_count: it is the denominator for how often a prompt gets picked."""
    usage = tally_prompt_usage([turn(offered=["apple", "banana"], chosen="")])

    assert usage.offers == {"version:apple": 1, "version:banana": 1}
    assert usage.picks == {}
    assert usage, "there is still something to write"


def test_a_game_with_nothing_to_record_is_falsy():
    assert not tally_prompt_usage([])
    assert not tally_prompt_usage([turn(offered=[], chosen="")])


def test_ephemeral_prompt_text_collision_never_credits_curated_content():
    usage = tally_prompt_usage([
        turn(
            offered=["apple", "kite"],
            offered_ids=[None, None],
            chosen="kite",
            chosen_id=None,
            correct=2,
            guessers=2,
        )
    ])

    assert not usage
