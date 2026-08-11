from app.canvas_history import encode_canvas_history
from app.rooms import DrawingRecapEntry, NAME_COLOR_PATTERN, RoomFullError, RoomManager


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


def test_add_player_uses_requested_name_color_or_random_default():
    rm = RoomManager()
    room = rm.create_room(name="Room")

    chosen = rm.add_player(room, "Alice", name_color="#AABBCC")
    generated = rm.add_player(room, "Bob", name_color="not-a-color")

    assert chosen.name_color == "#aabbcc"
    assert NAME_COLOR_PATTERN.fullmatch(generated.name_color)


def test_add_player_respects_max_players():
    rm = RoomManager()
    room = rm.create_room(name="Room", is_public=True, max_players=1)
    rm.add_player(room, "Alice")
    try:
        rm.add_player(room, "Bob")
        assert False, "expected RoomFullError"
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
    room = rm.create_room(name="Room", is_public=True, max_players=1, spectators_see_solution=True)
    p1 = rm.add_player(room, "Alice")
    assert p1.is_spectator is False

    # Active player join fails when full
    try:
        rm.add_player(room, "Bob", is_spectator=False)
        assert False, "expected RoomFullError"
    except RoomFullError:
        pass

    # Spectator can join full room
    spec = rm.add_player(room, "Charlie", is_spectator=True)
    assert spec.is_spectator is True
    summary = room.to_public_summary()
    assert summary["spectatorsSeeSolution"] is True
    assert summary["playerCount"] == 1
    assert summary["spectatorCount"] == 1
    assert summary["isFull"] is True
    assert room.to_state_payload()["spectatorsSeeSolution"] is True
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
            round_number=1,
            turn_number=1,
            drawer_id=drawer.id,
            drawer_nickname=drawer.nickname,
            drawer_name_color=drawer.name_color,
            word="apple",
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
        "word": "apple",
        "actionCount": 0,
    }]
    assert "canvas" not in payload["lastGameDrawings"][0]

    room.state = "playing"
    assert room.to_state_payload()["lastGameDrawings"] == []

