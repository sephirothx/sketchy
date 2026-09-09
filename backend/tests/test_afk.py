"""The inactivity rule, the ledger it reads, and the sweep that applies it.

The rule itself is a pure function, so these are ordinary calls rather than a
socket server with a clock moved by hand. The sweep gets a fake clock and a
fake `sio`, which is enough: what it does is emit one event or set one flag.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.flow_timing import FlowTiming
from app.game import Game, Phase
from app.rooms import RoomManager
from app.services.afk import (
    CHECK,
    INACTIVITY_EXEMPT_COMMANDS,
    NOTHING,
    RAISE,
    ActivityLedger,
    AfkWatch,
    checkable_players,
    decide,
    sweep_interval_from,
)


class FakeClock:
    """Monotonic seconds the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


TIMING = FlowTiming(afk_inactivity_seconds=300, afk_check_seconds=25)


# --------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------


def test_a_quiet_socket_is_asked_only_once_it_passes_the_window():
    assert decide(idle_seconds=299, check_open_seconds=None, timing=TIMING) == NOTHING
    assert decide(idle_seconds=300, check_open_seconds=None, timing=TIMING) == CHECK


def test_an_open_check_is_raised_only_once_it_lapses():
    assert decide(idle_seconds=310, check_open_seconds=24, timing=TIMING) == NOTHING
    assert decide(idle_seconds=325, check_open_seconds=25, timing=TIMING) == RAISE


def test_an_open_check_is_never_asked_again():
    """A second `afk_check` would restart a countdown the seat is already in."""
    assert decide(idle_seconds=10_000, check_open_seconds=0, timing=TIMING) == NOTHING


def test_the_windows_are_read_from_the_timing_rather_than_baked_in():
    fast = FlowTiming(afk_inactivity_seconds=2, afk_check_seconds=1)
    assert decide(idle_seconds=2, check_open_seconds=None, timing=fast) == CHECK
    assert decide(idle_seconds=3, check_open_seconds=1, timing=fast) == RAISE


def test_the_sweep_never_ticks_coarser_than_the_check_it_measures():
    """Tuned down for a test run, a five-second sweep would overshoot."""
    assert sweep_interval_from(FlowTiming()) == 5.0
    assert sweep_interval_from(FlowTiming(afk_check_seconds=2)) == 1.0
    assert sweep_interval_from(FlowTiming(afk_check_seconds=0.2)) == 0.1


def test_the_sweep_asks_for_its_interval_rather_than_copying_it():
    """A tunable copied at construction is a tunable that cannot be tuned.

    Handlers are registered before the stored settings are applied
    (`main.py`), so a watch that read the interval once would sweep at the
    compiled cadence for the life of the process — and a deployment that
    shortened the check window would find checks staying open past it.
    """
    timing = FlowTiming(afk_check_seconds=25)
    watch = AfkWatch(AsyncMock(), RoomManager(), ActivityLedger(), AsyncMock(), timing=timing)
    assert watch.interval_seconds == 5.0

    timing.afk_check_seconds = 2  # what the admin panel does at runtime
    assert watch.interval_seconds == 1.0, "asked for, not copied"


# --------------------------------------------------------------------------
# The ledger
# --------------------------------------------------------------------------


def test_the_ledger_measures_from_the_last_stamp():
    clock = FakeClock()
    ledger = ActivityLedger(clock=clock)
    ledger.note("sid")
    clock.advance(30)
    assert ledger.idle_seconds("sid") == 30
    ledger.note("sid")
    assert ledger.idle_seconds("sid") == 0


def test_a_socket_with_no_stamp_marks_nobody():
    """A race that forgot a socket must not read as absent since the epoch."""
    assert ActivityLedger().idle_seconds("never-seen") == 0.0


def test_forgetting_a_socket_drops_its_stamp():
    ledger = ActivityLedger()
    ledger.note("sid")
    ledger.forget("sid")
    assert len(ledger) == 0


def test_the_heartbeat_and_the_client_s_own_traffic_are_exempt():
    """Anything the client sends unprompted must not keep a seat alive."""
    assert "session_ping" in INACTIVITY_EXEMPT_COMMANDS
    assert "request_sync_strokes" in INACTIVITY_EXEMPT_COMMANDS
    # And anything a person pressed must.
    for command in ("guess", "send_chat", "draw", "select_prompt", "vote_player"):
        assert command not in INACTIVITY_EXEMPT_COMMANDS


# --------------------------------------------------------------------------
# Who the check applies to
# --------------------------------------------------------------------------


def _room_with(*, spectator=False, afk=False, connected=True):
    manager = RoomManager()
    room = manager.create_room(name="Studio", is_public=True)
    player = manager.add_player(room, "Ann")
    player.sid = "sid-ann"
    player.is_spectator = spectator
    player.is_afk = afk
    player.connected = connected
    return manager, room, player


def test_a_seat_that_is_playing_is_checkable():
    _, room, player = _room_with()
    assert checkable_players(room) == [player]


@pytest.mark.parametrize(
    "kwargs, why",
    [
        ({"spectator": True}, "nothing waits on a spectator"),
        ({"afk": True}, "already the thing the check produces"),
        ({"connected": False}, "the reconnect grace owns a gone socket"),
    ],
)
def test_seats_the_check_leaves_alone(kwargs, why):
    _, room, _ = _room_with(**kwargs)
    assert checkable_players(room) == [], why


# --------------------------------------------------------------------------
# The sweep
# --------------------------------------------------------------------------


def _watch(manager, clock, *, game_flow=None):
    sio = AsyncMock()
    flow = game_flow if game_flow is not None else AsyncMock()
    activity = ActivityLedger(clock=clock)
    watch = AfkWatch(sio, manager, activity, flow, timing=TIMING, clock=clock)
    return sio, watch, activity


@pytest.mark.asyncio
async def test_a_quiet_seat_is_asked_then_marked():
    clock = FakeClock()
    manager, room, player = _room_with()
    sio, watch, activity = _watch(manager, clock)
    activity.note(player.sid)

    clock.advance(299)
    assert (await watch.flush()).is_empty

    clock.advance(1)
    outcome = await watch.flush()
    assert outcome.checked == 1
    sio.emit.assert_awaited_once_with("afk_check", {"seconds": 25}, to="sid-ann")
    assert not player.is_afk, "asked, not yet marked"

    clock.advance(25)
    outcome = await watch.flush()
    assert outcome.raised == 1
    assert player.is_afk


@pytest.mark.asyncio
async def test_answering_the_check_closes_it_and_marks_nobody():
    """The answer is an ordinary command, so it lands in the ledger."""
    clock = FakeClock()
    manager, room, player = _room_with()
    sio, watch, activity = _watch(manager, clock)
    activity.note(player.sid)

    clock.advance(300)
    await watch.flush()
    assert watch.open_checks == 1

    # What `toggle_afk {afk: false}` does at the command door.
    activity.note(player.sid)
    clock.advance(30)
    outcome = await watch.flush()

    assert outcome.is_empty
    assert watch.open_checks == 0
    assert not player.is_afk


@pytest.mark.asyncio
async def test_the_check_is_asked_once_however_long_the_silence_runs():
    clock = FakeClock()
    manager, room, player = _room_with()
    sio, watch, activity = _watch(manager, clock)
    activity.note(player.sid)
    clock.advance(300)

    await watch.flush()
    clock.advance(5)
    await watch.flush()
    clock.advance(5)
    await watch.flush()

    assert sio.emit.await_count == 1, "one question, not one per tick"


@pytest.mark.asyncio
async def test_a_marked_seat_is_not_asked_again():
    clock = FakeClock()
    manager, room, player = _room_with()
    sio, watch, activity = _watch(manager, clock)
    activity.note(player.sid)
    clock.advance(300)
    await watch.flush()
    clock.advance(25)
    await watch.flush()
    await watch.flush()

    assert player.is_afk
    events = [call.args[0] for call in sio.emit.await_args_list]
    assert events.count("afk_check") == 1


@pytest.mark.asyncio
async def test_marking_a_drawer_forfeits_the_turn_wherever_it_lands():
    """`apply_afk_consequences` already does this; the sweep must call it."""
    clock = FakeClock()
    manager, room, player = _room_with()
    other = manager.add_player(room, "Bob")
    other.sid = "sid-bob"
    room.state = "playing"
    room.game = Game(turn_order=[player.id, other.id], rounds_total=1)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.phase = Phase.DRAWING

    flow = AsyncMock()
    sio, watch, activity = _watch(manager, clock, game_flow=flow)
    activity.note(player.sid)
    activity.note(other.sid)
    clock.advance(300)
    await watch.flush()
    clock.advance(25)
    await watch.flush()

    assert player.is_afk
    flow.apply_afk_consequences.assert_awaited()
    marked = [call.args[1].id for call in flow.apply_afk_consequences.await_args_list]
    assert player.id in marked


@pytest.mark.asyncio
async def test_a_seat_that_goes_while_the_pass_is_out_is_not_marked():
    """Asking one seat awaits, and the next seat can leave inside that await.

    The reconnect grace owns a seat whose socket has gone, not this. Marking
    one anyway would have them come back AFK, and would move the host off
    somebody whose only offence was a dropped connection.
    """
    clock = FakeClock()
    manager, room, first = _room_with()
    second = manager.add_player(room, "Bob")
    second.sid = "sid-bob"

    flow = AsyncMock()
    sio, watch, activity = _watch(manager, clock, game_flow=flow)
    activity.note(first.sid)
    activity.note(second.sid)
    clock.advance(300)
    await watch.flush()  # both asked
    clock.advance(25)

    # Bob's socket drops while the sweep is partway through the room. Marking
    # Ann broadcasts her new state, and that await is where the pass gives up
    # control - by the time it comes back, Bob's seat is a different question.
    async def drop_bob(*args, **kwargs):
        second.connected = False

    flow._emit_room_state.side_effect = drop_bob
    await watch.flush()

    assert first.is_afk, "Ann was still there to be marked"
    assert not second.is_afk, "Bob had already gone"


@pytest.mark.asyncio
async def test_a_check_open_on_a_departed_socket_is_dropped():
    """The map must not grow across a long-lived process."""
    clock = FakeClock()
    manager, room, player = _room_with()
    sio, watch, activity = _watch(manager, clock)
    activity.note(player.sid)
    clock.advance(300)
    await watch.flush()
    assert watch.open_checks == 1

    del room.players[player.id]
    await watch.flush()
    assert watch.open_checks == 0
