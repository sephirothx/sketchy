"""Rooms whose seats each play in their own language (#1182).

A mixed room declares `mul`. It may draw on lists every room language can
play - a list in no language, or a list whose family spells every concept in
all seven (Standard, R-PROMPT-01) - and each seat meets the drawn prompt in
the language it joined with: its offers, its letter tiles, its hints and its
near misses. A guess naming the drawing in any language scores, except where
that spelling is another prompt of the game in the guesser's own language.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.db.seed import seed_prompt_lists
from app.domain_values import PROMPT_LANGUAGES
from app.game import Game, Phase, PromptForm
from app.repositories.interfaces import (
    MixedRoomListError,
    PromptListEntryInput,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)
from app.services.prompt_usage import tally_prompt_usage

from tests.dbfixtures import create_test_db


@pytest_asyncio.fixture
async def seeded():
    factory, engine = await create_test_db()
    prompts = SqlAlchemyPromptListRepository(factory)
    await seed_prompt_lists(prompts)
    users = SqlAlchemyUserRepository(factory)
    guest = await users.create_anonymous("Owner")
    owner = await users.claim_account(guest.id, "Owner", "test-hash")
    yield prompts, owner
    await engine.dispose()


async def test_a_mixed_room_pins_standard_in_every_language(seeded):
    prompts, owner = seeded
    pinned = await prompts.authorize_selection(
        ["german_standard"], requesting_user_id=owner.id, expected_language="mul"
    )

    assert pinned.language == "mul"
    assert len(pinned.revision_ids) == len(PROMPT_LANGUAGES)
    # One prompt, however many languages spell it.
    assert pinned.prompt_count == 260
    assert set(pinned.letter_total_by_language) == set(PROMPT_LANGUAGES)
    assert all(pinned.letter_total_by_language.values())

    # Two languages' Standard is the same family, pinned once.
    both = await prompts.authorize_selection(
        ["english_standard", "german_standard"],
        requesting_user_id=owner.id,
        expected_language="mul",
    )
    assert sorted(both.revision_ids) == sorted(pinned.revision_ids)


async def test_a_mixed_room_refuses_a_list_not_every_language_spells(seeded):
    prompts, owner = seeded
    with pytest.raises(MixedRoomListError):
        await prompts.authorize_selection(
            ["german_extended"], requesting_user_id=owner.id, expected_language="mul"
        )
    owned = await prompts.create_owned(
        owner.id,
        name="Mine",
        description="",
        language="en",
        prompts=(PromptListEntryInput(answer="otter"),),
    )
    with pytest.raises(MixedRoomListError):
        await prompts.authorize_selection(
            [owned.slug], requesting_user_id=owner.id, expected_language="mul"
        )


async def test_a_mixed_room_draws_every_language_s_form_and_agnostic_ones_whole(seeded):
    prompts, owner = seeded
    names = await prompts.create_owned(
        owner.id,
        name="Names",
        description="",
        language="zxx",
        prompts=(PromptListEntryInput(answer="Pikachu"),),
    )
    pinned = await prompts.authorize_selection(
        ["english_standard", names.slug],
        requesting_user_id=owner.id,
        expected_language="mul",
    )
    assert pinned.prompt_count == 261

    sample = await prompts.sample_mixed_prompts(list(pinned.revision_ids), limit=300)

    assert sample.drawable == 261
    assert len(sample.prompts) == 261
    agnostic = [prompt for prompt in sample.prompts if not prompt.translations]
    assert [prompt.answer for prompt in agnostic] == ["Pikachu"]
    spelled = [prompt for prompt in sample.prompts if prompt.translations]
    assert all(set(p.translations) == set(PROMPT_LANGUAGES) for p in spelled)
    dog = next(p for p in spelled if p.translations["en"].answer == "dog")
    assert dog.translations["de"].answer == "Hund"
    assert dog.translations["de"].prompt_version_id != dog.translations["en"].prompt_version_id


def _mixed_game() -> Game:
    """A drawer in English and guessers in German, French and Italian, over a
    pool holding the bow tie - Italian "papillon" - and the butterfly, French
    "papillon"."""
    bow_tie = {
        "en": PromptForm("bow tie", (), "v-bow-en"),
        "de": PromptForm("Fliege", (), "v-bow-de"),
        "fr": PromptForm("nœud papillon", (), "v-bow-fr"),
        "it": PromptForm("papillon", ("cravattino",), "v-bow-it"),
    }
    butterfly = {
        "en": PromptForm("butterfly", (), "v-fly-en"),
        "de": PromptForm("Schmetterling", (), "v-fly-de"),
        "fr": PromptForm("papillon", (), "v-fly-fr"),
        "it": PromptForm("farfalla", (), "v-fly-it"),
    }
    game = Game(
        turn_order=["drawer", "german", "french", "italian"],
        rounds_total=1,
        prompt_language="mul",
        prompt_pool=["c-bow", "c-fly"],
        prompt_answers={"c-bow": "bow tie", "c-fly": "butterfly"},
        prompt_version_ids={"c-bow": "v-bow-en", "c-fly": "v-fly-en"},
        prompt_translations={"c-bow": bow_tie, "c-fly": butterfly},
        seat_languages={"drawer": "en", "german": "de", "french": "fr", "italian": "it"},
        letter_counts_by_language={"de": {"e": 10, "q": 0}, "en": {"q": 10, "e": 1}},
        letter_total_by_language={"de": 10, "en": 11},
        hint_mode="checkpoints",
    )
    game.start_next_turn(canvas_generation=1)
    index = game.prompt_choices.index("c-bow")
    assert game.choose_prompt_option("drawer", index)
    return game


def test_each_seat_meets_the_prompt_in_its_own_language():
    game = _mixed_game()

    assert game.prompt == "bow tie"
    assert game.prompt_for("german") == "Fliege"
    assert game.masked_prompt("german").endswith("  6")
    assert game.masked_prompt("french").endswith("  4 8")
    assert game.masked_prompt("drawer") == "bow tie"
    assert sorted(game.prompt_choice_answers("german")) == ["Fliege", "Schmetterling"]
    assert game.prompt_spellings()["it"] == "papillon"


def test_a_guess_in_any_language_scores_but_not_a_false_friend():
    game = _mixed_game()

    assert game.submit_guess("german", "bow tie")[0] is True
    assert game.submit_guess("italian", "cravattino")[0] is True
    # "papillon" is the butterfly to a French seat, and another prompt of
    # this game: it does not win the Italian bow tie for them.
    assert game.submit_guess("french", "papillon")[0] is False
    # ...and kept out of the room, where the Italian seat would read its own
    # answer: it is routed like a near miss.
    assert game.guess_hint("french", "papillon") == "close"
    assert game.submit_guess("french", "noeud papillon")[0] is True


def test_a_near_miss_is_measured_in_the_seat_s_own_language_only():
    game = _mixed_game()

    assert game.guess_hint("german", "Fliegee") == "close"
    # Close to the English spelling, which is not the German seat's word.
    assert game.guess_hint("german", "bow tiee") is None


def test_timed_hints_reveal_each_spelling_its_own_share():
    game = _mixed_game()
    game.phase = Phase.DRAWING
    while game.reveal_hint_letter():
        pass

    for token in ("drawer", "german", "french", "italian"):
        text = game.prompt_for(token) or ""
        slots = sum(ch.isalnum() for ch in text)
        hidden = game.masked_prompt(token if token != "drawer" else None).count("_")
        if token == "drawer":
            continue
        assert hidden >= 2, token
        assert slots - hidden <= max(1, round(slots * 0.4)), token


def test_the_wheel_is_priced_from_the_seat_s_own_language():
    game = _mixed_game()
    game.hint_mode = "wheel"

    german = game.wheel_letter_prices("german")
    english = game.wheel_letter_prices("drawer")
    assert german["e"] > german["q"]
    assert english["q"] > english["e"]


def test_each_language_s_guessers_count_against_its_own_version():
    game = _mixed_game()
    game.snapshot_turn_participants(
        {"german": "eligible", "french": "eligible", "italian": "eligible"}
    )
    game.submit_guess("german", "Fliege")
    game.submit_guess("french", "papillon")
    game.end_turn(
        3,
        terminal_states={"german": "active", "french": "active", "italian": "active"},
    )
    [turn] = game.completed_turns

    assert turn.chosen_prompt == "bow tie"
    assert turn.chosen_prompt_version_id == "v-bow-en"
    assert sorted(turn.guess_totals_by_version) == [
        ("v-bow-de", 1, 1),
        ("v-bow-fr", 0, 1),
        ("v-bow-it", 0, 1),
    ]
    usage = tally_prompt_usage(game.completed_turns)
    assert usage.picks["v-bow-en"].picks == 1
    assert usage.picks["v-bow-en"].total_guessers == 0
    assert usage.picks["v-bow-de"].picks == 0
    assert (usage.picks["v-bow-de"].correct_guesses, usage.picks["v-bow-de"].total_guessers) == (1, 1)
