from app.game import DRAWING_SECONDS, Game, Phase


def make_game(n_players=3, rounds=2):
    tokens = [f"p{i}" for i in range(n_players)]
    return Game(turn_order=tokens, rounds_total=rounds)


def test_start_next_turn_rotates_drawer():
    game = make_game(n_players=3, rounds=2)
    game.start_next_turn()
    assert game.current_drawer == "p0"
    game.choose_word(game.current_drawer, game.word_choices[0])
    game.end_round()
    game.start_next_turn()
    assert game.current_drawer == "p1"


def test_total_turns_and_finished():
    game = make_game(n_players=3, rounds=2)
    assert game.total_turns == 6
    for _ in range(6):
        game.start_next_turn()
    assert game.is_finished() is True


def test_choose_word_rejects_wrong_player():
    game = make_game()
    game.start_next_turn()
    other_player = "p1"
    assert game.choose_word(other_player, game.word_choices[0]) is False
    assert game.phase == Phase.CHOOSING_WORD


def test_choose_word_rejects_invalid_word():
    game = make_game()
    game.start_next_turn()
    assert game.choose_word(game.current_drawer, "not-a-choice") is False


def test_force_word_choice_picks_first_option():
    game = make_game()
    game.start_next_turn()
    first_choice = game.word_choices[0]
    game.force_word_choice()
    assert game.word == first_choice
    assert game.phase == Phase.DRAWING


def test_masked_word_reveals_length_only():
    game = make_game()
    game.start_next_turn()
    game.choose_word(game.current_drawer, game.word_choices[0])
    word = game.word
    expected = "_" * len(word) + f"  {len(word)}"
    assert game.masked_word() == expected


def test_masked_word_shows_spaces_and_special_characters():
    game = make_game(n_players=1, rounds=1)
    game.word_pool = ["red panda"]
    game.start_next_turn()
    game.force_word_choice()
    assert game.masked_word() == "___  _____  3 5"

    game2 = make_game(n_players=1, rounds=1)
    game2.word_pool = ["spider-man"]
    game2.start_next_turn()
    game2.force_word_choice()
    assert game2.masked_word() == "______-___  6 3"


def test_submit_guess_correct_awards_points_and_ignores_drawer():
    game = make_game(n_players=3)
    game.start_next_turn()
    game.choose_word(game.current_drawer, game.word_choices[0])
    game.set_phase_deadline(DRAWING_SECONDS)

    drawer_correct, drawer_points = game.submit_guess(game.current_drawer, game.word)
    assert drawer_correct is False
    assert drawer_points == 0

    guesser = "p1" if game.current_drawer != "p1" else "p2"
    correct, points = game.submit_guess(guesser, game.word.upper())
    assert correct is True
    assert points > 0
    # Guessing again should not award points twice.
    correct_again, points_again = game.submit_guess(guesser, game.word)
    assert correct_again is False
    assert points_again == 0


def test_submit_guess_wrong_word():
    game = make_game()
    game.start_next_turn()
    game.choose_word(game.current_drawer, game.word_choices[0])
    game.set_phase_deadline(DRAWING_SECONDS)
    correct, points = game.submit_guess("p1", "definitely-wrong")
    assert correct is False
    assert points == 0


def test_end_round_awards_drawer_bonus_per_guesser():
    game = make_game(n_players=3)
    game.start_next_turn()
    game.choose_word(game.current_drawer, game.word_choices[0])
    game.set_phase_deadline(DRAWING_SECONDS)
    others = [t for t in game.turn_order if t != game.current_drawer]
    for token in others:
        game.submit_guess(token, game.word)
    bonus = game.end_round()
    assert bonus == 10 * len(others)
    assert game.phase == Phase.ROUND_END


def test_end_round_bonus_shrinks_when_drawer_stalls_before_drawing():
    """A drawer who delays drawing (eating into the shared deadline) should earn a
    smaller bonus, not the same flat amount - otherwise stalling with an easy word
    to suppress guessers' scores would be free for the drawer."""
    game = make_game(n_players=3)
    game.start_next_turn()
    game.choose_word(game.current_drawer, game.word_choices[0])
    others = [t for t in game.turn_order if t != game.current_drawer]

    # Simulate stalling: only 1 second remains by the time guesses come in.
    game.set_phase_deadline(1)
    for token in others:
        game.submit_guess(token, game.word)
    stalled_bonus = game.end_round()

    # Compare against drawing immediately (full time remaining for guesses).
    game2 = make_game(n_players=3)
    game2.start_next_turn()
    game2.choose_word(game2.current_drawer, game2.word_choices[0])
    others2 = [t for t in game2.turn_order if t != game2.current_drawer]
    game2.set_phase_deadline(DRAWING_SECONDS)
    for token in others2:
        game2.submit_guess(token, game2.word)
    prompt_bonus = game2.end_round()

    assert stalled_bonus < prompt_bonus


def test_all_guessed():
    game = make_game(n_players=3)
    game.start_next_turn()
    game.choose_word(game.current_drawer, game.word_choices[0])
    others = [t for t in game.turn_order if t != game.current_drawer]
    assert game.all_guessed(len(others)) is False
    for token in others:
        game.submit_guess(token, game.word)
    assert game.all_guessed(len(others)) is True


def test_undo_last_stroke_with_no_strokes():
    game = make_game()
    assert game.undo_last_stroke() is False


def test_undo_last_stroke_removes_entire_pen_stroke():
    game = make_game()
    game.record_stroke("draw_start", {"x": 0, "y": 0})
    game.record_stroke("draw_move", {"points": [{"x": 0.1, "y": 0.1}]})
    game.record_stroke("draw_end", {})
    assert game.undo_last_stroke() is True
    assert game.strokes == []


def test_undo_last_stroke_only_removes_most_recent_stroke():
    game = make_game()
    game.record_stroke("draw_start", {"x": 0, "y": 0})
    game.record_stroke("draw_end", {})
    game.record_stroke("draw_start", {"x": 1, "y": 1})
    game.record_stroke("draw_move", {"points": [{"x": 0.2, "y": 0.2}]})
    game.record_stroke("draw_end", {})
    assert game.undo_last_stroke() is True
    assert [s["event"] for s in game.strokes] == ["draw_start", "draw_end"]


def test_undo_last_stroke_removes_single_shape_event():
    game = make_game()
    game.record_stroke("draw_start", {"x": 0, "y": 0})
    game.record_stroke("draw_end", {})
    game.record_stroke("draw_shape", {"shape": "rectangle"})
    assert game.undo_last_stroke() is True
    assert [s["event"] for s in game.strokes] == ["draw_start", "draw_end"]


def test_undo_last_stroke_repeatedly_empties_history():
    game = make_game()
    game.record_stroke("draw_shape", {"shape": "ellipse"})
    game.record_stroke("draw_start", {"x": 0, "y": 0})
    game.record_stroke("draw_end", {})
    assert game.undo_last_stroke() is True
    assert game.undo_last_stroke() is True
    assert game.strokes == []
    assert game.undo_last_stroke() is False


def make_hint_game(word, mode, n_players=3):
    game = make_game(n_players=n_players, rounds=1)
    game.hint_mode = mode
    game.word_pool = [word]
    game.start_next_turn()
    game.force_word_choice()
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


def test_reveal_hint_letter_is_shown_to_everyone():
    game = make_hint_game("testing", "checkpoints")
    assert game.reveal_hint_letter() is True
    masked_for_no_one = game.masked_word()
    masked_for_someone = game.masked_word("p1")
    assert masked_for_no_one == masked_for_someone
    assert masked_for_no_one.count("_") == len(game.word) - 1


def test_buy_hint_letter_rejects_when_not_in_purchase_mode():
    game = make_hint_game("testing", "checkpoints")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.buy_hint_letter(guesser, 0) is False


def test_buy_hint_letter_rejects_drawer_and_correct_guessers():
    game = make_hint_game("testing", "purchase")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.buy_hint_letter(game.current_drawer, 0) is False

    game.set_phase_deadline(DRAWING_SECONDS)
    game.submit_guess(guesser, game.word)
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

    masked_for_buyer = game.masked_word(buyer)
    masked_for_other = game.masked_word(other)
    masked_for_no_one = game.masked_word()
    assert masked_for_buyer.count("_") == len(game.word) - 1
    assert masked_for_other.count("_") == len(game.word)
    assert masked_for_no_one.count("_") == len(game.word)


def test_hint_cost_scales_up_per_hint_bought_this_turn():
    game = make_hint_game("testing", "purchase")
    buyer = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.hint_cost(buyer) == 5
    game.buy_hint_letter(buyer, 0)
    assert game.hint_cost(buyer) == 10
    game.buy_hint_letter(buyer, 1)
    assert game.hint_cost(buyer) == 15
    # Cost is tracked per-player - another guesser's first hint is still cheap.
    other = next(t for t in game.turn_order if t not in (game.current_drawer, buyer))
    assert game.hint_cost(other) == 5


def make_close_guess_game(word, n_players=3):
    game = make_game(n_players=n_players, rounds=1)
    game.word_pool = [word]
    game.start_next_turn()
    game.force_word_choice()
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


def test_guess_hint_distance_between_2_and_5_uses_similarity_ratio():
    game = make_close_guess_game("testing")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.guess_hint(guesser, "testong") == "close"  # distance 2, high overlap
    assert game.guess_hint(guesser, "xyz") is None  # distance too large / ratio too low


def test_guess_hint_exact_match_returns_none():
    game = make_close_guess_game("testing")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.guess_hint(guesser, "testing") is None


def test_guess_hint_rejects_drawer_and_correct_guessers():
    game = make_close_guess_game("testing")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.guess_hint(game.current_drawer, "testng") is None

    game.set_phase_deadline(DRAWING_SECONDS)
    game.submit_guess(guesser, game.word)
    assert game.guess_hint(guesser, "testng") is None


def test_guess_hint_ignores_very_short_strings():
    game = make_close_guess_game("cat")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # A single-letter guess is too short to be meaningfully "close", and
    # there's only one word so no partial-match hint applies either.
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
    # partial-word-match hint.
    assert game.guess_hint(guesser, "big shiny house") == "partial"


def test_guess_hint_partial_two_short_words_match():
    game = make_close_guess_game("tiny red ant")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # Neither "red" nor "ant" reaches CLOSE_GUESS_MIN_WORD_LENGTH on its own,
    # but 2 whole words matching exactly is still enough for the partial hint.
    assert game.guess_hint(guesser, "huge red ant") == "partial"


def test_guess_hint_partial_requires_long_word_or_min_correct_words():
    game = make_close_guess_game("tiny red ant")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # Only one short word ("red") matches exactly - neither rule is satisfied.
    assert game.guess_hint(guesser, "huge red bug") is None


def test_guess_hint_partial_requires_matching_token_count():
    game = make_close_guess_game("big giant purple octopus")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # Missing the last word entirely: token count differs from the target so
    # the partial-word check is skipped, and the whole phrase is too
    # different (missing "octopus") to be flagged "close" either.
    assert game.guess_hint(guesser, "big giant purple") is None

