import pytest

from app.identifiers import generate_uuid7
from app.canvas_history import encode_canvas_history
from app.game import Game
from app.domain_values import HINT_MODES, SCORING_MODES
from app.rooms import (
    ANONYMOUS_NAME_COLOR,
    GUESS_DEDUP_WINDOW,
    DrawingRecapEntry,
    NAME_COLOR_PATTERN,
    RoomFullError,
    RoomManager,
    resolve_hint_mode,
    MAX_RECAP_CANVAS_BYTES,
)


def test_create_room_generates_unique_code():
    rm = RoomManager()
    room1 = rm.create_room(name="Room 1", is_public=True)
    room2 = rm.create_room(name="Room 2", is_public=True)
    assert room1.code != room2.code
    assert len(room1.code) == 6


def test_create_room_uses_default_drawing_time_and_hint_mode():
    rm = RoomManager()
    room = rm.create_room(name="Room", is_public=True)
    assert room.max_players == 8
    assert room.rounds == 3
    assert room.drawing_seconds == 90
    assert room.hint_mode == "checkpoints"


def test_canvas_generation_is_monotonic_across_game_instances():
    room = RoomManager().create_room(name="Room", is_public=True)

    first_game = Game(turn_order=["first"])
    first_game.start_next_turn(
        canvas_generation=room.allocate_canvas_generation(),
    )
    replacement_game = Game(turn_order=["second"])
    replacement_game.start_next_turn(
        canvas_generation=room.allocate_canvas_generation(),
    )

    assert first_game.canvas.generation == 1
    assert replacement_game.canvas.generation == 2
    assert room.canvas_generation == 2


def test_nearest_drawing_seconds_snaps_to_allowed_presets():
    from app.rooms import nearest_drawing_seconds

    assert nearest_drawing_seconds(90) == 90
    assert nearest_drawing_seconds(100) == 90
    assert nearest_drawing_seconds(250) == 240
    assert nearest_drawing_seconds(280) == 300
    assert nearest_drawing_seconds(1) == 15


def test_add_player_first_is_host():
    rm = RoomManager()
    room = rm.create_room(name="Room", is_public=True)
    p1 = rm.add_player(room, "Alice")
    p2 = rm.add_player(room, "Bob")
    assert p1.is_host is True
    assert p2.is_host is False


def test_registered_player_uses_requested_name_color_or_random_default():
    rm = RoomManager()
    room = rm.create_room(name="Room")

    chosen = rm.add_player(room, "Alice", name_color="#EF3482", is_anonymous=False)
    generated = rm.add_player(room, "Bob", name_color="not-a-color", is_anonymous=False)

    assert chosen.name_color == "#ef3482"
    assert NAME_COLOR_PATTERN.fullmatch(generated.name_color)


def test_anonymous_players_are_forced_to_the_guest_color():
    rm = RoomManager()
    room = rm.create_room(name="Room")

    guest = rm.add_player(room, "Alice", name_color="#EF3482")

    assert guest.is_anonymous is True
    assert guest.name_color == ANONYMOUS_NAME_COLOR


def test_add_player_respects_max_players():
    rm = RoomManager()
    room = rm.create_room(name="Room", is_public=True, max_players=1)
    rm.add_player(room, "Alice")
    try:
        rm.add_player(room, "Bob")
        raise AssertionError("expected RoomFullError")
    except RoomFullError:
        pass


def test_remove_player_promotes_new_host():
    rm = RoomManager()
    room = rm.create_room(name="Room", is_public=True)
    p1 = rm.add_player(room, "Alice")
    p2 = rm.add_player(room, "Bob")
    rm.remove_player(room, p1.id)
    assert room.players[p2.id].is_host is True


def test_list_public_rooms_excludes_private():
    rm = RoomManager()
    rm.create_room(name="Public", is_public=True)
    rm.create_room(name="Private", is_public=False)
    public = rm.list_public_rooms()
    assert len(public) == 1
    assert public[0]["name"] == "Public"


def test_remove_room_if_empty():
    rm = RoomManager()
    room = rm.create_room(name="Room", is_public=True)
    p1 = rm.add_player(room, "Alice")
    p1.connected = False
    rm.remove_room_if_empty(room.id)
    assert room.id not in rm.rooms


def test_get_room_by_code_case_insensitive():
    rm = RoomManager()
    room = rm.create_room(name="Room", is_public=False)
    found = rm.get_room_by_code(room.code.lower())
    assert found is room


def test_scoring_mode_is_in_room_payloads():
    rm = RoomManager()
    room = rm.create_room(name="Casual", is_public=True, scoring_mode="none")
    player = rm.add_player(room, "Alice")

    assert room.to_public_summary()["scoringMode"] == "none"
    assert room.to_state_payload()["scoringMode"] == "none"
    assert player.score == 0


@pytest.mark.parametrize("scoring_mode", ["none", "default", "pressure"])
def test_every_scoring_mode_starts_players_at_zero(scoring_mode):
    """Hints are bought on credit, so no mode needs an opening balance."""
    rm = RoomManager()
    room = rm.create_room(name="Racy", is_public=True, scoring_mode=scoring_mode)
    player = rm.add_player(room, "Alice")

    assert room.to_public_summary()["scoringMode"] == scoring_mode
    assert room.to_state_payload()["scoringMode"] == scoring_mode
    assert player.score == 0


def test_create_room_assigns_funny_random_name_when_unspecified():
    from app.rooms import ROOM_NAME_ADJECTIVES, ROOM_NAME_NOUNS

    rm = RoomManager()
    room1 = rm.create_room(name="", is_public=True)
    room2 = rm.create_room(name="   ", is_public=True)
    room3 = rm.create_room(is_public=True)

    for r in (room1, room2, room3):
        assert r.name and isinstance(r.name, str)
        assert any(adj in r.name for adj in ROOM_NAME_ADJECTIVES)
        assert any(noun in r.name for noun in ROOM_NAME_NOUNS)


def test_spectator_can_join_full_room_and_option_in_payload():
    rm = RoomManager()
    room = rm.create_room(name="Room", is_public=True, max_players=1, spectators_see_prompt=True)
    p1 = rm.add_player(room, "Alice")
    assert p1.is_spectator is False

    # Active player join fails when full
    try:
        rm.add_player(room, "Bob", is_spectator=False)
        raise AssertionError("expected RoomFullError")
    except RoomFullError:
        pass

    # Spectator can join full room
    spec = rm.add_player(room, "Charlie", is_spectator=True)
    assert spec.is_spectator is True
    summary = room.to_public_summary()
    assert summary["spectatorsSeePrompt"] is True
    assert summary["playerCount"] == 1
    assert summary["spectatorCount"] == 1
    assert summary["isFull"] is True
    assert room.to_state_payload()["spectatorsSeePrompt"] is True
    players_payload = room.to_state_payload()["players"]
    assert any(p["nickname"] == "Charlie" and p["isSpectator"] is True for p in players_payload)


def test_remove_player_cleans_up_votes():
    rm = RoomManager()
    room = rm.create_room(name="Room", is_public=True)
    p1 = rm.add_player(room, "Alice")
    p2 = rm.add_player(room, "Bob")

    p2.kick_votes.add(p1.id)
    p2.afk_votes.add(p1.id)

    rm.remove_player(room, p1.id)
    assert p1.id not in p2.kick_votes
    assert p1.id not in p2.afk_votes


def test_moderation_population_includes_afk_players_and_target_but_not_spectators():
    rm = RoomManager()
    room = rm.create_room(name="Room", is_public=True)
    voter = rm.add_player(room, "Voter")
    target = rm.add_player(room, "Target")
    afk_voter = rm.add_player(room, "AFK")
    spectator = rm.add_player(room, "Spectator", is_spectator=True)
    afk_voter.is_afk = True

    moderation = room.to_state_payload()["moderation"]

    assert moderation == {
        "eligibleVoterIds": [voter.id, target.id, afk_voter.id],
        "requiredVotes": 2,
    }
    assert spectator.id not in moderation["eligibleVoterIds"]

    extra_spectator = rm.add_player(room, "Another spectator", is_spectator=True)
    assert extra_spectator.id not in room.to_state_payload()["moderation"]["eligibleVoterIds"]
    assert room.to_state_payload()["moderation"]["requiredVotes"] == 2


def test_create_room_with_hide_masked_prompt_forces_hints_off():
    rm = RoomManager()
    room = rm.create_room(name="Hidden Room", hide_masked_prompt=True, hint_mode="checkpoints")
    assert room.hide_masked_prompt is True
    assert room.hint_mode == "none"
    assert room.to_public_summary()["hideMaskedPrompt"] is True
    assert room.to_state_payload()["hideMaskedPrompt"] is True


def test_room_payload_exposes_only_recap_metadata_while_waiting():
    rm = RoomManager()
    room = rm.create_room(name="Room")
    drawer = rm.add_player(room, "Drawer")
    room.last_game_drawings.append(
        DrawingRecapEntry(
            turn_id=str(generate_uuid7()),
            round_number=1,
            turn_number=1,
            drawer_id=drawer.id,
            drawer_nickname=drawer.nickname,
            drawer_name_color=drawer.name_color,
            prompt="apple",
            action_count=0,
            canvas_history=encode_canvas_history([]),
        )
    )

    payload = room.to_state_payload()
    assert payload["lastGameDrawings"] == [{
        "index": 0,
        "roundNumber": 1,
        "turnNumber": 1,
        "drawerId": drawer.id,
        "drawerNickname": "Drawer",
        "drawerNameColor": drawer.name_color,
        "prompt": "apple",
        "actionCount": 0,
        "available": True,
    }]
    assert "canvas" not in payload["lastGameDrawings"][0]

    room.state = "playing"
    assert room.to_state_payload()["lastGameDrawings"] == []


def recap_entry(turn: int, canvas: bytes) -> DrawingRecapEntry:
    return DrawingRecapEntry(
        turn_id=str(generate_uuid7()),
        round_number=1,
        turn_number=turn,
        drawer_id=f"drawer-{turn}",
        drawer_nickname=f"Drawer {turn}",
        drawer_name_color=None,
        prompt=f"prompt-{turn}",
        action_count=1,
        canvas_history=canvas,
    )


def test_a_full_length_game_of_real_drawings_keeps_every_one():
    """The budget must never bind on a game anybody actually played."""
    room = RoomManager().create_room(name="Room", is_public=True)
    typical = b"x" * 10_000  # what a real drawing measures

    # Sixteen players over ten rounds: the longest game the settings allow.
    for turn in range(160):
        room.record_drawing_recap(recap_entry(turn, typical))

    assert all(drawing.is_available for drawing in room.last_game_drawings)


def test_a_game_that_outgrows_its_budget_keeps_what_it_showed_first():
    """A recap must not rearrange itself while somebody is reading it."""
    room = RoomManager().create_room(name="Room", is_public=True)
    huge = b"x" * (MAX_RECAP_CANVAS_BYTES // 4)

    for turn in range(6):
        room.record_drawing_recap(recap_entry(turn, huge))

    # Every turn is still listed, with its prompt and its drawer.
    assert len(room.last_game_drawings) == 6
    assert [d.prompt for d in room.last_game_drawings] == [f"prompt-{t}" for t in range(6)]
    # Four of these fill the budget exactly; the turns after it are the ones
    # turned away, and nothing already kept was disturbed.
    kept = [d.turn_number for d in room.last_game_drawings if d.is_available]
    assert kept == [0, 1, 2, 3]
    retained = sum(len(d.canvas_history or b"") for d in room.last_game_drawings)
    assert retained <= MAX_RECAP_CANVAS_BYTES


def test_the_recap_says_which_drawings_it_still_holds():
    room = RoomManager().create_room(name="Room", is_public=True)
    # Each of these is over half the budget, so no two can be held at once.
    huge = b"x" * (MAX_RECAP_CANVAS_BYTES // 2 + 1)
    for turn in range(3):
        room.record_drawing_recap(recap_entry(turn, huge))

    availability = [entry["available"] for entry in room.drawing_recap_metadata()]
    assert availability == [True, False, False]
    # Turning one drawing away does not close the recap: a small one still
    # fits behind it, and what was already kept is untouched.
    room.record_drawing_recap(recap_entry(3, b"tiny"))
    assert [
        entry["available"] for entry in room.drawing_recap_metadata()
    ] == [True, False, False, True]


def test_starting_a_game_gives_the_whole_budget_back():
    room = RoomManager().create_room(name="Room", is_public=True)
    for turn in range(4):
        room.record_drawing_recap(recap_entry(turn, b"x" * (MAX_RECAP_CANVAS_BYTES // 3)))
    assert not all(d.is_available for d in room.last_game_drawings)

    # `_start_fresh_game` clears the list; the next game starts from nothing.
    room.last_game_drawings = []
    room.record_drawing_recap(recap_entry(0, b"x" * (MAX_RECAP_CANVAS_BYTES // 3)))
    assert room.last_game_drawings[0].is_available


def _seat(rm, room, nickname, **flags):
    """Add a player, then apply the connected/AFK/spectator flags under test."""
    player = rm.add_player(room, nickname, is_spectator=flags.pop("is_spectator", False))
    for name, value in flags.items():
        setattr(player, name, value)
    return player


def test_seated_players_keeps_absent_players_and_drops_spectators():
    rm = RoomManager()
    room = rm.create_room(name="Room")
    here = _seat(rm, room, "Here")
    away = _seat(rm, room, "Away", connected=False)
    resting = _seat(rm, room, "Resting", is_afk=True)
    _seat(rm, room, "Watcher", is_spectator=True)

    # A seat is held by whoever took it, whether or not they are at it: the
    # count decides whether the room is full.
    assert [p.id for p in room.seated_players()] == [here.id, away.id, resting.id]


def test_active_players_are_the_ones_the_game_waits_on():
    rm = RoomManager()
    room = rm.create_room(name="Room")
    here = _seat(rm, room, "Here")
    _seat(rm, room, "Away", connected=False)
    _seat(rm, room, "Resting", is_afk=True)
    _seat(rm, room, "Watcher", is_spectator=True)
    _seat(rm, room, "AwayWatcher", is_spectator=True, connected=False)

    assert [p.id for p in room.active_players()] == [here.id]


def test_eligible_guessers_is_the_active_players_minus_the_drawer():
    rm = RoomManager()
    room = rm.create_room(name="Room")
    drawer = _seat(rm, room, "Drawer")
    guesser = _seat(rm, room, "Guesser")
    _seat(rm, room, "Away", connected=False)
    _seat(rm, room, "Resting", is_afk=True)
    _seat(rm, room, "Watcher", is_spectator=True)

    room.game = Game(turn_order=[drawer.id, guesser.id])
    room.game.current_drawer = drawer.id

    assert [p.id for p in room.eligible_guessers()] == [guesser.id]


def test_eligible_guessers_outside_a_turn_excludes_nobody():
    rm = RoomManager()
    room = rm.create_room(name="Room")
    first = _seat(rm, room, "First")
    second = _seat(rm, room, "Second")

    # No game, and a game between turns, both leave every active player owing
    # a guess - there is no drawer to subtract.
    assert [p.id for p in room.eligible_guessers()] == [first.id, second.id]
    room.game = Game(turn_order=[first.id, second.id])
    assert room.game.current_drawer is None
    assert [p.id for p in room.eligible_guessers()] == [first.id, second.id]


def test_eligible_guessers_drops_a_drawer_who_went_afk_only_once():
    rm = RoomManager()
    room = rm.create_room(name="Room")
    drawer = _seat(rm, room, "Drawer")
    guesser = _seat(rm, room, "Guesser")
    room.game = Game(turn_order=[drawer.id, guesser.id])
    room.game.current_drawer = drawer.id

    drawer.is_afk = True

    # The drawer is excluded by both rules at once; the count must not go
    # negative or double-subtract.
    assert [p.id for p in room.eligible_guessers()] == [guesser.id]


def test_majority_of_needs_more_than_half():
    from app.rooms import majority_of

    assert [majority_of(n) for n in range(0, 9)] == [1, 1, 2, 2, 3, 3, 4, 4, 5]
    for population in range(1, 50):
        assert majority_of(population) * 2 > population


@pytest.mark.parametrize("hint_mode", HINT_MODES)
@pytest.mark.parametrize("scoring_mode", SCORING_MODES)
def test_a_hidden_prompt_leaves_nothing_to_hint_at(hint_mode, scoring_mode):
    assert resolve_hint_mode(hint_mode, scoring_mode, True) == "none"


@pytest.mark.parametrize("hint_mode", ("purchase", "wheel"))
def test_a_room_that_does_not_score_cannot_charge_for_hints(hint_mode):
    assert resolve_hint_mode(hint_mode, "none", False) == "none"


@pytest.mark.parametrize("scoring_mode", SCORING_MODES)
def test_free_hints_survive_every_scoring_mode(scoring_mode):
    # Checkpoint hints cost nothing, so an unscored room can still show them.
    assert resolve_hint_mode("checkpoints", scoring_mode, False) == "checkpoints"


@pytest.mark.parametrize("hint_mode", HINT_MODES)
@pytest.mark.parametrize("scoring_mode", ("default", "pressure"))
def test_a_scoring_room_keeps_the_hint_mode_it_asked_for(hint_mode, scoring_mode):
    assert resolve_hint_mode(hint_mode, scoring_mode, False) == hint_mode


@pytest.mark.parametrize("hint_mode", HINT_MODES)
@pytest.mark.parametrize("scoring_mode", SCORING_MODES)
@pytest.mark.parametrize("hide_masked_prompt", (True, False))
def test_resolving_a_hint_mode_settles_in_one_pass(
    hint_mode, scoring_mode, hide_masked_prompt
):
    once = resolve_hint_mode(hint_mode, scoring_mode, hide_masked_prompt)
    assert once in HINT_MODES
    assert resolve_hint_mode(once, scoring_mode, hide_masked_prompt) == once


@pytest.mark.parametrize(
    "settings",
    (
        {"hide_masked_prompt": True, "hint_mode": "checkpoints"},
        {"hide_masked_prompt": True, "hint_mode": "wheel"},
        {"scoring_mode": "none", "hint_mode": "purchase"},
        {"scoring_mode": "none", "hint_mode": "wheel"},
    ),
)
def test_create_room_applies_the_whole_hint_rule(settings):
    # create_room is reachable without a payload, so the rule has to hold here
    # and not only at the boundary model.
    room = RoomManager().create_room(name="Room", **settings)
    assert room.hint_mode == "none"


def test_a_seat_remembers_only_a_bounded_window_of_guess_ids():
    """The window exists to stop one retry being processed twice, not to
    remember a turn. A client inventing ids must not be able to grow it, and
    the price of the bound is that an id older than the window is accepted
    again - which no client that retries once, seconds later, ever reaches."""
    rm = RoomManager()
    room = rm.create_room(name="Room")
    player = rm.add_player(room, "Guesser")

    for guess_id in range(GUESS_DEDUP_WINDOW):
        assert player.accept_guess_id("sid-1", guess_id) is True
    assert player.accept_guess_id("sid-1", 0) is False

    assert player.accept_guess_id("sid-1", GUESS_DEDUP_WINDOW) is True
    assert player.accept_guess_id("sid-1", 0) is True, "the window grew without bound"
