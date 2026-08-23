"""Mapping a finished game onto the rows that record it."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.domain_values import DRAWING_UNAVAILABLE_RECAP_BUDGET
from app.game import CompletedTurnStats, Game, TurnGuessRecord
from app.identifiers import generate_uuid7
from app.rooms import DrawingRecapEntry, RoomManager
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
    drawer_id: str, *, number: int = 1, guesses=(), present=(), turn_id=None
) -> CompletedTurnStats:
    return CompletedTurnStats(
        # A real turn always carries the id allocated when it started, and the
        # drawing is matched to it by that id, so the default mirrors the game
        # rather than leaving the builder to mint a replacement.
        id=turn_id or str(generate_uuid7()),
        round_number=1,
        turn_number=number,
        offered_prompts=["jackpot", "b", "c"],
        chosen_prompt="jackpot",
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
    assert history.record.id == game.id
    assert UUID(history.record.id).version == 7


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


def test_guess_ids_follow_the_turns_actually_written():
    _, room, players, game = build(
        ("Ann", "user-ann", 300, False),
        ("Bob", "user-bob", 100, False),
        ("Cid", None, 50, False),
    )
    # Cid has no account, but their factual seat and the surrounding turn links
    # remain complete.
    game.completed_turns = [
        turn(players["Ann"].id, number=1, guesses=[(players["Bob"].id, 200, 3.0)]),
        turn(players["Cid"].id, number=2, guesses=[(players["Ann"].id, 150, 8.0)]),
        turn(players["Bob"].id, number=3, guesses=[(players["Ann"].id, 250, 2.0)]),
    ]

    history = build_game_history(room, game, finished_at=FINISHED_AT)

    assert [r.turn_number for r in history.turns] == [1, 2, 3]
    assert [(g.turn_id, g.user_id) for g in history.guesses] == [
        (history.turns[0].id, "user-bob"),
        (history.turns[1].id, "user-ann"),
        (history.turns[2].id, "user-ann"),
    ]
    cid = next(participant for participant in history.participants if participant.user_id is None)
    assert cid.display_name == "Cid"
    assert history.turns[1].drawer_seat_id == cid.seat_id


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
    # Their earlier seat still drew a turn, and that turn is still theirs.
    assert history.turns[0].drawer_user_id == "user-ann"


def test_record_carries_the_settings_the_game_was_played_under():
    _, room, players, game = build(
        ("Ann", "user-ann", 300, False),
        ("Bob", "user-bob", 100, False),
    )
    game.scoring_mode = "pressure"
    game.hint_mode = "wheel"
    game.drawing_seconds = 120
    game.allowed_tools = ("brush", "shapes")
    game.color_mode = "black_and_white"
    game.prompt_language = "de"
    game.hide_masked_prompt = True
    game.prompt_source_revision_ids = ("revision-one", "revision-two")
    game.prompt_pool = ["jackpot", "b", "c"]
    game.prompt_version_ids = {
        "jackpot": "version-jackpot",
        "b": "version-b",
        "c": "version-c",
    }
    game.prompt_source_revision_ids_by_answer = {
        "jackpot": ("revision-one",),
        "b": ("revision-one", "revision-two"),
        "c": ("revision-two",),
    }
    game.completed_turns = [turn(players["Ann"].id)]

    history = build_game_history(room, game, finished_at=FINISHED_AT)

    assert history.record.room_name == "Studio"
    assert history.record.total_rounds == 2
    assert history.record.started_at == game.started_at
    assert history.record.finished_at == FINISHED_AT
    assert history.record.scoring_version == 1
    assert history.record.rule_snapshot_version == 1
    assert history.record.rule_snapshot["scoring"]["mode"] == "pressure"
    assert history.record.rule_snapshot["scoring"]["pressure"] == {
        "maximumGuessPoints": 300,
        "minimumGuessPoints": 50,
        "decayPerReferenceSecond": 0.98,
        "referenceSeconds": 90.0,
        "postGuessMultiplier": 2.0,
    }
    assert history.record.rule_snapshot["drawing"] == {
        "seconds": 120,
        "allowedTools": ["brush", "shapes"],
        "colorMode": "black_and_white",
        "allowedColors": ["#000000", "#ffffff"],
    }
    assert history.record.rule_snapshot["prompt"] == {
        "language": "de",
        "hideMaskedPrompt": True,
        "sourceRevisionIds": ["revision-one", "revision-two"],
    }
    assert history.record.prompt_source_mode == "curated"
    assert history.record.prompt_source_revision_ids == (
        "revision-one",
        "revision-two",
    )
    assert [offer.prompt for offer in history.turns[0].prompt_offers] == [
        "jackpot",
        "b",
        "c",
    ]
    assert [offer.selected for offer in history.turns[0].prompt_offers] == [
        True,
        False,
        False,
    ]
    assert history.turns[0].prompt_version_id == "version-jackpot"
    assert history.turns[0].prompt_source_kind == "curated"
    assert history.turns[0].prompt_offers[1].source_revision_ids == (
        "revision-one",
        "revision-two",
    )
    assert history.turns[0].duration_seconds == 42.5


def test_actual_pool_distinguishes_custom_curated_and_fallback_offers():
    _, room, players, game = build(
        ("Ann", "user-ann", 300, False),
        ("Bob", "user-bob", 100, False),
    )
    game.prompt_pool = ["jackpot", "b", "c"]
    game.custom_prompt_keys = frozenset({"jackpot"})
    game.prompt_version_ids = {"b": "version-b"}
    game.prompt_source_revision_ids = ("revision-curated",)
    game.prompt_source_revision_ids_by_answer = {
        "b": ("revision-curated",)
    }
    game.completed_turns = [turn(players["Ann"].id)]

    history = build_game_history(room, game, finished_at=FINISHED_AT)

    assert history.record.prompt_source_mode == "mixed"
    assert [offer.source_kind for offer in history.turns[0].prompt_offers] == [
        "custom",
        "curated",
        "builtin_fallback",
    ]
    assert history.turns[0].prompt_offers[0].prompt_version_id is None
    assert history.turns[0].prompt_version_id is None
    assert history.turns[0].prompt_source_kind == "custom"
    assert history.turns[0].prompt_offers[1].prompt_version_id == "version-b"
    assert history.turns[0].prompt_offers[2].source_revision_ids == ()


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
            offered_prompts=["a", "b", "c"],
            chosen_prompt="jackpot",
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
            prompt_auto_picked=True,
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
    assert turn_record.prompt_auto_picked is True
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


def recap(room, completed, *, canvas: bytes | None = b"SKCH-bytes"):
    room.last_game_drawings.append(
        DrawingRecapEntry(
            turn_id=completed.id,
            round_number=completed.round_number,
            turn_number=completed.turn_number,
            drawer_id=completed.drawer_token,
            drawer_nickname="Drawer",
            drawer_name_color=None,
            prompt=completed.chosen_prompt,
            action_count=3,
            canvas_history=canvas,
        )
    )


def test_a_drawing_follows_its_turn_by_id_not_by_position():
    _, room, players, game = build(
        ("Ann", "user-ann", 300, False),
        ("Bob", "user-bob", 100, False),
    )
    first = turn(players["Ann"].id, number=1)
    second = turn(players["Bob"].id, number=2)
    game.completed_turns = [first, second]
    # Recorded out of order on purpose: nothing may depend on the list order.
    recap(room, second, canvas=b"second")
    recap(room, first, canvas=b"first")

    history = build_game_history(room, game, finished_at=FINISHED_AT)

    by_turn = {d.turn_id: d.payload for d in history.drawings}
    assert by_turn[first.id] == b"first"
    assert by_turn[second.id] == b"second"


def test_a_turn_the_history_skips_takes_its_drawing_with_it():
    """A spectator-only drawer has no factual seat, so neither turn nor drawing lands."""

    _, room, players, game = build(
        ("Ann", "user-ann", 300, False),
        ("Bob", "user-bob", 100, False),
        ("Cid", "user-cid", 0, True),
    )
    kept = turn(players["Ann"].id, number=1)
    skipped = turn(players["Cid"].id, number=2)
    game.completed_turns = [kept, skipped]
    recap(room, kept)
    recap(room, skipped)

    history = build_game_history(room, game, finished_at=FINISHED_AT)

    assert [d.turn_id for d in history.drawings] == [kept.id]
    assert {t.id for t in history.turns} == {kept.id}


def test_a_drawing_dropped_for_budget_is_recorded_as_unavailable():
    _, room, players, game = build(
        ("Ann", "user-ann", 300, False),
        ("Bob", "user-bob", 100, False),
    )
    dropped = turn(players["Ann"].id)
    game.completed_turns = [dropped]
    recap(room, dropped, canvas=None)

    history = build_game_history(room, game, finished_at=FINISHED_AT)

    assert len(history.drawings) == 1
    assert history.drawings[0].payload is None
    assert history.drawings[0].unavailable_reason == DRAWING_UNAVAILABLE_RECAP_BUDGET


def test_a_game_with_no_recap_records_no_drawings():
    _, room, players, game = build(
        ("Ann", "user-ann", 300, False),
        ("Bob", "user-bob", 100, False),
    )
    game.completed_turns = [turn(players["Ann"].id)]

    history = build_game_history(room, game, finished_at=FINISHED_AT)

    assert history.drawings == []
