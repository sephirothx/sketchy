"""Places, and what a tie does to them."""
from __future__ import annotations

from app.game import Game, competition_ranks
from app.presenters import turn_ended_payload
from app.rooms import RoomManager


def test_distinct_scores_count_up_from_one():
    assert competition_ranks([300, 200, 100]) == [1, 2, 3]


def test_tied_scores_share_the_higher_place():
    assert competition_ranks([300, 300, 100]) == [1, 1, 3]


def test_the_places_a_tie_crowds_out_are_skipped():
    """1, 2, 2, 4 - never 1, 2, 2, 3."""
    assert competition_ranks([300, 200, 200, 100]) == [1, 2, 2, 4]
    assert competition_ranks([300, 300, 300, 100]) == [1, 1, 1, 4]


def test_everyone_level_is_everyone_first():
    assert competition_ranks([0, 0, 0]) == [1, 1, 1]


def test_no_scores_no_places():
    assert competition_ranks([]) == []


def build_room(*seats: tuple[str, int]):
    room_manager = RoomManager()
    room = room_manager.create_room(name="Studio", is_public=True, rounds=1)
    players = {}
    for nickname, score in seats:
        player = room_manager.add_player(room, nickname, user_id=f"u-{nickname}")
        player.score = score
        players[nickname] = player
    room.game = Game(
        turn_order=[p.id for p in room.player_list()], rounds_total=1
    )
    return room, players


def test_turn_results_give_tied_players_the_same_place():
    """The screen after every turn, where a tie is most likely to show up."""
    room, players = build_room(("Ann", 300), ("Bob", 300), ("Cid", 100))
    room.game.current_drawer = players["Cid"].id

    ranks = {
        entry["nickname"]: entry["newRank"]
        for entry in turn_ended_payload(room, drawer_bonus=0)["scores"]
    }

    assert ranks == {"Ann": 1, "Bob": 1, "Cid": 3}


def test_a_tie_broken_by_the_turn_shows_as_a_place_gained():
    """Both were first; one pulls ahead, so the other genuinely drops to second."""
    room, players = build_room(("Ann", 400), ("Bob", 300))
    room.game.current_drawer = players["Bob"].id
    # Ann guessed this turn and took the lead with it.
    room.game.guess_points = {players["Ann"].id: 100}

    entries = {
        entry["nickname"]: entry
        for entry in turn_ended_payload(room, drawer_bonus=0)["scores"]
    }

    assert entries["Ann"]["previousRank"] == 1
    assert entries["Bob"]["previousRank"] == 1
    assert entries["Ann"]["newRank"] == 1
    assert entries["Bob"]["newRank"] == 2
