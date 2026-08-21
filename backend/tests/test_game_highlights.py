"""Picking the moments worth showing from a finished game."""
from __future__ import annotations

from app.game import CompletedTurnStats, Game, TurnGuessRecord
from app.rooms import RoomManager
from app.services.game_highlights import build_game_highlights


def build(*seats: tuple[str, bool]):
    """Seats given as (nickname, is_spectator)."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Studio", is_public=True, rounds=2)
    players = {}
    for nickname, is_spectator in seats:
        player = room_manager.add_player(
            room, nickname, user_id=f"u-{nickname}", is_spectator=is_spectator
        )
        players[nickname] = player
    game = Game(
        turn_order=[p.id for p in room.player_list() if not p.is_spectator],
        rounds_total=2,
    )
    room.game = game
    return room_manager, room, players, game


def turn(
    drawer_id: str,
    *,
    number: int = 1,
    prompt: str = "jackpot",
    correct: int = 0,
    total: int = 0,
    guesses: tuple[TurnGuessRecord, ...] = (),
) -> CompletedTurnStats:
    return CompletedTurnStats(
        round_number=1,
        turn_number=number,
        offered_prompts=["a", "b", "c"],
        chosen_prompt=prompt,
        correct_guess_count=correct,
        total_guesser_count=total,
        drawer_token=drawer_id,
        duration_seconds=30.0,
        guesses=guesses,
    )


def guess(token: str, seconds: float) -> TurnGuessRecord:
    return TurnGuessRecord(
        token=token, points_awarded=100, guess_time_seconds=seconds
    )


def kinds(highlights: list[dict]) -> set[str]:
    return {h["kind"] for h in highlights}


def only(highlights: list[dict], kind: str) -> dict:
    matches = [h for h in highlights if h["kind"] == kind]
    assert len(matches) == 1, f"expected one {kind}, got {len(matches)}"
    return matches[0]


def test_no_completed_turns_produces_no_highlights():
    _, room, _, game = build(("Ana", False), ("Bo", False))
    assert build_game_highlights(room, game) == []


def test_hardest_prompt_is_the_lowest_share_of_its_guessers():
    _, room, players, game = build(("Ana", False), ("Bo", False))
    game.completed_turns = [
        turn(players["Ana"].id, number=1, prompt="cat", correct=3, total=3),
        turn(players["Bo"].id, number=2, prompt="roller coaster", correct=1, total=4),
    ]
    hardest = only(build_game_highlights(room, game), "hardest_prompt")
    assert hardest["prompt"] == "roller coaster"
    assert hardest["correctGuessCount"] == 1
    assert hardest["totalGuesserCount"] == 4


def test_turns_with_no_eligible_guessers_are_not_the_hardest():
    """A turn nobody could have guessed is empty, not hard."""
    _, room, players, game = build(("Ana", False), ("Bo", False))
    game.completed_turns = [
        turn(players["Ana"].id, number=1, prompt="nobody home", correct=0, total=0),
        turn(players["Bo"].id, number=2, prompt="cat", correct=2, total=4),
    ]
    assert only(build_game_highlights(room, game), "hardest_prompt")["prompt"] == "cat"


def test_hardest_prompt_ties_break_on_fewer_correct_then_earlier_turn():
    _, room, players, game = build(("Ana", False), ("Bo", False))
    game.completed_turns = [
        turn(players["Ana"].id, number=1, prompt="half of four", correct=2, total=4),
        turn(players["Bo"].id, number=2, prompt="half of two", correct=1, total=2),
    ]
    # Same 0.5 ratio; the one that fewer players actually got wins.
    assert (
        only(build_game_highlights(room, game), "hardest_prompt")["prompt"]
        == "half of two"
    )


def test_no_hardest_prompt_when_everyone_got_everything():
    """Nothing was hard, so naming one prompt would invent a difficulty."""
    _, room, players, game = build(("Ana", False), ("Bo", False))
    game.completed_turns = [
        turn(players["Ana"].id, number=1, prompt="cat", correct=3, total=3),
        turn(players["Bo"].id, number=2, prompt="dog", correct=3, total=3),
    ]
    assert "hardest_prompt" not in kinds(build_game_highlights(room, game))


def test_fastest_guess_names_the_player_and_the_prompt():
    _, room, players, game = build(("Ana", False), ("Bo", False))
    game.completed_turns = [
        turn(
            players["Ana"].id,
            number=1,
            prompt="cat",
            correct=1,
            total=2,
            guesses=(guess(players["Bo"].id, 9.5),),
        ),
        turn(
            players["Bo"].id,
            number=2,
            prompt="dog",
            correct=1,
            total=2,
            guesses=(guess(players["Ana"].id, 2.25),),
        ),
    ]
    fastest = only(build_game_highlights(room, game), "fastest_guess")
    assert fastest["nickname"] == "Ana"
    assert fastest["prompt"] == "dog"
    assert fastest["seconds"] == 2.25


def test_no_correct_guesses_produces_no_guess_highlights():
    _, room, players, game = build(("Ana", False), ("Bo", False))
    game.completed_turns = [
        turn(players["Ana"].id, number=1, correct=0, total=2),
        turn(players["Bo"].id, number=2, correct=0, total=2),
    ]
    assert kinds(build_game_highlights(room, game)) == {"hardest_prompt"}


def test_best_drawer_needs_someone_to_be_better_than():
    """One qualifying drawer is not the best of anything."""
    _, room, players, game = build(("Ana", False), ("Bo", False))
    game.completed_turns = [turn(players["Ana"].id, number=1, correct=2, total=2)]
    assert "best_drawer" not in kinds(build_game_highlights(room, game))


def test_best_drawer_is_the_highest_average_share_of_guessers():
    _, room, players, game = build(("Ana", False), ("Bo", False))
    game.completed_turns = [
        turn(players["Ana"].id, number=1, correct=4, total=4),
        turn(players["Bo"].id, number=2, correct=1, total=4),
    ]
    best = only(build_game_highlights(room, game), "best_drawer")
    assert best["nickname"] == "Ana"
    assert best["guessRatio"] == 1.0


def test_quickest_on_average_ignores_a_player_with_a_single_guess():
    """An average over one guess is that guess, and would win on luck."""
    _, room, players, game = build(
        ("Ana", False), ("Bo", False), ("Cy", False), ("Dee", False)
    )
    ana, bo = players["Ana"].id, players["Bo"].id
    cy, dee = players["Cy"].id, players["Dee"].id
    game.completed_turns = [
        turn(
            ana,
            number=1,
            correct=3,
            total=3,
            guesses=(guess(bo, 8.0), guess(cy, 1.0), guess(dee, 0.5)),
        ),
        turn(bo, number=2, correct=1, total=3, guesses=(guess(cy, 20.0),)),
        turn(cy, number=3, correct=1, total=3, guesses=(guess(bo, 8.0),)),
    ]
    # Dee guessed once, fastest of anyone, and is excluded for it. Cy has the
    # fastest guess of those who qualify but averages 10.5 over two; Bo averages 8.
    quickest = only(build_game_highlights(room, game), "quickest_average")
    assert quickest["nickname"] == "Bo"
    assert quickest["seconds"] == 8.0


def test_quickest_on_average_needs_two_players_to_rank():
    _, room, players, game = build(("Ana", False), ("Bo", False))
    ana, bo = players["Ana"].id, players["Bo"].id
    game.completed_turns = [
        turn(ana, number=1, correct=1, total=1, guesses=(guess(bo, 4.0),)),
        turn(ana, number=2, correct=1, total=1, guesses=(guess(bo, 6.0),)),
    ]
    assert "quickest_average" not in kinds(build_game_highlights(room, game))


def test_a_player_who_left_is_still_named():
    """Their seat is gone from the room, but they still played the game."""
    room_manager, room, players, game = build(("Ana", False), ("Bo", False))
    ana, bo = players["Ana"].id, players["Bo"].id
    game.completed_turns = [
        turn(bo, number=1, prompt="cat", correct=1, total=2, guesses=(guess(ana, 1.5),))
    ]
    room_manager.remove_player(room, ana)

    fastest = only(build_game_highlights(room, game), "fastest_guess")
    assert fastest["nickname"] == "Ana"
    assert fastest["nameColor"] == players["Ana"].name_color
    assert fastest["isAnonymous"] == players["Ana"].is_anonymous


def test_every_highlight_carries_the_fields_a_name_renders_from():
    _, room, players, game = build(("Ana", False), ("Bo", False))
    ana, bo = players["Ana"].id, players["Bo"].id
    game.completed_turns = [
        turn(ana, number=1, correct=1, total=2, guesses=(guess(bo, 3.0),)),
        turn(ana, number=2, correct=1, total=2, guesses=(guess(bo, 5.0),)),
        turn(bo, number=3, correct=2, total=2, guesses=(guess(ana, 4.0), guess(ana, 6.0))),
    ]
    highlights = build_game_highlights(room, game)
    for highlight in highlights:
        if highlight["kind"] == "hardest_prompt":
            continue
        assert set(highlight) >= {"nickname", "nameColor", "isAnonymous"}
