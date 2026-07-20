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
