from app.rooms import RoomFullError, RoomManager


def test_create_room_generates_unique_code():
    rm = RoomManager()
    room1 = rm.create_room(name="Room 1", is_public=True)
    room2 = rm.create_room(name="Room 2", is_public=True)
    assert room1.code != room2.code
    assert len(room1.code) == 6


def test_add_player_first_is_host():
    rm = RoomManager()
    room = rm.create_room(name="Room", is_public=True)
    p1 = rm.add_player(room, "Alice")
    p2 = rm.add_player(room, "Bob")
    assert p1.is_host is True
    assert p2.is_host is False


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
    rm.remove_player(room, p1.token)
    assert room.players[p2.token].is_host is True


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
