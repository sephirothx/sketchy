import pytest
from uuid import UUID

from app.canvas_history import (
    ClearAction,
    FillAction,
    PathAction,
    decode_binary_canvas_history,
)
from app.game import (
    CLOSE_GUESS_MAX_DISTANCE,
    DRAWING_SECONDS,
    HINT_BASE_COST,
    MAX_GUESS_POINTS,
    MAX_HINT_SPEND,
    MIN_GUESS_POINTS,
    PRESSURE_MAX_POINTS,
    PRESSURE_MIN_POINTS,
    PRESSURE_MULTIPLIER,
    Game,
    Phase,
    _bounded_damerau_levenshtein,
)
from app.rooms import DRAWING_TIME_OPTIONS
from app.canvas_session import MAX_CANVAS_COMMITS
from app.prompts import MAX_PROMPT_LENGTH


def make_game(n_players=3, rounds=2):
    tokens = [f"p{i}" for i in range(n_players)]
    return Game(turn_order=tokens, rounds_total=rounds)


def pen_start(x=0, y=0):
    return {"x": x, "y": y, "color": "#000000", "width": 4}


def shape_payload(shape="rectangle"):
    return {
        "shape": shape,
        "from": {"x": 0.1, "y": 0.2},
        "to": {"x": 0.8, "y": 0.9},
        "color": "#000000",
        "width": 4,
    }


def test_start_next_turn_rotates_drawer():
    game = make_game(n_players=3, rounds=2)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    first_turn_id = game.current_turn_id
    assert first_turn_id is not None
    assert UUID(first_turn_id).version == 7
    assert game.current_drawer == "p0"
    game.choose_prompt(game.current_drawer, game.prompt_choices[0])
    game.end_turn()
    assert game.completed_turns[0].id == first_turn_id
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    assert game.current_turn_id != first_turn_id
    assert UUID(game.current_turn_id).version == 7
    assert game.current_drawer == "p1"


def test_total_turns_and_finished():
    game = make_game(n_players=3, rounds=2)
    assert game.total_turns == 6
    for _ in range(6):
        game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    assert game.is_finished() is True


def test_adding_player_mid_round_preserves_current_and_next_drawer():
    game = make_game(n_players=3, rounds=2)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    assert game.current_drawer == "p1"

    game.add_player_to_rotation("late")

    assert game.current_drawer == "p1"
    assert game.round_number == 1
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    assert game.current_drawer == "p2"


def test_removing_non_drawer_preserves_current_and_next_drawer():
    game = make_game(n_players=3, rounds=2)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    assert game.current_drawer == "p1"

    assert game.remove_player_from_rotation("p0") is False

    assert game.current_drawer == "p1"
    assert game.round_number == 1
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    assert game.current_drawer == "p2"


def test_removing_drawer_positions_cursor_before_next_survivor():
    game = make_game(n_players=3, rounds=2)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    assert game.current_drawer == "p1"

    assert game.remove_player_from_rotation("p1") is True
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)

    assert game.current_drawer == "p2"
    assert game.round_number == 1


def _play_with_churn(n_players, rounds, max_players, script):
    """Play a game to completion, applying `script`'s joins and leaves.

    `script` maps a turn number to the actions taken right after that turn:
    ``"join"`` seats a newcomer, ``"rm:<token>"`` removes one. Returns the
    number of turns actually started and the prompts they consumed.
    """
    game = Game(
        turn_order=[f"p{i}" for i in range(n_players)],
        rounds_total=rounds,
        max_players=max_players,
    )
    turns = 0
    prompts = 0
    joined = 0
    while not game.is_finished() and turns < 200:
        prompts += len(
            game.start_next_turn(canvas_generation=game.canvas.generation + 1)
        )
        turns += 1
        for action in script.get(turns, ()):
            if action == "join" and len(game.turn_order) < max_players:
                joined += 1
                game.add_player_to_rotation(f"n{joined}")
            elif action.startswith("rm:"):
                token = action[3:]
                if token in game.turn_order and len(game.turn_order) > 1:
                    game.remove_player_from_rotation(token)
    return turns, prompts


def test_churn_cannot_push_a_game_past_its_advertised_length():
    """`turn_index` is re-based, not incremented, when the roster changes.

    Those re-bases can move it backwards, replaying turn slots and letting a
    room with mid-game churn run longer than the `rounds x max_players` it
    advertised. The prompt sample is sized off that product, so it has to be a
    ceiling rather than an estimate.
    """
    # A join, a departure, then another join: enough to replay a slot.
    turns, prompts = _play_with_churn(
        n_players=3,
        rounds=2,
        max_players=4,
        script={1: ("join",), 2: ("rm:p0",), 3: ("join",)},
    )

    assert turns <= 2 * 4
    assert prompts <= 2 * 4 * 3


def test_turn_ceiling_does_not_cut_a_game_without_churn():
    """The ceiling is a backstop, not a shortener: a quiet game is unaffected."""
    turns, prompts = _play_with_churn(
        n_players=4, rounds=2, max_players=4, script={}
    )

    assert turns == 8
    assert prompts == 24


def test_choose_prompt_rejects_wrong_player():
    game = make_game()
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    other_player = "p1"
    assert game.choose_prompt(other_player, game.prompt_choices[0]) is False
    assert game.phase == Phase.CHOOSING_PROMPT


def test_choose_prompt_rejects_invalid_prompt():
    game = make_game()
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    assert game.choose_prompt(game.current_drawer, "not-a-choice") is False


def test_force_word_choice_picks_first_option():
    game = make_game()
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    first_choice = game.prompt_choices[0]
    game.force_prompt_choice()
    assert game.prompt == first_choice
    assert game.phase == Phase.DRAWING


def test_masked_word_reveals_length_only():
    game = make_game()
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.choose_prompt(game.current_drawer, game.prompt_choices[0])
    prompt = game.prompt
    expected = "_" * len(prompt) + f"  {len(prompt)}"
    assert game.masked_prompt() == expected


def test_masked_word_shows_spaces_and_special_characters():
    game = make_game(n_players=1, rounds=1)
    game.prompt_pool = ["red panda"]
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.force_prompt_choice()
    assert game.masked_prompt() == "___  _____  3 5"

    game2 = make_game(n_players=1, rounds=1)
    game2.prompt_pool = ["spider-man"]
    game2.start_next_turn(canvas_generation=game2.canvas.generation + 1)
    game2.force_prompt_choice()
    assert game2.masked_prompt() == "______-___  6 3"


def test_submit_guess_correct_awards_points_and_ignores_drawer():
    game = make_game(n_players=3)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.choose_prompt(game.current_drawer, game.prompt_choices[0])
    game.set_phase_deadline(DRAWING_SECONDS)

    drawer_correct, drawer_points = game.submit_guess(game.current_drawer, game.prompt)
    assert drawer_correct is False
    assert drawer_points == 0

    guesser = "p1" if game.current_drawer != "p1" else "p2"
    correct, points = game.submit_guess(guesser, game.prompt.upper())
    assert correct is True
    assert points > 0
    # Guessing again should not award points twice.
    correct_again, points_again = game.submit_guess(guesser, game.prompt)
    assert correct_again is False
    assert points_again == 0


def test_submit_guess_ignores_canonically_decomposable_diacritics():
    cases = (
        ("il tempo è denaro", "il tempo e denaro"),
        ("cafe", "CAFÉ"),
        ("cafe\u0301", "  CAFE  "),
    )
    for answer, guess in cases:
        game = Game(turn_order=["drawer", "guesser"], prompt_pool=[answer])
        game.start_next_turn(canvas_generation=game.canvas.generation + 1)
        game.force_prompt_choice()
        game.set_phase_deadline(DRAWING_SECONDS)

        correct, points = game.submit_guess("guesser", guess)

        assert correct is True
        assert points > 0


def test_submit_guess_keeps_letters_without_canonical_ascii_decomposition_distinct():
    cases = (
        ("smørrebrød", "smorrebrod"),
        ("łódź", "lodz"),
    )
    for answer, guess in cases:
        game = Game(turn_order=["drawer", "guesser"], prompt_pool=[answer])
        game.start_next_turn(canvas_generation=game.canvas.generation + 1)
        game.force_prompt_choice()

        correct, points = game.submit_guess("guesser", guess)

        assert correct is False
        assert points == 0


def test_submit_guess_records_elapsed_guess_time():
    game = make_game(n_players=2)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.choose_prompt(game.current_drawer, game.prompt_choices[0])
    game.remaining_seconds = lambda: DRAWING_SECONDS - 12.5
    guesser = next(token for token in game.turn_order if token != game.current_drawer)

    correct, _ = game.submit_guess(guesser, game.prompt)

    assert correct is True
    assert game.guess_times[guesser] == 12.5


def test_submit_guess_wrong_word():
    game = make_game()
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.choose_prompt(game.current_drawer, game.prompt_choices[0])
    game.set_phase_deadline(DRAWING_SECONDS)
    correct, points = game.submit_guess("p1", "definitely-wrong")
    assert correct is False
    assert points == 0


def test_no_scoring_marks_correct_guesses_without_awarding_points():
    game = Game(turn_order=["drawer", "guesser"], scoring_mode="none")
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.choose_prompt(game.current_drawer, game.prompt_choices[0])
    game.set_phase_deadline(DRAWING_SECONDS)

    correct, points = game.submit_guess("guesser", game.prompt)

    assert correct is True
    assert points == 0
    assert game.guess_points == {"guesser": 0}
    assert game.end_turn() == 0


def test_end_turn_awards_drawer_bonus_per_guesser():
    game = make_game(n_players=3)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.choose_prompt(game.current_drawer, game.prompt_choices[0])
    game.set_phase_deadline(DRAWING_SECONDS)
    others = [t for t in game.turn_order if t != game.current_drawer]
    for token in others:
        game.submit_guess(token, game.prompt)
    bonus = game.end_turn()
    assert bonus == 300 * len(others)
    assert game.phase == Phase.TURN_RESULTS


def test_end_turn_is_idempotent():
    game = make_game(n_players=3)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.choose_prompt(game.current_drawer, game.prompt_choices[0])
    game.set_phase_deadline(DRAWING_SECONDS)
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    game.submit_guess(guesser, game.prompt)

    assert game.end_turn() is not None
    assert game.end_turn() is None


def test_end_turn_bonus_shrinks_when_drawer_stalls_before_drawing():
    """A drawer who delays drawing (eating into the shared deadline) should earn a
    smaller bonus, not the same flat amount - otherwise stalling with an easy prompt
    to suppress guessers' scores would be free for the drawer."""
    game = make_game(n_players=3)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.choose_prompt(game.current_drawer, game.prompt_choices[0])
    others = [t for t in game.turn_order if t != game.current_drawer]

    # Simulate stalling: only 1 second remains by the time guesses come in.
    game.set_phase_deadline(1)
    for token in others:
        game.submit_guess(token, game.prompt)
    stalled_bonus = game.end_turn()

    # Compare against drawing immediately (full time remaining for guesses).
    game2 = make_game(n_players=3)
    game2.start_next_turn(canvas_generation=game2.canvas.generation + 1)
    game2.choose_prompt(game2.current_drawer, game2.prompt_choices[0])
    others2 = [t for t in game2.turn_order if t != game2.current_drawer]
    game2.set_phase_deadline(DRAWING_SECONDS)
    for token in others2:
        game2.submit_guess(token, game2.prompt)
    prompt_bonus = game2.end_turn()

    assert stalled_bonus < prompt_bonus


def test_all_guessed():
    game = make_game(n_players=3)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.choose_prompt(game.current_drawer, game.prompt_choices[0])
    others = [t for t in game.turn_order if t != game.current_drawer]
    assert game.all_guessed(len(others)) is False
    for token in others:
        game.submit_guess(token, game.prompt)
    assert game.all_guessed(len(others)) is True


def test_undo_last_stroke_with_no_strokes():
    game = make_game()
    assert game.canvas.undo_last_stroke() is False


def test_canvas_revision_advances_only_for_semantic_history_changes():
    game = make_game()
    assert game.canvas.revision == 0

    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    assert game.canvas.revision == 1

    assert game.canvas.record_stroke("draw_start", pen_start()) is True
    assert game.canvas.revision == 2
    assert game.canvas.record_stroke(
        "draw_move",
        {"points": [{"x": 0.1, "y": 0.1}]},
    ) is True
    assert game.canvas.record_stroke("draw_end", {}) is True
    assert game.canvas.revision == 2

    assert game.canvas.record_stroke("draw_shape", shape_payload()) is True
    assert game.canvas.revision == 3
    assert game.canvas.clear_canvas_stroke() is True
    assert game.canvas.revision == 4
    assert game.canvas.undo_last_stroke() is True
    assert game.canvas.revision == 5
    assert game.canvas.undo_last_stroke() is True
    assert game.canvas.revision == 6
    assert game.canvas.undo_last_stroke() is True
    assert game.canvas.revision == 7
    assert game.canvas.undo_last_stroke() is False
    assert game.canvas.revision == 7


def test_canvas_sequence_commits_crc32_and_undo_uses_prefix_hash():
    game = make_game()
    game.canvas.record_stroke("draw_shape", shape_payload())
    first_hash = game.canvas.hash
    assert game.canvas.commit_sequence(1) == (
        game.canvas.revision,
        first_hash,
        "action",
    )

    game.canvas.record_stroke(
        "draw_fill",
        {"x": 0.25, "y": 0.75, "color": "#abcdef"},
    )
    assert game.canvas.hash != first_hash
    assert game.canvas.commit_sequence(2)[1] == game.canvas.hash

    assert game.canvas.undo_last_stroke() is True
    assert game.canvas.hash == first_hash
    assert game.canvas.commit_sequence(3, "undo") == (
        game.canvas.revision,
        first_hash,
        "undo",
    )


def test_canvas_commit_history_keeps_a_bounded_recovery_window():
    game = make_game()
    for sequence in range(1, MAX_CANVAS_COMMITS + 3):
        game.canvas.commit_sequence(sequence)

    assert len(game.canvas.commits) == MAX_CANVAS_COMMITS
    assert game.canvas.commit_base_sequence == 3
    assert game.canvas.get_commit(2) is None
    assert game.canvas.get_commit(3) is not None
    assert game.canvas.get_commit(MAX_CANVAS_COMMITS + 2) is not None


def test_record_stroke_respects_history_limit(monkeypatch):
    monkeypatch.setattr("app.canvas_session.MAX_CANVAS_ACTIONS", 1)
    game = make_game()

    assert game.canvas.record_stroke("draw_shape", shape_payload()) is True
    assert game.canvas.record_stroke("draw_shape", shape_payload("ellipse")) is False
    assert len(game.canvas.history) == 1

    assert game.canvas.clear_canvas_stroke() is False
    assert len(game.canvas.history) == 1


def test_record_stroke_respects_total_path_point_limit(monkeypatch):
    monkeypatch.setattr("app.canvas_session.MAX_CANVAS_POINTS", 3)
    game = make_game()

    assert game.canvas.record_stroke("draw_start", pen_start()) is True
    assert game.canvas.record_stroke(
        "draw_move",
        {"points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}]},
    )
    assert game.canvas.record_stroke(
        "draw_move",
        {"points": [{"x": 0.3, "y": 0.3}]},
    ) is False
    assert game.canvas.point_count == 3

    assert game.canvas.undo_last_stroke() is True
    assert game.canvas.point_count == 0


def test_undo_last_stroke_removes_entire_pen_stroke():
    game = make_game()
    game.canvas.record_stroke("draw_start", pen_start())
    game.canvas.record_stroke("draw_move", {"points": [{"x": 0.1, "y": 0.1}]})
    game.canvas.record_stroke("draw_end", {})
    assert game.canvas.undo_last_stroke() is True
    assert game.canvas.history == []


def test_undo_last_stroke_only_removes_most_recent_stroke():
    game = make_game()
    game.canvas.record_stroke("draw_start", pen_start())
    game.canvas.record_stroke("draw_end", {})
    game.canvas.record_stroke("draw_start", pen_start(1, 1))
    game.canvas.record_stroke("draw_move", {"points": [{"x": 0.2, "y": 0.2}]})
    game.canvas.record_stroke("draw_end", {})
    assert game.canvas.undo_last_stroke() is True
    assert all(isinstance(action, PathAction) for action in game.canvas.history)


def test_undo_last_stroke_removes_single_shape_event():
    game = make_game()
    game.canvas.record_stroke("draw_start", pen_start())
    game.canvas.record_stroke("draw_end", {})
    game.canvas.record_stroke("draw_shape", shape_payload())
    assert game.canvas.undo_last_stroke() is True
    assert all(isinstance(action, PathAction) for action in game.canvas.history)


def test_undo_last_stroke_repeatedly_empties_history():
    game = make_game()
    game.canvas.record_stroke("draw_shape", shape_payload("ellipse"))
    game.canvas.record_stroke("draw_start", pen_start())
    game.canvas.record_stroke("draw_end", {})
    assert game.canvas.undo_last_stroke() is True
    assert game.canvas.undo_last_stroke() is True
    assert game.canvas.history == []
    assert game.canvas.undo_last_stroke() is False


def test_clear_canvas_stroke_and_undo_clear():
    game = make_game()
    game.canvas.record_stroke("draw_start", pen_start())
    game.canvas.record_stroke("draw_end", {})
    assert game.canvas.clear_canvas_stroke() is True
    assert isinstance(game.canvas.history[0], PathAction)
    assert isinstance(game.canvas.history[1], ClearAction)

    # Undo recovers drawing history to before Clear was pressed
    assert game.canvas.undo_last_stroke() is True
    assert all(isinstance(action, PathAction) for action in game.canvas.history)


def test_new_stroke_after_clear_resets_pre_clear_history():
    game = make_game()
    game.canvas.record_stroke("draw_start", pen_start())
    game.canvas.record_stroke("draw_end", {})
    game.canvas.clear_canvas_stroke()

    # Starting a new stroke after Clear resets pre-clear history
    game.canvas.record_stroke("draw_start", pen_start(1, 1))
    assert isinstance(game.canvas.history[0], PathAction)
    assert game.canvas.history[0].points[0][0] == 1


def test_sync_payload_round_trip_preserves_replay_and_undo_actions():
    game = make_game()
    game.canvas.record_stroke("draw_start", {**pen_start(), "color": "#ffffff"})
    game.canvas.record_stroke("draw_move", {"points": [{"x": 0.2, "y": 0.3}]})
    game.canvas.record_stroke("draw_end", {})
    game.canvas.record_stroke("draw_shape", shape_payload("triangle"))
    game.canvas.record_stroke(
        "draw_fill",
        {"x": 0.999, "y": 0.999, "color": "#123456"},
    )
    game.canvas.clear_canvas_stroke()

    assert decode_binary_canvas_history(
        game.canvas.sync_payload()
    ) == game.canvas.history
    assert game.canvas.undo_last_stroke() is True
    assert game.canvas.history[-1] == FillAction(x=799, y=599, color=0x123456)


def test_masked_word_returns_unmasked_for_drawer_and_correct_guesser():
    game = make_game(n_players=3)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game._set_prompt("cat")
    drawer = game.current_drawer
    guesser1, guesser2 = [t for t in game.turn_order if t != drawer]

    # Drawer sees unmasked prompt
    assert game.masked_prompt(drawer) == "cat"
    # Other guessers see masked prompt
    assert game.masked_prompt(guesser1) != "cat"

    # Correct guesser sees unmasked prompt
    game.submit_guess(guesser1, "cat")
    assert game.masked_prompt(guesser1) == "cat"
    assert game.masked_prompt(guesser2) != "cat"


def test_start_next_turn_skips_afk_drawers():
    game = make_game(n_players=3)
    p1, p2, p3 = game.turn_order
    # p2 is marked AFK
    game.start_next_turn(afk_tokens={p2}, canvas_generation=game.canvas.generation + 1)
    assert game.current_drawer == p1

    # Next turn skips p2 and chooses p3
    game.start_next_turn(afk_tokens={p2}, canvas_generation=game.canvas.generation + 1)
    assert game.current_drawer == p3


def make_hint_game(prompt, mode, n_players=3):
    game = make_game(n_players=n_players, rounds=1)
    game.hint_mode = mode
    game.prompt_pool = [prompt]
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.force_prompt_choice()
    return game


def test_reveal_hint_letter_respects_min_hidden_letters():
    # 4 alnum letters ("test"): up to 2 can be revealed while keeping
    # MIN_HIDDEN_LETTERS (2) hidden, then no more.
    game = make_hint_game("test", "checkpoints")
    assert game.reveal_hint_letter() is True
    assert len(game.revealed_positions) == 1
    assert game.reveal_hint_letter() is True
    assert len(game.revealed_positions) == 2
    assert game.reveal_hint_letter() is False
    assert len(game.revealed_positions) == 2


def test_reveal_hint_letter_too_short_word_never_reveals():
    game = make_hint_game("hi", "checkpoints")
    assert game.reveal_hint_letter() is False
    assert game.revealed_positions == set()


def test_max_hint_checkpoints_scales_with_word_length():
    game = make_hint_game("hi", "checkpoints")
    assert game.max_hint_checkpoints() == 0

    game_cat = make_hint_game("cat", "checkpoints")
    assert game_cat.max_hint_checkpoints() == 1

    game_banana = make_hint_game("banana", "checkpoints")
    assert game_banana.max_hint_checkpoints() == 2

    game_long = make_hint_game("the quick brown fox", "checkpoints")
    assert game_long.max_hint_checkpoints() == 6


def test_reveal_hint_letter_is_shown_to_everyone():
    game = make_hint_game("testing", "checkpoints")
    assert game.reveal_hint_letter() is True
    masked_for_no_one = game.masked_prompt()
    masked_for_someone = game.masked_prompt("p1")
    assert masked_for_no_one == masked_for_someone
    assert masked_for_no_one.count("_") == len(game.prompt) - 1


def test_buy_hint_letter_rejects_when_not_in_purchase_mode():
    game = make_hint_game("testing", "checkpoints")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.buy_hint_letter(guesser, 0) is False


def test_buy_hint_letter_rejects_drawer_and_correct_guessers():
    game = make_hint_game("testing", "purchase")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.buy_hint_letter(game.current_drawer, 0) is False

    game.set_phase_deadline(DRAWING_SECONDS)
    game.submit_guess(guesser, game.prompt)
    assert game.buy_hint_letter(guesser, 1) is False


def test_buy_hint_letter_rejects_invalid_or_already_revealed_slot():
    game = make_hint_game("testing", "purchase")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.buy_hint_letter(guesser, -1) is False
    assert game.buy_hint_letter(guesser, len(game.letter_positions)) is False

    assert game.buy_hint_letter(guesser, 0) is True
    assert game.buy_hint_letter(guesser, 0) is False


def test_buy_hint_letter_is_private_to_the_buyer():
    game = make_hint_game("testing", "purchase")
    tokens = [t for t in game.turn_order if t != game.current_drawer]
    buyer, other = tokens[0], tokens[1]
    assert game.buy_hint_letter(buyer, 2) is True

    masked_for_buyer = game.masked_prompt(buyer)
    masked_for_other = game.masked_prompt(other)
    masked_for_no_one = game.masked_prompt()
    assert masked_for_buyer.count("_") == len(game.prompt) - 1
    assert masked_for_other.count("_") == len(game.prompt)
    assert masked_for_no_one.count("_") == len(game.prompt)


def test_hint_cost_scales_up_per_hint_bought_this_turn():
    game = make_hint_game("testing", "purchase")
    buyer = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.hint_cost(buyer) == 12
    game.buy_hint_letter(buyer, 0)
    assert game.hint_cost(buyer) == 24
    game.buy_hint_letter(buyer, 1)
    assert game.hint_cost(buyer) == 36
    # Cost is tracked per-player - another guesser's first hint is still cheap.
    other = next(t for t in game.turn_order if t not in (game.current_drawer, buyer))
    assert game.hint_cost(other) == 12


def test_buy_wheel_letter_rejects_when_not_in_wheel_mode():
    game = make_hint_game("testing", "purchase")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.buy_wheel_letter(guesser, "t") is False


def test_buy_wheel_letter_rejects_drawer_and_correct_guessers():
    game = make_hint_game("testing", "wheel")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.buy_wheel_letter(game.current_drawer, "t") is False

    game.set_phase_deadline(DRAWING_SECONDS)
    game.submit_guess(guesser, game.prompt)
    assert game.buy_wheel_letter(guesser, "e") is False


def test_buy_wheel_letter_rejects_duplicate_letter():
    game = make_hint_game("testing", "wheel")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.buy_wheel_letter(guesser, "t") is True
    assert game.buy_wheel_letter(guesser, "t") is False


def test_buy_wheel_letter_reveals_all_occurrences_privately():
    game = make_hint_game("testing", "wheel")
    tokens = [t for t in game.turn_order if t != game.current_drawer]
    buyer, other = tokens[0], tokens[1]
    assert game.buy_wheel_letter(buyer, "t") is True  # "testing" has 2 t's

    masked_for_buyer = game.masked_prompt(buyer)
    masked_for_other = game.masked_prompt(other)
    masked_for_no_one = game.masked_prompt()
    assert masked_for_buyer.count("_") == len(game.prompt) - 2
    assert masked_for_other.count("_") == len(game.prompt)
    assert masked_for_no_one.count("_") == len(game.prompt)


def test_buy_wheel_letter_still_recorded_when_letter_absent():
    game = make_hint_game("testing", "wheel")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.buy_wheel_letter(guesser, "z") is True  # not in "testing"
    assert game.masked_prompt(guesser).count("_") == len(game.prompt)
    # Still counts toward this turn's escalating cost, and can't be re-bought.
    assert game.buy_wheel_letter(guesser, "z") is False


def test_wheel_hint_cost_scales_up_per_letter_bought_this_turn():
    game = make_hint_game("testing", "wheel")
    buyer = next(t for t in game.turn_order if t != game.current_drawer)
    base_cost = game.letter_price("t")
    assert game.wheel_hint_cost(buyer, "t") == base_cost
    game.buy_wheel_letter(buyer, "t")
    assert game.wheel_hint_cost(buyer, "e") == game.letter_price("e") * 2
    game.buy_wheel_letter(buyer, "e")
    assert game.wheel_hint_cost(buyer, "s") == game.letter_price("s") * 3
    # Cost is tracked per-player - another guesser's first letter is still base price.
    other = next(t for t in game.turn_order if t not in (game.current_drawer, buyer))
    assert game.wheel_hint_cost(other, "t") == base_cost


def test_letter_price_vowel_pricier_than_consonant_baseline():
    # A prompt pool with equal frequency for the vowel and consonant compared,
    # so only the flat vowel/consonant baseline (not frequency) affects price.
    game = make_hint_game("aabb", "wheel")
    assert game.letter_price("a") > game.letter_price("b")


def test_letter_price_rarer_letter_costs_less():
    # "t" appears far more often than "z" across this pool, so "z" (rarer)
    # should cost less than "t", both being consonants - use two consonants
    # to isolate the frequency effect from the vowel/consonant baseline.
    game = make_hint_game("test", "wheel")
    game.prompt_pool = ["ttttt", "ttttt", "ttttz"]
    assert game.letter_price("z") < game.letter_price("t")


def make_close_guess_game(prompt, n_players=3):
    game = make_game(n_players=n_players, rounds=1)
    game.prompt_pool = [prompt]
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.force_prompt_choice()
    return game


def test_guess_hint_distance_one_is_always_close():
    game = make_close_guess_game("testing")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.guess_hint(guesser, "testng") == "close"  # 1 char missing


def test_guess_hint_counts_transposition_as_one_edit():
    # Damerau-Levenshtein: a swapped pair of adjacent letters is a single
    # edit, not two substitutions, so "elpehant" (swapped "pe") should be
    # just as close as a one-letter typo.
    game = make_close_guess_game("elephant")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.guess_hint(guesser, "elpehant") == "close"


def test_bounded_edit_distance_returns_sentinel_outside_useful_band():
    sentinel = CLOSE_GUESS_MAX_DISTANCE + 1
    assert _bounded_damerau_levenshtein("panda", "padna", 2) == 1
    assert _bounded_damerau_levenshtein("panda", "pandemonium", 2) == sentinel
    assert _bounded_damerau_levenshtein("x" * 60, "y" * 60, 2) == sentinel


def test_largest_guess_uses_bounded_edit_distance_memory():
    import tracemalloc

    guess = "x" * MAX_PROMPT_LENGTH
    target = "y" * MAX_PROMPT_LENGTH
    tracemalloc.start()
    try:
        _bounded_damerau_levenshtein(
            guess,
            target,
            CLOSE_GUESS_MAX_DISTANCE,
        )
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    # Three distance-2 sparse rows should stay far below a full 61x61 matrix.
    assert peak_bytes < 16 * 1024


def test_guess_hint_distance_between_2_and_5_uses_similarity_ratio():
    game = make_close_guess_game("testing")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.guess_hint(guesser, "testong") == "close"  # distance 2, high overlap
    assert game.guess_hint(guesser, "xyz") is None  # distance too large / ratio too low


def test_guess_hint_exact_match_returns_none():
    game = make_close_guess_game("testing")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.guess_hint(guesser, "testing") is None


def test_guess_hint_treats_accent_only_difference_as_exact_match():
    game = make_close_guess_game("café")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.guess_hint(guesser, "cafe") is None


def test_guess_hint_rejects_drawer_and_correct_guessers():
    game = make_close_guess_game("testing")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.guess_hint(game.current_drawer, "testng") is None

    game.set_phase_deadline(DRAWING_SECONDS)
    game.submit_guess(guesser, game.prompt)
    assert game.guess_hint(guesser, "testng") is None


def test_guess_hint_ignores_very_short_strings():
    game = make_close_guess_game("cat")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # A single-letter guess is too short to be meaningfully "close", and
    # there's only one prompt so no partial-match hint applies either.
    assert game.guess_hint(guesser, "c") is None


def test_guess_hint_close_whole_phrase():
    game = make_close_guess_game("red panda")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.guess_hint(guesser, "red pand") == "close"
    assert game.guess_hint(guesser, "totally unrelated") is None


def test_guess_hint_partial_word_match():
    game = make_close_guess_game("big shiny castle")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # "shiny" (5 letters) matches exactly, but the whole phrase is too
    # different overall to be flagged "close" - falls back to the
    # partial-prompt-match hint.
    assert game.guess_hint(guesser, "big shiny house") == "partial"


def test_guess_hint_partial_multiple_short_words_reach_min_letters():
    game = make_close_guess_game("tiny red ant")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # Neither "red" nor "ant" alone reaches CLOSE_GUESS_MIN_CORRECT_LETTERS,
    # but their combined length (6) does.
    assert game.guess_hint(guesser, "huge red ant") == "partial"


def test_guess_hint_partial_requires_min_correct_letters():
    game = make_close_guess_game("tiny red ant")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # Only one short prompt ("red", 3 letters) matches exactly - below
    # CLOSE_GUESS_MIN_CORRECT_LETTERS.
    assert game.guess_hint(guesser, "huge red bug") is None


def test_guess_hint_partial_single_word_below_min_letters():
    game = make_close_guess_game("big frog king")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # "frog" (4 letters) is the only match - just below the 5-letter minimum.
    assert game.guess_hint(guesser, "hot frog thing") is None


def test_guess_hint_partial_allows_one_word_count_difference():
    game = make_close_guess_game("big giant purple octopus")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # Missing the last prompt entirely, but the prompt-count difference is only
    # 1, which is now tolerated - "big", "giant" and "purple" all match.
    assert game.guess_hint(guesser, "big giant purple") == "partial"


def test_guess_hint_partial_rejects_word_count_diff_over_one():
    game = make_close_guess_game("big giant purple octopus")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # Missing 2 of the 4 words: prompt-count difference is 2, too large to be
    # tolerated, so the partial-prompt check is skipped entirely.
    assert game.guess_hint(guesser, "big giant") is None


def test_guess_hint_partial_word_order_independent():
    game = make_close_guess_game("red panda bear")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # All 3 words are correct but reordered - matching is position
    # independent (bag-of-words), so this still counts as partial.
    assert game.guess_hint(guesser, "panda red bear") == "partial"


def test_guess_hint_partial_caps_duplicate_word_matches():
    game = make_close_guess_game("red red panda")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # Duplicate words are capped at the lower count per prompt (multiset
    # intersection): 1x "red" (guess has 1, target has 2) + 1x "panda"
    # (guess has 2, target has 1) = 3 + 5 = 8 correct letters total.
    assert game.guess_hint(guesser, "red panda panda") == "partial"


def test_new_scoring_system_guesser_and_drawer_scores():
    game = make_game(n_players=3)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.choose_prompt(game.current_drawer, game.prompt_choices[0])

    others = [t for t in game.turn_order if t != game.current_drawer]
    g1, g2 = others[0], others[1]

    # Guesser 1 guesses at start (t = 0, remaining = 80s) -> 300 points
    game.remaining_seconds = lambda: DRAWING_SECONDS
    _, p1 = game.submit_guess(g1, game.prompt)
    assert p1 == 300

    # Guesser 2 guesses halfway through (t = 40s, remaining = 40s) -> 200 points
    game.remaining_seconds = lambda: DRAWING_SECONDS / 2
    _, p2 = game.submit_guess(g2, game.prompt)
    assert p2 == 200

    # Drawer score equals sum of guesser scores (300 + 200 = 500)
    drawer_score = game.end_turn()
    assert drawer_score == 500


def test_hide_masked_prompt_returns_question_marks():
    game = Game(turn_order=["p0", "p1"], rounds_total=1, hide_masked_prompt=True)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    prompt = game.prompt_choices[0]
    game.choose_prompt("p0", prompt)

    # Drawer sees full prompt
    assert game.masked_prompt("p0") == prompt

    # Guesser sees ???
    assert game.masked_prompt("p1") == "???"

    # Spectator without prompt access sees ???
    assert game.masked_prompt("spec", is_spectator=True, spectators_see_prompt=False) == "???"

    # Spectator with prompt access sees the full prompt
    assert game.masked_prompt("spec", is_spectator=True, spectators_see_prompt=True) == prompt

    # Guesser who answered correctly sees full prompt
    game.submit_guess("p1", prompt)
    assert game.masked_prompt("p1") == prompt


# --- per-turn analytics kept for the game record --------------------------

def test_hint_purchases_record_what_the_player_was_charged():
    """The recorded debt has to match the price the player was quoted.

    `buy_hint` reads `hint_cost` to answer the client, so the game records the
    same reading, taken before the purchase moves the price.
    """
    game = make_hint_game("testing", "purchase")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)

    first_price = game.hint_cost(guesser)
    assert game.buy_hint_letter(guesser, 0) is True
    second_price = game.hint_cost(guesser)
    assert game.buy_hint_letter(guesser, 1) is True

    assert second_price > first_price
    assert game.hint_purchases[guesser] == 2
    assert game.hint_spend[guesser] == first_price + second_price


def test_wheel_letter_purchases_record_their_own_prices():
    game = make_hint_game("testing", "wheel")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)

    price = game.wheel_hint_cost(guesser, "e")
    assert game.buy_wheel_letter(guesser, "e") is True

    assert game.hint_purchases[guesser] == 1
    assert game.hint_spend[guesser] == price


def test_a_rejected_purchase_costs_nothing():
    game = make_hint_game("testing", "purchase")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    game.buy_hint_letter(guesser, 0)
    spend = game.hint_spend[guesser]

    assert game.buy_hint_letter(guesser, 0) is False
    assert game.hint_spend[guesser] == spend


# --- hints are bought on credit and settled against the turn's guess ------

def guess_with_remaining(game, token, remaining):
    """Guess the prompt with the drawing clock parked at `remaining` seconds."""
    game.remaining_seconds = lambda: remaining
    return game.submit_guess(token, game.prompt)


def test_hint_spend_is_deducted_from_a_correct_guess():
    game = make_hint_game("testing", "purchase")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.buy_hint_letter(guesser, 0) is True
    assert game.buy_hint_letter(guesser, 1) is True
    spend = game.hint_spend[guesser]

    correct, points = guess_with_remaining(game, guesser, game.drawing_seconds)

    assert correct is True
    assert points == MAX_GUESS_POINTS - spend
    assert game.guess_points[guesser] == MAX_GUESS_POINTS - spend


def test_hint_spend_cannot_push_a_turn_below_zero():
    game = make_hint_game("testing", "purchase")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    for slot in range(5):  # 12 + 24 + 36 + 48 + 60 = 180
        assert game.buy_hint_letter(guesser, slot) is True
    assert game.hint_spend[guesser] > MIN_GUESS_POINTS

    # Guessing on the buzzer is worth MIN_GUESS_POINTS, less than the debt.
    correct, points = guess_with_remaining(game, guesser, 0.0)

    assert correct is True
    assert points == 0
    assert game.guess_points[guesser] == 0


def test_hints_cost_nothing_without_a_correct_guess():
    game = make_hint_game("testing", "purchase")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.buy_hint_letter(guesser, 0) is True

    drawer_bonus = game.end_turn(total_guesser_count=2)

    assert drawer_bonus == 0
    assert game.completed_turns[-1].guesses == ()
    assert game.hint_spend[guesser] == HINT_BASE_COST


def test_hint_spend_only_charges_the_buyer():
    game = make_hint_game("testing", "purchase", n_players=3)
    buyer, bystander = [t for t in game.turn_order if t != game.current_drawer]
    assert game.buy_hint_letter(buyer, 0) is True

    _, bystander_points = guess_with_remaining(game, bystander, game.drawing_seconds)
    _, buyer_points = guess_with_remaining(game, buyer, game.drawing_seconds)

    assert bystander_points == MAX_GUESS_POINTS
    assert buyer_points == MAX_GUESS_POINTS - HINT_BASE_COST


def test_drawer_bonus_is_the_sum_of_post_hint_points():
    game = make_hint_game("testing", "purchase", n_players=3)
    buyer, bystander = [t for t in game.turn_order if t != game.current_drawer]
    assert game.buy_hint_letter(buyer, 0) is True
    guess_with_remaining(game, bystander, game.drawing_seconds)
    guess_with_remaining(game, buyer, game.drawing_seconds)

    drawer_bonus = game.end_turn(total_guesser_count=2)

    assert drawer_bonus == sum(game.guess_points.values())
    assert drawer_bonus == 2 * MAX_GUESS_POINTS - HINT_BASE_COST


def test_hint_spend_resets_between_turns():
    game = make_hint_game("testing", "purchase")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.buy_hint_letter(guesser, 0) is True

    game.end_turn(total_guesser_count=2)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)

    assert game.hint_spend == {}
    assert game.hint_spend_remaining(guesser) == MAX_HINT_SPEND


# --- the per-turn hint spend limit ----------------------------------------

def test_hint_spend_cannot_exceed_the_best_possible_guess():
    """The cap is the point past which more hints could never pay for
    themselves, so it tracks the best a turn can award."""
    assert MAX_HINT_SPEND == MAX_GUESS_POINTS


def test_hint_spend_remaining_tracks_the_cap():
    game = make_hint_game("testing", "purchase")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.hint_spend_remaining(guesser) == MAX_HINT_SPEND

    game.buy_hint_letter(guesser, 0)
    assert game.hint_spend_remaining(guesser) == MAX_HINT_SPEND - HINT_BASE_COST

    game.hint_spend[guesser] = MAX_HINT_SPEND + 500
    assert game.hint_spend_remaining(guesser) == 0


def test_a_purchase_over_the_turn_budget_is_rejected():
    # 12 + 24 + 36 + 48 + 60 + 72 = 252; a seventh hint costs 84 and would
    # take the turn past MAX_HINT_SPEND.
    game = make_hint_game("testing", "purchase")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    for slot in range(6):
        assert game.buy_hint_letter(guesser, slot) is True
    spend = game.hint_spend[guesser]
    assert spend + game.hint_cost(guesser) > MAX_HINT_SPEND

    assert game.buy_hint_letter(guesser, 6) is False
    assert game.hint_spend[guesser] == spend
    assert 6 not in game.purchased_hints[guesser]
    assert "_" in game.masked_prompt(guesser)


def test_an_over_budget_wheel_letter_is_rejected():
    game = make_hint_game("testing", "wheel")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    game.hint_spend[guesser] = MAX_HINT_SPEND - 1
    assert game.wheel_hint_cost(guesser, "e") > 1

    assert game.buy_wheel_letter(guesser, "e") is False
    assert game.hint_spend[guesser] == MAX_HINT_SPEND - 1
    assert game.purchased_letters.get(guesser, set()) == set()


def test_only_real_guess_attempts_are_counted_as_wrong():
    game = make_hint_game("testing", "none")
    drawer = game.current_drawer
    guesser, other = [t for t in game.turn_order if t != drawer]

    game.submit_guess(guesser, "banana")
    game.submit_guess(drawer, "banana")       # the drawer is chatting
    game.submit_guess(other, "testing")       # correct
    game.submit_guess(other, "banana")        # already correct: chatting too

    assert game.wrong_guesses == {guesser: 1}


def test_near_misses_are_counted_separately():
    game = make_hint_game("testing", "none")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)

    game.submit_guess(guesser, "testng")   # one deletion: close
    game.submit_guess(guesser, "aardvark")  # nowhere near

    assert game.wrong_guesses[guesser] == 2
    assert game.near_miss_count == 1


def test_turn_outcomes_preserve_non_success_and_ineligible_states():
    game = make_hint_game("testing", "purchase", n_players=4)
    eligible, afk, disconnected = [
        token for token in game.turn_order if token != game.current_drawer
    ]
    game.snapshot_turn_participants(
        {
            eligible: "eligible",
            afk: "afk",
            disconnected: "disconnected",
        }
    )
    assert game.buy_hint_letter(eligible, 0) is True
    game.submit_guess(eligible, "testng")
    game.add_player_to_rotation("late-player")
    assert game.submit_guess("late-player", "testing") == (False, 0)

    game.end_turn(
        total_guesser_count=1,
        terminal_states={
            eligible: "left",
            afk: "afk",
            disconnected: "disconnected",
            "late-player": "active",
        },
    )

    outcomes = {
        outcome.token: outcome for outcome in game.completed_turns[-1].participant_outcomes
    }
    attempted = outcomes[eligible]
    assert attempted.eligible is True
    assert attempted.outcome == "incorrect"
    assert attempted.terminal_state == "left"
    assert attempted.correct_guess_time_seconds is None
    assert attempted.wrong_guess_count == 1
    assert attempted.near_miss_count == 1
    assert attempted.hints_used == 1
    assert attempted.points_spent_on_hints > 0
    assert outcomes[afk].eligibility_reason == "afk"
    assert outcomes[afk].outcome == "ineligible"
    assert outcomes[disconnected].terminal_state == "disconnected"
    assert outcomes["late-player"].eligibility_reason == "joined_late"
    assert outcomes["late-player"].outcome == "ineligible"


def test_a_word_the_drawer_chose_is_not_marked_auto_picked():
    game = make_game(n_players=2, rounds=1)
    choices = game.start_next_turn(canvas_generation=1)
    assert game.choose_prompt(game.current_drawer, choices[0]) is True
    assert game.prompt_auto_picked is False


def test_a_word_the_clock_picked_is_marked_auto_picked():
    game = make_game(n_players=2, rounds=1)
    game.start_next_turn(canvas_generation=1)
    game.force_prompt_choice()
    assert game.prompt_auto_picked is True


def test_completed_turn_records_how_the_round_ended():
    game = make_hint_game("testing", "none", n_players=2)
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    game.submit_guess(guesser, "testing")

    game.end_turn(total_guesser_count=1)

    turn = game.completed_turns[-1]
    assert turn.end_reason == "all_guessed"
    assert turn.total_guesser_count == 1


def test_a_round_nobody_solved_ends_on_the_clock():
    game = make_hint_game("testing", "none", n_players=2)
    game.end_turn(total_guesser_count=1)
    assert game.completed_turns[-1].end_reason == "timeout"


def test_completed_turn_records_the_roster_and_the_drawing_effort():
    game = make_hint_game("testing", "none", n_players=3)
    game.canvas.record_stroke("draw_start", pen_start())
    game.canvas.record_stroke("draw_end", {})

    game.end_turn(total_guesser_count=2)

    turn = game.completed_turns[-1]
    assert turn.present_tokens == tuple(game.turn_order)
    assert turn.stroke_count == len(game.canvas.history)
    assert turn.stroke_count > 0


def test_per_turn_analytics_do_not_leak_into_the_next_turn():
    game = make_hint_game("testing", "purchase", n_players=2)
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    game.buy_hint_letter(guesser, 0)
    game.submit_guess(guesser, "banana")
    game.end_turn(total_guesser_count=1)

    game.start_next_turn(canvas_generation=game.canvas.generation + 1)

    assert game.hint_spend == {}
    assert game.hint_purchases == {}
    assert game.wrong_guesses == {}
    assert game.near_miss_count == 0
    assert game.prompt_auto_picked is False


# ---------------------------------------------------------------------------
# "pressure" scoring mode
# ---------------------------------------------------------------------------


def make_pressure_game(n_guessers=1, drawing_seconds=90.0):
    """A pressure-mode game parked in DRAWING with the prompt chosen.

    The clock is driven by assigning to `game.remaining_seconds`, matching
    `test_submit_guess_records_elapsed_guess_time`.
    """
    tokens = ["drawer"] + [f"g{i}" for i in range(n_guessers)]
    game = Game(
        turn_order=tokens, scoring_mode="pressure", drawing_seconds=drawing_seconds
    )
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.choose_prompt(game.current_drawer, game.prompt_choices[0])
    return game


def guess_at(game, token, elapsed):
    game.remaining_seconds = lambda: game.drawing_seconds - elapsed
    correct, points = game.submit_guess(token, game.prompt)
    assert correct is True
    return points


def test_pressure_awards_the_maximum_on_an_instant_guess():
    game = make_pressure_game()
    assert guess_at(game, "g0", 0.0) == PRESSURE_MAX_POINTS


def test_pressure_points_decrease_monotonically_with_time():
    scores = []
    for elapsed in (0, 5, 10, 20, 30, 45, 60):
        game = make_pressure_game()
        scores.append(guess_at(game, "g0", elapsed))
    assert scores == sorted(scores, reverse=True)
    assert len(set(scores)) == len(scores)


def test_pressure_curve_is_independent_of_round_length():
    """The whole point of deriving the rate from drawing_seconds: a guess at the
    same *fraction* of the turn is worth the same in a 15s room and a 300s one."""
    for fraction in (0.0, 0.25, 0.5, 1.0):
        values = set()
        for drawing_seconds in DRAWING_TIME_OPTIONS:
            game = make_pressure_game(drawing_seconds=float(drawing_seconds))
            values.add(guess_at(game, "g0", drawing_seconds * fraction))
        assert len(values) == 1, f"fraction {fraction} varied by room length: {values}"


def test_pressure_unpressured_late_guess_is_a_fixed_share_of_the_maximum():
    """Measured just short of the buzzer, where the raw curve still governs: by
    the buzzer itself an unpressured guess has decayed into the floor."""
    for drawing_seconds in DRAWING_TIME_OPTIONS:
        game = make_pressure_game(drawing_seconds=float(drawing_seconds))
        assert guess_at(game, "g0", drawing_seconds * 0.95) == 53

    for drawing_seconds in DRAWING_TIME_OPTIONS:
        game = make_pressure_game(drawing_seconds=float(drawing_seconds))
        assert guess_at(game, "g0", drawing_seconds) == PRESSURE_MIN_POINTS


def test_pressure_multiplier_is_dormant_until_someone_guesses():
    game = make_pressure_game(n_guessers=2)
    assert game._pressure_multiplier() == 1.0
    guess_at(game, "g0", 10.0)
    assert game._pressure_multiplier() == PRESSURE_MULTIPLIER


def test_pressure_simultaneous_guesses_score_identically():
    game = make_pressure_game(n_guessers=2)
    first = guess_at(game, "g0", 20.0)
    second = guess_at(game, "g1", 20.0)
    assert first == second


def test_pressure_barely_punishes_a_photo_finish():
    """The explicit design requirement: a guess landing right behind the first
    correct one must not fall off a cliff.

    Measured against what the same guess would have paid with the multiplier
    dormant, so this isolates the pressure penalty from the ordinary per-second
    decay that elapsed during the gap.
    """
    for gap in (0.1, 0.5, 1.0):
        pressured = make_pressure_game(n_guessers=2)
        guess_at(pressured, "g0", 20.0)
        with_pressure = guess_at(pressured, "g1", 20.0 + gap)

        alone = make_pressure_game()
        without_pressure = guess_at(alone, "g0", 20.0 + gap)

        penalty = without_pressure - with_pressure
        assert penalty <= 5, f"gap {gap}s drew a {penalty}-point pressure penalty"


def test_pressure_photo_finish_stays_close_to_the_winner():
    """The player-visible half of the same requirement: losing the race by a
    hair should cost a handful of points, not a tier."""
    game = make_pressure_game(n_guessers=2)
    first = guess_at(game, "g0", 20.0)
    second = guess_at(game, "g1", 20.5)
    assert first - second <= 5, f"half a second cost {first - second} points"


def test_pressure_penalty_grows_with_the_gap():
    penalties = []
    for gap in (1.0, 5.0, 20.0):
        pressured = make_pressure_game(n_guessers=2)
        guess_at(pressured, "g0", 20.0)
        with_pressure = guess_at(pressured, "g1", 20.0 + gap)

        alone = make_pressure_game()
        without_pressure = guess_at(alone, "g0", 20.0 + gap)

        penalties.append(without_pressure - with_pressure)
    assert penalties == sorted(penalties)
    assert penalties[-1] >= 25


def test_pressure_never_pays_less_than_the_floor():
    for drawing_seconds in DRAWING_TIME_OPTIONS:
        game = make_pressure_game(n_guessers=2, drawing_seconds=float(drawing_seconds))
        guess_at(game, "g0", 0.0)
        assert guess_at(game, "g1", drawing_seconds) == PRESSURE_MIN_POINTS


def test_the_pressure_floor_does_not_protect_hint_debt():
    """PRESSURE_MIN_POINTS floors the gross award; the debt is settled after."""
    game = make_pressure_game(n_guessers=2, drawing_seconds=90.0)
    game.hint_mode = "purchase"
    guess_at(game, "g0", 0.0)
    game.hint_spend["g1"] = PRESSURE_MIN_POINTS + 10

    assert guess_at(game, "g1", 90.0) == 0


def test_pressure_decay_state_resets_between_turns():
    game = make_pressure_game(n_guessers=2)
    guess_at(game, "g0", 30.0)
    guess_at(game, "g1", 40.0)
    assert game.decay_time > 0

    game.end_turn(total_guesser_count=2)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)

    assert game.decay_time == 0.0
    assert game.decay_marker_elapsed == 0.0


def test_pressure_drawer_bonus_is_the_sum_of_guesser_points():
    game = make_pressure_game(n_guessers=3)
    total = sum(
        guess_at(game, token, elapsed)
        for token, elapsed in (("g0", 12.0), ("g1", 18.0), ("g2", 25.0))
    )
    assert game.end_turn(total_guesser_count=3) == total


def test_pressure_worked_example_matches_the_documented_curve():
    """Pins the numbers the scoring mode was signed off on."""
    game = make_pressure_game(n_guessers=5)
    awarded = [
        guess_at(game, token, elapsed)
        for token, elapsed in (
            ("g0", 12.0),
            ("g1", 18.0),
            ("g2", 25.0),
            ("g3", 41.0),
            ("g4", 68.0),
        )
    ]
    assert awarded == [235, 185, 139, 73, 50]


def test_default_scoring_is_unchanged_by_the_constant_refactor():
    for elapsed, expected in ((0, 300), (40, 200), (80, 100)):
        game = Game(turn_order=["drawer", "guesser"], drawing_seconds=80.0)
        game.start_next_turn(canvas_generation=game.canvas.generation + 1)
        game.choose_prompt(game.current_drawer, game.prompt_choices[0])
        assert guess_at(game, "guesser", elapsed) == expected


def test_end_turn_refuses_a_missing_terminal_state():
    """A frozen seat with no reported end state is a caller bug, surfaced as a
    clear error instead of a KeyError mid-persistence."""
    game = make_game(n_players=2, rounds=1)
    game.start_next_turn(canvas_generation=game.canvas.generation + 1)
    game.choose_prompt(game.current_drawer, game.prompt_choices[0])
    game.snapshot_turn_participants({"p2": "eligible"})
    with pytest.raises(ValueError, match="terminal state"):
        game.end_turn(terminal_states={})
