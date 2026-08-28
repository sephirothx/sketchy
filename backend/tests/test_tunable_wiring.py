"""Each tunable reaches the value the running server actually consults.

The registry is only worth its indirection if writing through it moves the
number a handler reads. That is not obvious for any of these: several were
constants imported by name, which binds a copy at import; two were argument
defaults, bound when the function was defined; and three are held inside rate
limiters that used to take their ceiling in a constructor. A test that only
checked `describe()` would pass for every one of those while the server went on
using the old number, so each of these writes through the panel's own path and
then asks the thing that enforces it.
"""
from __future__ import annotations

import pytest

from app.flow_timing import FlowTiming
from app.handlers.budgets import CommandBudgetPolicy
from app.game import Game
from app.presenters import turn_ended_payload
from app.rooms import RoomManager, room_defaults as live_room_defaults
from app.services.room_quotas import (
    RoomCapacityService,
    RoomQuotaExceeded,
    RoomQuotaService,
)
from app.services.runtime_settings import TunableError
from app.services.shutdown import ShutdownCoordinator
from app.services.tunables import build_runtime_settings


def a_registry(**parts):
    return build_runtime_settings(
        budgets=parts.pop("budgets", CommandBudgetPolicy()), environ={}, **parts
    )


@pytest.fixture
def tuned_room_defaults(monkeypatch):
    """A registry wired to the process's own new-room defaults, then restored.

    Deliberately the live object rather than a fresh one. `handlers/payloads`
    and `rooms` both hold a reference to it, so a test that rebound the *name*
    in one module would prove nothing about the other - which is the same
    import-binding trap this whole registry exists to avoid.
    """
    for name, value in vars(live_room_defaults).items():
        monkeypatch.setattr(live_room_defaults, name, value)
    return a_registry(room_defaults=live_room_defaults)


# ------------------------------------------------------------------- budgets


def test_a_budget_change_moves_what_the_guard_will_read():
    policy = CommandBudgetPolicy()
    settings = a_registry(budgets=policy)
    settings.set("budget.drawing", 300)
    assert policy.for_command("draw").limit == 300


# ------------------------------------------------------------------ ceilings


def test_the_global_room_ceiling_refuses_at_its_new_value():
    rooms = RoomManager()
    quotas = RoomQuotaService(rooms)
    settings = a_registry(quotas=quotas, capacity=RoomCapacityService())
    for _ in range(2):
        rooms.create_room()

    settings.set("rooms.global_limit", 2)
    with pytest.raises(RoomQuotaExceeded):
        quotas.check_capacity("someone")

    settings.set("rooms.global_limit", 3)
    quotas.check_capacity("someone")


def test_the_socket_ceiling_moves_with_the_setting():
    capacity = RoomCapacityService()
    settings = a_registry(quotas=RoomQuotaService(RoomManager()), capacity=capacity)
    settings.set("rooms.socket_limit", 10)
    for sid in range(10):
        capacity.note_socket_opened(str(sid))
    assert capacity.has_socket_capacity()
    capacity.note_socket_opened("one-too-many")
    assert not capacity.has_socket_capacity()


def test_a_join_limit_change_reaches_the_limiter_not_just_the_field():
    """The ceiling used to be copied into the limiter's constructor.

    Setting the field alone would leave the limiter enforcing whatever it was
    built with - so this asks the limiter, which is what actually refuses.
    """
    capacity = RoomCapacityService()
    settings = a_registry(quotas=RoomQuotaService(RoomManager()), capacity=capacity)
    settings.set("rooms.joins_per_socket", 2)
    assert capacity.admits_a_join("socket")
    assert capacity.admits_a_join("socket")
    assert not capacity.admits_a_join("socket")


def test_lowering_a_limit_does_not_hand_back_a_fresh_allowance():
    """Rebuilding the limiter would discard the windows already open.

    Which would make lowering a ceiling *grant* the caller who has just spent
    theirs a new one - the opposite of what lowering it is for.
    """
    capacity = RoomCapacityService()
    settings = a_registry(quotas=RoomQuotaService(RoomManager()), capacity=capacity)
    for _ in range(5):
        capacity.admits_a_join("socket")
    settings.set("rooms.joins_per_socket", 3)
    assert not capacity.admits_a_join("socket")


def test_the_room_creation_rate_is_readable_without_a_database():
    """Only the creation *rate* needs a persistent bucket; the rest is memory."""
    quotas = RoomQuotaService(RoomManager())
    settings = a_registry(quotas=quotas, capacity=RoomCapacityService())
    assert settings.value("rooms.creations_per_hour") == 10
    settings.set("rooms.creations_per_hour", 25)
    assert quotas.creations_per_hour == 25


# ----------------------------------------------------------------- flow timing


def test_a_phase_length_change_reaches_the_payload_the_clients_read(monkeypatch):
    """`turn_ended_payload` imported this constant by name, so it held a copy.

    The clients count the results screen down from the number in this payload
    rather than from one of their own, so this is the value that decides how
    long the pause actually is.
    """
    flow = FlowTiming()
    monkeypatch.setattr("app.presenters.timing", flow)
    settings = a_registry(flow=flow)

    manager = RoomManager()
    room = manager.create_room(name="Studio", rounds=1)
    manager.add_player(room, "Marta", user_id="u-marta")
    room.game = Game(turn_order=[p.id for p in room.player_list()], rounds_total=1)
    room.game.prompt = "lighthouse"
    room.game.phase_deadline = None

    settings.set("turn.results_seconds", 12)
    assert turn_ended_payload(room)["seconds"] == 12


def test_the_reconnect_grace_is_stated_once():
    """It used to be declared in two modules; one of them was never read."""
    from app.handlers import connection
    from app.services import game_flow

    assert not hasattr(connection, "RECONNECT_GRACE_SECONDS")
    assert not hasattr(game_flow, "RECONNECT_GRACE_SECONDS")


def test_the_turn_results_pause_is_still_configurable_by_environment():
    """The E2E harness sets `TURN_RESULTS_SECONDS`; that must keep working."""
    flow = FlowTiming()
    settings = build_runtime_settings(
        budgets=CommandBudgetPolicy(),
        flow=flow,
        environ={"TURN_RESULTS_SECONDS": "0.5"},
    )
    assert flow.turn_results_seconds == 0.5
    assert settings.source("turn.results_seconds") == "environment"


# --------------------------------------------------------------- room defaults


def test_a_new_room_is_made_with_the_tuned_defaults(tuned_room_defaults):
    """These were argument defaults, bound when the function was defined."""
    tuned_room_defaults.set("room_defaults.drawing_seconds", 60)
    tuned_room_defaults.set("room_defaults.max_players", 12)
    tuned_room_defaults.set("room_defaults.rounds", 5)

    room = RoomManager().create_room()
    assert (room.drawing_seconds, room.max_players, room.rounds) == (60, 12, 5)


def test_the_create_form_offers_the_tuned_defaults(tuned_room_defaults):
    """A pydantic `default=` is evaluated when the model class is built."""
    from app.handlers.payloads import RoomSettingsFields

    tuned_room_defaults.set("room_defaults.rounds", 7)
    assert RoomSettingsFields().rounds == 7


def test_the_range_a_host_chooses_from_is_not_tunable():
    """The frontend duplicates those bounds, which makes them a contract."""
    settings = a_registry(room_defaults=live_room_defaults)
    assert "room_defaults.max_players" in settings
    for name in settings.names():
        assert "options" not in name and "_min" not in name and "_max" not in name


# -------------------------------------------------------------------- shutdown


def test_the_drain_window_moves_for_the_next_shutdown():
    coordinator = ShutdownCoordinator(session_factory=None, room_manager=RoomManager())
    coordinator.begin_startup(drain_seconds=30)
    settings = a_registry(shutdown=coordinator)
    settings.set("shutdown.drain_seconds", 12.5)
    assert coordinator.drain_seconds == 12.5


def test_the_drain_window_keeps_the_bounds_the_environment_had():
    """R-SHUT-03 fixes the range at 0-300 however the value arrives."""
    coordinator = ShutdownCoordinator(session_factory=None, room_manager=RoomManager())
    coordinator.begin_startup(drain_seconds=30)
    settings = a_registry(shutdown=coordinator)
    with pytest.raises(TunableError, match="between 0 and 300"):
        settings.set("shutdown.drain_seconds", 301)
    assert coordinator.drain_seconds == 30


def test_the_environment_still_supplies_the_boot_drain():
    coordinator = ShutdownCoordinator(session_factory=None, room_manager=RoomManager())
    coordinator.begin_startup(drain_seconds=30)
    settings = build_runtime_settings(
        budgets=CommandBudgetPolicy(),
        shutdown=coordinator,
        environ={"SHUTDOWN_DRAIN_SECONDS": "0"},
    )
    assert coordinator.drain_seconds == 0
    assert settings.source("shutdown.drain_seconds") == "environment"
