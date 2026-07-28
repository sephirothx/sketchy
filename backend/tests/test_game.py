from app.game import DRAWING_SECONDS, Game, Phase


def make_game(n_players=3, rounds=2):
    tokens = [f"p{i}" for i in range(n_players)]
    return Game(turn_order=tokens, rounds_total=rounds)


def pen_start(x=0, y=0):
    return {"x": x, "y": y, "color": "#000000", "width": 4}


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


def test_adding_player_mid_round_preserves_current_and_next_drawer():
    game = make_game(n_players=3, rounds=2)
    game.start_next_turn()
    game.start_next_turn()
    assert game.current_drawer == "p1"

    game.add_player_to_rotation("late")

    assert game.current_drawer == "p1"
    assert game.round_number == 1
    game.start_next_turn()
    assert game.current_drawer == "p2"


def test_removing_non_drawer_preserves_current_and_next_drawer():
    game = make_game(n_players=3, rounds=2)
    game.start_next_turn()
    game.start_next_turn()
    assert game.current_drawer == "p1"

    assert game.remove_player_from_rotation("p0") is False

    assert game.current_drawer == "p1"
    assert game.round_number == 1
    game.start_next_turn()
    assert game.current_drawer == "p2"


def test_removing_drawer_positions_cursor_before_next_survivor():
    game = make_game(n_players=3, rounds=2)
    game.start_next_turn()
    game.start_next_turn()
    assert game.current_drawer == "p1"

    assert game.remove_player_from_rotation("p1") is True
    game.start_next_turn()

    assert game.current_drawer == "p2"
    assert game.round_number == 1


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


def test_submit_guess_records_elapsed_guess_time():
    game = make_game(n_players=2)
    game.start_next_turn()
    game.choose_word(game.current_drawer, game.word_choices[0])
    game.remaining_seconds = lambda: DRAWING_SECONDS - 12.5
    guesser = next(token for token in game.turn_order if token != game.current_drawer)

    correct, _ = game.submit_guess(guesser, game.word)

    assert correct is True
    assert game.guess_times[guesser] == 12.5


def test_submit_guess_wrong_word():
    game = make_game()
    game.start_next_turn()
    game.choose_word(game.current_drawer, game.word_choices[0])
    game.set_phase_deadline(DRAWING_SECONDS)
    correct, points = game.submit_guess("p1", "definitely-wrong")
    assert correct is False
    assert points == 0


def test_no_scoring_marks_correct_guesses_without_awarding_points():
    game = Game(turn_order=["drawer", "guesser"], scoring_mode="none")
    game.start_next_turn()
    game.choose_word(game.current_drawer, game.word_choices[0])
    game.set_phase_deadline(DRAWING_SECONDS)

    correct, points = game.submit_guess("guesser", game.word)

    assert correct is True
    assert points == 0
    assert game.guess_points == {"guesser": 0}
    assert game.end_round() == 0


def test_end_round_awards_drawer_bonus_per_guesser():
    game = make_game(n_players=3)
    game.start_next_turn()
    game.choose_word(game.current_drawer, game.word_choices[0])
    game.set_phase_deadline(DRAWING_SECONDS)
    others = [t for t in game.turn_order if t != game.current_drawer]
    for token in others:
        game.submit_guess(token, game.word)
    bonus = game.end_round()
    assert bonus == 300 * len(others)
    assert game.phase == Phase.ROUND_END


def test_end_round_is_idempotent():
    game = make_game(n_players=3)
    game.start_next_turn()
    game.choose_word(game.current_drawer, game.word_choices[0])
    game.set_phase_deadline(DRAWING_SECONDS)
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    game.submit_guess(guesser, game.word)

    assert game.end_round() is not None
    assert game.end_round() is None


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


def test_record_stroke_respects_history_limit(monkeypatch):
    monkeypatch.setattr("app.game.MAX_STROKE_RECORDS", 1)
    game = make_game()

    assert game.record_stroke("draw_shape", {"shape": "rectangle"}) is True
    assert game.record_stroke("draw_shape", {"shape": "ellipse"}) is False
    assert len(game.strokes) == 1


def test_undo_last_stroke_removes_entire_pen_stroke():
    game = make_game()
    game.record_stroke("draw_start", pen_start())
    game.record_stroke("draw_move", {"points": [{"x": 0.1, "y": 0.1}]})
    game.record_stroke("draw_end", {})
    assert game.undo_last_stroke() is True
    assert game.strokes == []


def test_undo_last_stroke_only_removes_most_recent_stroke():
    game = make_game()
    game.record_stroke("draw_start", pen_start())
    game.record_stroke("draw_end", {})
    game.record_stroke("draw_start", pen_start(1, 1))
    game.record_stroke("draw_move", {"points": [{"x": 0.2, "y": 0.2}]})
    game.record_stroke("draw_end", {})
    assert game.undo_last_stroke() is True
    assert [s["event"] for s in game.strokes] == ["draw_path"]


def test_undo_last_stroke_removes_single_shape_event():
    game = make_game()
    game.record_stroke("draw_start", pen_start())
    game.record_stroke("draw_end", {})
    game.record_stroke("draw_shape", {"shape": "rectangle"})
    assert game.undo_last_stroke() is True
    assert [s["event"] for s in game.strokes] == ["draw_path"]


def test_undo_last_stroke_repeatedly_empties_history():
    game = make_game()
    game.record_stroke("draw_shape", {"shape": "ellipse"})
    game.record_stroke("draw_start", pen_start())
    game.record_stroke("draw_end", {})
    assert game.undo_last_stroke() is True
    assert game.undo_last_stroke() is True
    assert game.strokes == []
    assert game.undo_last_stroke() is False


def test_clear_canvas_stroke_and_undo_clear():
    game = make_game()
    game.record_stroke("draw_start", pen_start())
    game.record_stroke("draw_end", {})
    assert game.clear_canvas_stroke() is True
    assert [s["event"] for s in game.strokes] == ["draw_path", "clear_canvas"]

    # Undo recovers drawing history to before Clear was pressed
    assert game.undo_last_stroke() is True
    assert [s["event"] for s in game.strokes] == ["draw_path"]


def test_new_stroke_after_clear_resets_pre_clear_history():
    game = make_game()
    game.record_stroke("draw_start", pen_start())
    game.record_stroke("draw_end", {})
    game.clear_canvas_stroke()

    # Starting a new stroke after Clear resets pre-clear history
    game.record_stroke("draw_start", pen_start(1, 1))
    assert game.strokes[0]["payload"]["points"][0]["x"] == 1


def test_masked_word_returns_unmasked_for_drawer_and_correct_guesser():
    game = make_game(n_players=3)
    game.start_next_turn()
    game._set_word("cat")
    drawer = game.current_drawer
    guesser1, guesser2 = [t for t in game.turn_order if t != drawer]

    # Drawer sees unmasked word
    assert game.masked_word(drawer) == "cat"
    # Other guessers see masked word
    assert game.masked_word(guesser1) != "cat"

    # Correct guesser sees unmasked word
    game.submit_guess(guesser1, "cat")
    assert game.masked_word(guesser1) == "cat"
    assert game.masked_word(guesser2) != "cat"


def test_start_next_turn_skips_afk_drawers():
    game = make_game(n_players=3)
    p1, p2, p3 = game.turn_order
    # p2 is marked AFK
    game.start_next_turn(afk_tokens={p2})
    assert game.current_drawer == p1

    # Next turn skips p2 and chooses p3
    game.start_next_turn(afk_tokens={p2})
    assert game.current_drawer == p3




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
    game.submit_guess(guesser, game.word)
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

    masked_for_buyer = game.masked_word(buyer)
    masked_for_other = game.masked_word(other)
    masked_for_no_one = game.masked_word()
    assert masked_for_buyer.count("_") == len(game.word) - 2
    assert masked_for_other.count("_") == len(game.word)
    assert masked_for_no_one.count("_") == len(game.word)


def test_buy_wheel_letter_still_recorded_when_letter_absent():
    game = make_hint_game("testing", "wheel")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    assert game.buy_wheel_letter(guesser, "z") is True  # not in "testing"
    assert game.masked_word(guesser).count("_") == len(game.word)
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
    # A word pool with equal frequency for the vowel and consonant compared,
    # so only the flat vowel/consonant baseline (not frequency) affects price.
    game = make_hint_game("aabb", "wheel")
    assert game.letter_price("a") > game.letter_price("b")


def test_letter_price_rarer_letter_costs_less():
    # "t" appears far more often than "z" across this pool, so "z" (rarer)
    # should cost less than "t", both being consonants - use two consonants
    # to isolate the frequency effect from the vowel/consonant baseline.
    game = make_hint_game("test", "wheel")
    game.word_pool = ["ttttt", "ttttt", "ttttz"]
    assert game.letter_price("z") < game.letter_price("t")


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


def test_guess_hint_partial_multiple_short_words_reach_min_letters():
    game = make_close_guess_game("tiny red ant")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # Neither "red" nor "ant" alone reaches CLOSE_GUESS_MIN_CORRECT_LETTERS,
    # but their combined length (6) does.
    assert game.guess_hint(guesser, "huge red ant") == "partial"


def test_guess_hint_partial_requires_min_correct_letters():
    game = make_close_guess_game("tiny red ant")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # Only one short word ("red", 3 letters) matches exactly - below
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
    # Missing the last word entirely, but the word-count difference is only
    # 1, which is now tolerated - "big", "giant" and "purple" all match.
    assert game.guess_hint(guesser, "big giant purple") == "partial"


def test_guess_hint_partial_rejects_word_count_diff_over_one():
    game = make_close_guess_game("big giant purple octopus")
    guesser = next(t for t in game.turn_order if t != game.current_drawer)
    # Missing 2 of the 4 words: word-count difference is 2, too large to be
    # tolerated, so the partial-word check is skipped entirely.
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
    # Duplicate words are capped at the lower count per word (multiset
    # intersection): 1x "red" (guess has 1, target has 2) + 1x "panda"
    # (guess has 2, target has 1) = 3 + 5 = 8 correct letters total.
    assert game.guess_hint(guesser, "red panda panda") == "partial"


def test_new_scoring_system_guesser_and_drawer_scores():
    game = make_game(n_players=3)
    game.start_next_turn()
    game.choose_word(game.current_drawer, game.word_choices[0])

    others = [t for t in game.turn_order if t != game.current_drawer]
    g1, g2 = others[0], others[1]

    # Guesser 1 guesses at start (t = 0, remaining = 80s) -> 300 points
    game.remaining_seconds = lambda: DRAWING_SECONDS
    _, p1 = game.submit_guess(g1, game.word)
    assert p1 == 300

    # Guesser 2 guesses halfway through (t = 40s, remaining = 40s) -> 200 points
    game.remaining_seconds = lambda: DRAWING_SECONDS / 2
    _, p2 = game.submit_guess(g2, game.word)
    assert p2 == 200

    # Drawer score equals sum of guesser scores (300 + 200 = 500)
    drawer_score = game.end_round()
    assert drawer_score == 500


def test_hide_masked_prompt_returns_question_marks():
    game = Game(turn_order=["p0", "p1"], rounds_total=1, hide_masked_prompt=True)
    game.start_next_turn()
    word = game.word_choices[0]
    game.choose_word("p0", word)

    # Drawer sees full word
    assert game.masked_word("p0") == word

    # Guesser sees ???
    assert game.masked_word("p1") == "???"

    # Spectator without solution sees ???
    assert game.masked_word("spec", is_spectator=True, spectators_see_solution=False) == "???"

    # Spectator with solution sees full word
    assert game.masked_word("spec", is_spectator=True, spectators_see_solution=True) == word

    # Guesser who answered correctly sees full word
    game.submit_guess("p1", word)
    assert game.masked_word("p1") == word

