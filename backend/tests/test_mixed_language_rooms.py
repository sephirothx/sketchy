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
    PromptListSelectionError,
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
    prompts.factory = factory
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
    # Close to another language's spelling is kept out of the room too, or
    # the English seat would read its answer in a German seat's typo.
    assert game.guess_hint("german", "bow tiee") == "close"
    assert game.guess_hint("german", "Katze") is None


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


def test_seats_that_spell_the_prompt_alike_see_the_same_letters():
    """By spelling, not by language: seats sharing a spelling cannot pool
    different reveals past the hidden floor (R-HINT-04), and a spectator in a
    language no player uses is revealed to as well."""
    game = Game(
        turn_order=["drawer", "german", "dutch"],
        rounds_total=1,
        prompt_language="mul",
        prompt_pool=["c-avocado"],
        prompt_answers={"c-avocado": "avocado"},
        prompt_translations={
            "c-avocado": {
                "en": PromptForm("avocado", (), "v-en"),
                "de": PromptForm("Avocado", (), "v-de"),
                "nl": PromptForm("avocado", (), "v-nl"),
                "pt": PromptForm("abacate", (), "v-pt"),
            }
        },
        seat_languages={"drawer": "en", "german": "de", "dutch": "nl", "watcher": "pt"},
        hint_mode="checkpoints",
    )
    game.start_next_turn(canvas_generation=1)
    assert game.choose_prompt_option("drawer", 0)
    while game.reveal_hint_letter():
        pass

    assert game.masked_prompt("dutch") == game.masked_prompt("german").replace("A", "a")
    assert game.masked_prompt("watcher").count("_") < len("abacate")


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


def _game_drawn_by(drawer_language: str, *, first: str = "c-bow", rounds: int = 1) -> Game:
    """The same pool as `_mixed_game`, drawn by a seat in `drawer_language`,
    with provenance per language so a turn's record can be told apart."""
    def forms(prefix: str, spelled: dict[str, str], aliases=None) -> dict[str, PromptForm]:
        return {
            language: PromptForm(
                answer,
                (aliases or {}).get(language, ()),
                f"v-{prefix}-{language}",
                (f"r-{language}",),
            )
            for language, answer in spelled.items()
        }

    game = Game(
        turn_order=["drawer", "english", "french", "italian"],
        rounds_total=rounds,
        prompt_language="mul",
        prompt_pool=["c-bow", "c-fly"],
        prompt_answers={"c-bow": "bow tie", "c-fly": "butterfly"},
        prompt_version_ids={"c-bow": "v-bow-en", "c-fly": "v-fly-en"},
        prompt_translations={
            "c-bow": forms("bow", {"en": "bow tie", "de": "Fliege", "fr": "nœud papillon", "it": "papillon"}),
            "c-fly": forms("fly", {"en": "butterfly", "de": "Schmetterling", "fr": "papillon", "it": "farfalla"}),
        },
        seat_languages={
            "drawer": drawer_language,
            "english": "en",
            "french": "fr",
            "italian": "it",
        },
        hint_mode="checkpoints",
    )
    game.start_next_turn(canvas_generation=1)
    assert game.choose_prompt_option("drawer", game.prompt_choices.index(first))
    return game


def test_a_german_drawer_draws_and_records_the_german_word():
    game = _game_drawn_by("de")

    assert game.prompt == "Fliege"
    assert game.turn_language() == "de"
    assert sorted(game.prompt_choice_answers("drawer")) == ["Fliege", "Schmetterling"]
    assert game.masked_prompt("english").endswith("  3 3")
    game.snapshot_turn_participants({"english": "eligible", "french": "eligible", "italian": "eligible"})
    game.end_turn(3, terminal_states={"english": "active", "french": "active", "italian": "active"})
    [turn] = game.completed_turns
    assert turn.chosen_prompt == "Fliege"
    assert sorted(turn.offered_prompts) == ["Fliege", "Schmetterling"]
    assert turn.chosen_prompt_version_id == "v-bow-de"
    assert sorted(turn.offered_prompt_version_ids) == ["v-bow-de", "v-fly-de"]
    assert set(turn.offered_prompt_source_revision_ids) == {("r-de",)}


def test_a_seat_that_never_said_plays_in_english():
    from app.rooms import RoomManager

    game = _game_drawn_by("de")
    assert game.seat_language("somebody-new") == "en"
    manager = RoomManager()
    room = manager.create_room("Room", prompt_language="mul")
    silent = manager.add_player(room, "Silent")
    assert room.seat_language(silent) == "en"
    spoken = manager.add_player(room, "Spoken", prompt_language="it")
    assert room.seat_language(spoken) == "it"


def test_every_spelling_reveals_exactly_its_own_share():
    from app.game import _checkpoint_share

    game = _game_drawn_by("en")
    # The longest spelling in play sets how many checkpoints the turn has:
    # the French "nœud papillon", twelve letters.
    assert game.max_hint_checkpoints() == _checkpoint_share(12)
    while game.reveal_hint_letter():
        pass
    for token in ("english", "french", "italian"):
        word = game.prompt_for(token) or ""
        slots = sum(ch.isalnum() for ch in word)
        shown = slots - game.masked_prompt(token).count("_")
        assert shown == _checkpoint_share(slots), token


def test_a_bought_letter_is_the_buyer_s_own_spelling():
    game = _game_drawn_by("en")
    game.hint_mode = "purchase"
    game.snapshot_turn_participants({"english": "eligible", "french": "eligible", "italian": "eligible"})

    # Slot 10 exists in "nœud papillon" and not in "bow tie".
    assert game.buy_hint_letter("french", 10) is True
    assert game.buy_hint_letter("english", 10) is False
    assert game.masked_prompt("french").split("  ")[1][6] == "o"
    assert game.letter_occurrences("french", "p") == 2
    assert game.letter_occurrences("english", "p") == 0


def test_a_seat_the_turn_froze_out_is_not_counted_against_its_version():
    game = _game_drawn_by("en")
    game.snapshot_turn_participants(
        {"english": "eligible", "french": "eligible", "italian": "afk"}
    )
    game.end_turn(2, terminal_states={"english": "active", "french": "active", "italian": "afk"})
    [turn] = game.completed_turns
    assert sorted(turn.guess_totals_by_version) == [("v-bow-en", 0, 1), ("v-bow-fr", 0, 1)]


def test_the_false_friend_guard_asks_about_the_prompt_in_play_now():
    """The guard remembers what each language's other prompts are, per turn:
    in the butterfly's turn, "papillon" is the bow tie to an Italian seat."""
    game = _game_drawn_by("en", rounds=2)
    assert game.submit_guess("italian", "papillon")[0] is True  # the bow tie
    game.snapshot_turn_participants({"english": "eligible", "french": "eligible", "italian": "eligible"})
    game.end_turn(3, terminal_states={"english": "active", "french": "active", "italian": "active"})
    game.start_next_turn(canvas_generation=2)
    game.current_drawer = "drawer"
    game.phase = Phase.CHOOSING_PROMPT
    game.prompt_choices = ["c-fly"]
    assert game.choose_prompt_option("drawer", 0)

    assert game.submit_guess("italian", "papillon")[0] is False
    # Not this seat's answer, but the French one: kept out of the room, and
    # not because it is near the Italian "farfalla".
    assert game.guess_hint("italian", "papillon") == "close"
    assert game.submit_guess("italian", "farfalla")[0] is True


def test_what_the_whole_room_reads_carries_every_spelling():
    from app.presenters import turn_ended_payload
    from app.rooms import DrawingRecapEntry, RoomManager
    from app.services.game_highlights import build_game_highlights

    manager = RoomManager()
    room = manager.create_room("Room", prompt_language="mul")
    for token in ("drawer", "english", "french", "italian"):
        player = manager.add_player(room, token.title())
        room.players[token] = room.players.pop(player.id)
        room.players[token].id = token
    game = _game_drawn_by("de")
    room.game = game
    game.snapshot_turn_participants({"english": "eligible", "french": "eligible", "italian": "eligible"})
    game.submit_guess("english", "bow tie")
    game.end_turn(3, terminal_states={"english": "active", "french": "active", "italian": "active"})

    ended = turn_ended_payload(room)
    assert ended["prompt"] == "Fliege"
    assert ended["prompts"]["fr"] == "nœud papillon"
    entry = DrawingRecapEntry(
        turn_id="t", round_number=1, turn_number=1, drawer_id="drawer",
        drawer_nickname="Drawer", drawer_name_color=None, prompt=game.prompt or "",
        action_count=0, canvas_history=None,
        prompts=tuple(sorted(game.prompt_spellings().items())),
    )
    assert entry.metadata(0)["prompts"]["it"] == "papillon"
    assert dict(game.completed_turns[0].chosen_prompt_spellings)["en"] == "bow tie"
    for highlight in build_game_highlights(room, game):
        if "prompt" in highlight:
            assert highlight["prompts"]["en"] == "bow tie", highlight


async def test_a_mixed_room_asks_each_language_about_collisions_and_letters(seeded):
    prompts, owner = seeded
    pinned = await prompts.authorize_selection(
        ["english_standard"], requesting_user_id=owner.id, expected_language="mul"
    )
    # Each language priced from its own lists, not one pooled tally.
    assert pinned.letter_total_by_language["de"] != pinned.letter_total_by_language["en"]
    assert pinned.letter_counts_by_language["de"] != pinned.letter_counts_by_language["en"]

    # "Hund" in no language is one answer with German Standard's dog to a
    # German seat, so the room refuses to draw from both.
    names = await prompts.create_owned(
        owner.id, name="Names", description="", language="zxx",
        prompts=(PromptListEntryInput(answer="Hund"),),
    )
    with pytest.raises(PromptListSelectionError, match="ambiguous"):
        await prompts.authorize_selection(
            ["english_standard", names.slug],
            requesting_user_id=owner.id,
            expected_language="mul",
        )


async def test_a_concept_taken_down_in_one_language_is_not_drawn(seeded):
    """Some seat could not play it; hidden prompts are never drawn (R-MOD-11)."""
    from uuid import UUID
    from sqlalchemy import select
    from app.db.models import PromptVersion

    prompts, owner = seeded
    pinned = await prompts.authorize_selection(
        ["english_standard"], requesting_user_id=owner.id, expected_language="mul"
    )
    async with prompts.factory() as session:
        async with session.begin():
            hund = await session.scalar(
                select(PromptVersion).where(
                    PromptVersion.language == "de", PromptVersion.canonical_answer == "Hund"
                )
            )
            hund.moderation_state = "hidden"
            dog_concept = hund.concept_id

    sample = await prompts.sample_mixed_prompts(list(pinned.revision_ids), limit=300)

    assert all(prompt.concept_id != str(UUID(str(dog_concept))) for prompt in sample.prompts)
    assert len(sample.prompts) == 259
    assert sample.drawable == 259


async def test_a_mixed_draw_counts_what_it_could_have_drawn(seeded):
    prompts, owner = seeded
    pinned = await prompts.authorize_selection(
        ["english_standard"], requesting_user_id=owner.id, expected_language="mul"
    )

    sample = await prompts.sample_mixed_prompts(list(pinned.revision_ids), limit=10)

    assert len(sample.prompts) == 10
    assert sample.drawable == 260


def test_a_spectator_neither_hurries_the_players_letters_nor_quiets_their_chat():
    """Only the players' spellings set the checkpoint schedule, and only the
    languages somebody plays make a near word private."""
    game = Game(
        turn_order=["drawer", "english"],
        rounds_total=1,
        prompt_language="mul",
        prompt_pool=["c-cat"],
        prompt_answers={"c-cat": "cat"},
        prompt_translations={
            "c-cat": {
                "en": PromptForm("cat", (), "v-en"),
                "fr": PromptForm("chat", (), "v-fr"),
                "de": PromptForm("Katze", (), "v-de"),
                "nl": PromptForm("kat", (), "v-nl"),
                "pt": PromptForm("gato", (), "v-pt"),
                "it": PromptForm("gatto", (), "v-it"),
                "es": PromptForm("gato", (), "v-es"),
            }
        },
        seat_languages={"drawer": "en", "english": "en", "watcher": "de"},
        hint_mode="checkpoints",
    )
    game.start_next_turn(canvas_generation=1)
    assert game.choose_prompt_option("drawer", 0)

    # "cat" alone has 3 slots, a share of 1; a German spectator's five-letter
    # "Katze" would make the schedule 2.
    from app.game import _checkpoint_share

    assert game.max_hint_checkpoints() == _checkpoint_share(3)
    # "what" is near French "chat", and nobody here plays French.
    assert game.guess_hint("english", "what") is None
    # Still revealed to the spectator, up to its own share.
    game.reveal_hint_letter()
    assert game.masked_prompt("watcher").count("_") < 5
