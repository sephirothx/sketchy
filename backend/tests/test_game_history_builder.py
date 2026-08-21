"""Mapping a finished game onto the rows that record it."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.game import CompletedTurnStats, Game, TurnGuessRecord
from app.rooms import RoomManager
from app.services.game_history import build_game_history

FINISHED_AT = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def build(*seats: tuple[str, str | None, int, bool]):
    """Seats given as (nickname, user_id, score, is_spectator)."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Studio", is_public=True, rounds=2)
    players = {}
    for nickname, user_id, score, is_spectator in seats:
        player = room_manager.add_player(
            room, nickname, user_id=user_id, is_spectator=is_spectator
        )
        player.score = score
        players[nickname] = player
    game = Game(
        turn_order=[p.id for p in room.player_list() if not p.is_spectator],
        rounds_total=2,
    )
    game.started_at = FINISHED_AT - timedelta(minutes=5)
    room.game = game
    return room_manager, room, players, game


def turn(
    drawer_id: str, *, number: int = 1, guesses=(), present=()
) -> CompletedTurnStats:
    return CompletedTurnStats(
        round_number=1,
        turn_number=number,
        offered_words=["a", "b", "c"],
        chosen_word="jackpot",
        correct_guess_count=len(guesses),
        total_guesser_count=len(guesses),
        drawer_token=drawer_id,
        duration_seconds=42.5,
        guesses=tuple(
            TurnGuessRecord(token=token, points_awarded=points, guess_time_seconds=t)
            for token, points, t in guesses
        ),
        present_tokens=tuple(present),
    )


def test_tied_scores_share_a_rank_so_both_count_as_wins():
    _, room, players, game = build(
        ("Ann", "user-ann", 300, False),
        ("Bob", "user-bob", 300, False),
        ("Cid", "user-cid", 100, False),
    )
    game.completed_turns = [turn(players["Ann"].id)]

    history = build_game_history(room, game, finished_at=FINISHED_AT)

    ranks = {p.user_id: p.final_rank for p in history.participants}
    assert ranks == {"user-ann": 1, "user-bob": 1, "user-cid": 3}


def test_spectators_are_left_out_of_the_standings():
    _, room, players, game = build(
        ("Ann", "user-ann", 300, False),
        ("Bob", "user-bob", 100, False),
        ("Wat", "user-wat", 0, True),
    )
    game.completed_turns = [turn(players["Ann"].id)]

    history = build_game_history(room, game, finished_at=FINISHED_AT)

    assert {p.user_id for p in history.participants} == {"user-ann", "user-bob"}
    assert history.record.player_count == 2


def test_guess_indices_follow_the_rounds_actually_written():
    _, room, players, game = build(
        ("Ann", "user-ann", 300, False),
        ("Bob", "user-bob", 100, False),
        ("Cid", None, 50, False),
    )
    # Cid has no account, so the middle turn cannot be written at all - the
    # guesses on the turn after it must still point at the right round.
    game.completed_turns = [
        turn(players["Ann"].id, number=1, guesses=[(players["Bob"].id, 200, 3.0)]),
        turn(players["Cid"].id, number=2, guesses=[(players["Ann"].id, 150, 8.0)]),
        turn(players["Bob"].id, number=3, guesses=[(players["Ann"].id, 250, 2.0)]),
    ]

    history = build_game_history(room, game, finished_at=FINISHED_AT)

    assert [r.turn_number for r in history.turns] == [1, 3]
    assert [(g.turn_index, g.user_id) for g in history.guesses] == [
        (0, "user-bob"),
        (1, "user-ann"),
    ]


def test_a_rejoined_account_is_recorded_once():
    room_manager, room, players, game = build(
        ("Ann", "user-ann", 300, False),
        ("Bob", "user-bob", 100, False),
    )
    old_seat = players["Ann"]
    game.completed_turns = [turn(old_seat.id)]
    room_manager.remove_player(room, old_seat.id)
    rejoined = room_manager.add_player(room, "Ann", user_id="user-ann")
    rejoined.score = 420
    game.add_player_to_rotation(rejoined.id)

    history = build_game_history(room, game, finished_at=FINISHED_AT)

    ann = [p for p in history.participants if p.user_id == "user-ann"]
    assert len(ann) == 1
    # The seat they still occupy is the one whose score kept moving.
    assert ann[0].final_score == 420
    # Their earlier seat still drew a round, and that round is still theirs.
    assert history.turns[0].drawer_user_id == "user-ann"


def test_record_carries_the_settings_the_game_was_played_under():
    _, room, players, game = build(
        ("Ann", "user-ann", 300, False),
        ("Bob", "user-bob", 100, False),
    )
    game.completed_turns = [turn(players["Ann"].id)]

    history = build_game_history(room, game, finished_at=FINISHED_AT)

    assert history.record.room_name == "Studio"
    assert history.record.total_rounds == 2
    assert history.record.started_at == game.started_at
    assert history.record.finished_at == FINISHED_AT
    assert history.turns[0].duration_seconds == 42.5


def test_turn_records_carry_the_analytics_the_ui_does_not_show_yet():
    _, room, players, game = build(
        ("Ann", "user-ann", 300, False),
        ("Bob", "user-bob", 100, False),
    )
    ann, bob = players["Ann"].id, players["Bob"].id
    game.completed_turns = [
        CompletedTurnStats(
            round_number=1,
            turn_number=1,
            offered_words=["a", "b", "c"],
            chosen_word="jackpot",
            correct_guess_count=1,
            total_guesser_count=3,
            drawer_token=ann,
            duration_seconds=42.5,
            guesses=(
                TurnGuessRecord(
                    token=bob,
                    points_awarded=180,
                    guess_time_seconds=30.0,
                    hints_used=2,
                    points_spent_on_hints=36,
                    wrong_guesses_before=4,
                ),
            ),
            word_auto_picked=True,
            stroke_count=17,
            end_reason="timeout",
            wrong_guess_count=6,
            near_miss_count=2,
            present_tokens=(ann, bob),
        )
    ]

    history = build_game_history(room, game, finished_at=FINISHED_AT)

    turn_record = history.turns[0]
    assert turn_record.guesser_count == 3
    assert turn_record.word_auto_picked is True
    assert turn_record.stroke_count == 17
    assert turn_record.end_reason == "timeout"
    assert turn_record.wrong_guess_count == 6
    assert turn_record.near_miss_count == 2

    guess = history.guesses[0]
    assert guess.hints_used == 2
    assert guess.points_spent_on_hints == 36
    assert guess.wrong_guesses_before == 4


def test_turns_played_separates_a_walkout_from_a_full_game():
    room_manager, room, players, game = build(
        ("Ann", "user-ann", 300, False),
        ("Bob", "user-bob", 100, False),
    )
    ann, bob = players["Ann"].id, players["Bob"].id
    # Bob is in the rotation for the first turn only, then leaves.
    game.completed_turns = [
        turn(ann, number=1, present=(ann, bob)),
        turn(ann, number=2, present=(ann,)),
    ]
    room_manager.remove_player(room, bob)

    history = build_game_history(room, game, finished_at=FINISHED_AT)

    played = {p.user_id: p.turns_played for p in history.participants}
    assert played == {"user-ann": 2, "user-bob": 1}
