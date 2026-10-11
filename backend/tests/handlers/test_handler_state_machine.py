"""Every socket handler, driven as a game by a state machine (#1465).

The handler tests each walk one path somebody thought of. The bugs that get
past them are orderings nobody wrote down - a command in the wrong phase, from
the wrong seat, after a disconnect, a moment after a deadline - and inputs
nobody sends: #1235 was every handler raising a `TypeError` for a command that
arrived with no payload at all, found by reading the code. Here Hypothesis
plays four people at the real handlers (`register_all_handlers`, in process):
they open and join rooms, start games, pick prompts, draw, guess, buy hints,
undo, vote, leave, drop their connection and come back, while the clock jumps
past turn and grace deadlines - and one rule sends any command arbitrary JSON.

After every step:

- no handler raised, and every refusal carries a string `errorCode` the
  client can read;
- nothing the server logged at ERROR or above - a phase timeout or a
  rebroadcast that fails is caught and logged, not raised, and would
  otherwise pass unseen;
- each room holds together: a game exactly while it is `playing`, its seats
  within `max_players`, exactly one host while anyone is in it (R-ROOM-16),
  and a socket in one seat at most (R-ROOM-08 - an account may hold two);
- nothing a guesser received contains the prompt while it is still theirs
  to guess, and nothing broadcast carries a credential.

The run asserts how far play got, so a change that leaves every command
bouncing off `invalid_payload` fails rather than passing vacuously; a scripted
game through the same machine pins that a whole game can still be played.

**Time.** Turn deadlines are tens of seconds and the reconnect grace thirty;
none of that can be waited out. The modules that schedule them see a virtual
clock instead (`asyncio.sleep`, `time.monotonic` and `time.time` replaced on
those modules only), and the `advance_clock` rule moves it: every timer due by
then fires, in deadline order, on the same code path the real timer takes.

**Budgets.** Command budgets are switched off: they exist to refuse exactly
the burst a state machine is, and with them on most steps come back
`too_fast` (83% in the spike) - testing the limiter, not the handlers.

Reproducible like every generated-input suite here (`tests/fuzzing.py`): the
same runs on every invocation, and `FUZZ_SCALE` for a longer random search.
"""
from __future__ import annotations

import asyncio
import heapq
import itertools
import logging
import time
from collections import Counter
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import socketio
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule, run_state_machine_as_test

import app.game
import app.handlers.connection
import app.handlers.restart
import app.handlers.rooms
import app.services.game_flow
from app.domain_values import HINT_MODES, SCORING_MODES
from app.game import PROMPT_CHOICES_PER_TURN, Phase
from app.handlers import payloads as payload_models
from app.handlers import register_all_handlers
from app.live_drawing import encode_live_drawing
from app.rooms import DRAWING_TIME_OPTIONS, RoomManager
from tests.fuzzing import budget
from app.services.game_handoff import FinishedGameHandoffWorker
from tests.fake_envelope_store import MemoryEnvelopeStore
from tests.fake_game_history_repo import FakeGameHistoryRepository
from tests.handlers.helpers import (
    ManualClock,
    SessionStore,
    StubPromptListRepo,
    contains_secret,
    replay_staged,
    settle_deferred,
)

PEOPLE = ("Ann", "Bob", "Cy", "Dee")
# How far play got, across every run of the module's machine. Read by the
# test after the runs finish.
REACHED: Counter = Counter()

_real_sleep = asyncio.sleep


# --- Virtual time ------------------------------------------------------------------


class VirtualClock:
    """Sleeps that end when the clock is moved, not when time passes."""

    def __init__(self) -> None:
        self.offset = 0.0
        self._monotonic_base = time.monotonic()
        self._wall_base = time.time()
        self._sleepers: list[tuple[float, int, asyncio.Future]] = []
        self._order = itertools.count()

    def monotonic(self) -> float:
        return self._monotonic_base + self.offset

    def time(self) -> float:
        return self._wall_base + self.offset

    async def sleep(self, seconds: float, result=None):
        if seconds <= 0:
            return await _real_sleep(0, result)
        future = asyncio.get_running_loop().create_future()
        heapq.heappush(self._sleepers, (self.offset + seconds, next(self._order), future))
        # Cancelled with its task when a timer is replaced: the stale entry
        # stays in the heap and is skipped when it comes due.
        await future
        return result

    async def advance(self, seconds: float) -> None:
        target = self.offset + seconds
        while self._sleepers and self._sleepers[0][0] <= target:
            deadline, _, future = heapq.heappop(self._sleepers)
            self.offset = max(self.offset, deadline)
            if not future.done():
                future.set_result(None)
                # The woken timer runs now, and may schedule the next one
                # (turn results after a turn) before the clock moves on.
                await settle()
        self.offset = target


class _Proxy:
    """A module's view of `asyncio` or `time` with some names replaced."""

    def __init__(self, real, **replaced) -> None:
        self._real = real
        self.__dict__.update(replaced)

    def __getattr__(self, name):
        return getattr(self._real, name)


# Every module that sleeps out a game deadline or reads the clock against one.
_SLEEPING_MODULES = (app.services.game_flow, app.handlers.restart, app.handlers.connection)
_CLOCK_MODULES = (
    app.services.game_flow, app.handlers.restart, app.handlers.connection,
    app.handlers.rooms, app.game,
)


async def settle() -> None:
    """Let every task the last step woke run to its next real wait."""
    for _ in range(25):
        await _real_sleep(0)


# --- Errors the server logged ------------------------------------------------------


# Module loggers are named either way: `getLogger(__name__)` and
# `getLogger("sketchy.<area>")`.
_APP_LOGGERS = ("app", "sketchy")


class _ErrorLog(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


# --- Payloads ----------------------------------------------------------------------

_FIELD_NAMES = sorted({
    info.alias or name
    for model in vars(payload_models).values()
    if isinstance(model, type) and issubclass(model, payload_models.RequestModel)
    for name, info in model.model_fields.items()
})
_json = st.recursive(
    st.none() | st.booleans() | st.integers(-(2**63), 2**63) | st.floats() | st.text(max_size=24),
    lambda children: st.lists(children, max_size=4)
    | st.dictionaries(st.sampled_from(_FIELD_NAMES) | st.text(max_size=8), children, max_size=5),
    max_leaves=12,
)
_settings_fields = st.fixed_dictionaries({}, optional={
    "rounds": st.integers(1, 3),
    "maxPlayers": st.sampled_from([2, 3, 4, 8]),
    "drawingSeconds": st.sampled_from(sorted(DRAWING_TIME_OPTIONS)),
    "hintMode": st.sampled_from(sorted(HINT_MODES)),
    "scoringMode": st.sampled_from(sorted(SCORING_MODES)),
    "isPublic": st.booleans(),
    "spectatorsSeePrompt": st.booleans(),
    "hideMaskedPrompt": st.booleans(),
    "customPrompts": st.sampled_from(["", "kite, lantern, walrus"]),
})


class HandlerMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self.clock = VirtualClock()
        self._patches = ExitStack()
        asyncio_view = _Proxy(asyncio, sleep=self.clock.sleep)
        time_view = _Proxy(time, monotonic=self.clock.monotonic, time=self.clock.time)
        for module in _SLEEPING_MODULES:
            self._patches.enter_context(patch.object(module, "asyncio", asyncio_view))
        for module in _CLOCK_MODULES:
            self._patches.enter_context(patch.object(module, "time", time_view))
        self.errors = _ErrorLog()
        for name in _APP_LOGGERS:
            logging.getLogger(name).addHandler(self.errors)

        self.room_manager = RoomManager()
        self.sessions = SessionStore()
        self.sio = socketio.AsyncServer(async_mode="asgi")
        self.ctx = self.run(self._build())
        self.commands = sorted(set(self.sio.handlers["/"]) - {"connect", "disconnect"})
        # Each person's current socket; a reconnect is a new one, as in a
        # browser, carrying the same account.
        self.sids = {person: f"{person.lower()}-0" for person in PEOPLE}
        self._generation = Counter()
        for person, sid in self.sids.items():
            self.sessions.sessions[sid] = {"user_id": f"user-{person.lower()}"}
        self.leaks: list[str] = []
        self.guess_ids = itertools.count(1)
        self.sequences = itertools.count(1)

    async def _build(self):
        # The stores a game reads and writes, as the other handler tests fake
        # them: a prompt list to draw from, and the history a finished game
        # is handed to and replayed into.
        history = self.history = FakeGameHistoryRepository()
        prompts = StubPromptListRepo()
        finished = FinishedGameHandoffWorker(
            MemoryEnvelopeStore(), game_history_repo=history, prompt_list_repo=prompts, clock=ManualClock()
        )
        ctx = register_all_handlers(
            self.sio,
            self.room_manager,
            game_history_repo=history,
            prompt_list_repo=prompts,
            finished_games=finished,
        )
        finished.bind_outcome(ctx.game_flow.note_history_outcome)
        self.sio.get_session = AsyncMock(side_effect=self.sessions.get)
        self.sio.save_session = AsyncMock(side_effect=self.sessions.save)
        self.sio.enter_room = AsyncMock()
        self.sio.leave_room = AsyncMock()
        self.sio.disconnect = AsyncMock()

        async def record(event, data=None, *args, **kwargs):
            # Judged as it is sent, against the room as it is at that moment:
            # one step can run several turns (a clock jump), and a later
            # turn's drawer and prompt say nothing about an earlier message.
            try:
                self._check_emit(event, data, kwargs)
            except AssertionError as violation:
                self.leaks.append(str(violation))

        self.sio.emit = AsyncMock(side_effect=record)
        ctx._command_windows.check = lambda *args, **kwargs: True
        ctx._within_shared_windows = lambda *args, **kwargs: True
        return ctx

    def run(self, coroutine):
        return self.loop.run_until_complete(coroutine)

    def teardown(self) -> None:
        try:
            self.run(self._close())
        finally:
            self.loop.close()
            for name in _APP_LOGGERS:
                logging.getLogger(name).removeHandler(self.errors)
            self._patches.close()

    async def _close(self) -> None:
        await self.ctx.timers.close()
        await replay_staged(self.ctx)
        REACHED["games_recorded"] += len(self.history.saved)
        tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # --- Calling a command -------------------------------------------------------

    def send(self, person: str, command: str, *args):
        async def call():
            answer = await asyncio.wait_for(self.sio.handlers["/"][command](self.sids[person], *args), 30)
            await settle()
            await settle_deferred(self.ctx)
            return answer

        answer = self.run(call())
        if isinstance(answer, dict) and answer.get("ok") is False:
            assert isinstance(answer.get("errorCode"), str), (
                f"{command} refused without an errorCode: {answer!r}"
            )
            REACHED[f"refused:{answer['errorCode']}"] += 1
        else:
            REACHED[f"answered:{command}"] += 1
        return answer

    def room_of(self, person: str):
        """The seat `person` holds on their current socket - by socket, as the
        server resolves it, because an account may still hold a seat in
        another room (R-ROOM-08)."""
        sid = self.sids[person]
        for room in self.room_manager.rooms.values():
            for player in room.players.values():
                if player.sid == sid:
                    return room, player
        return None, None

    def any_room(self, pick: int):
        """A room by index, busiest first, so low picks gather people into
        one room instead of scattering them across many."""
        rooms = sorted(self.room_manager.rooms.values(), key=lambda room: -len(room.players))
        return rooms[pick % len(rooms)] if rooms else None

    # --- Rules -------------------------------------------------------------------

    # Leaving, dropping and opening another room each undo the progress a
    # game needs, and with every rule drawn about equally often they would
    # undo it as fast as it is made. So they act on a third of their draws:
    # still dozens of times a run, but games get to start.
    _sometimes = st.sampled_from([True, False, False])

    @rule(person=st.sampled_from(PEOPLE), fields=_settings_fields, act=_sometimes)
    def create_room(self, person, fields, act):
        if act or self.room_of(person)[0] is None:
            self.send(person, "create_room", {"nickname": person, **fields})

    @rule(person=st.sampled_from(PEOPLE), pick=st.sampled_from([0, 0, 0, 1, 2, 5]), spectator=st.booleans())
    def join_room(self, person, pick, spectator):
        room = self.any_room(pick)
        code = room.code if room else "ABCDEF"
        self.send(person, "join_room", {"code": code, "nickname": person, "asSpectator": spectator})

    @rule(person=st.sampled_from(PEOPLE), act=_sometimes)
    def leave_room(self, person, act):
        if act:
            self.send(person, "leave_room", None)

    @rule(person=st.sampled_from(PEOPLE))
    def start_game(self, person):
        self.send(person, "start_game", None)

    @rule(person=st.sampled_from(PEOPLE), fields=_settings_fields)
    def update_settings(self, person, fields):
        self.send(person, "update_room_settings", fields)

    @rule(person=st.sampled_from(PEOPLE), index=st.integers(-1, PROMPT_CHOICES_PER_TURN), stale=st.booleans())
    def select_prompt(self, person, index, stale):
        room, _ = self.room_of(person)
        turn_id = room.game.current_turn_id if room and room.game and not stale else "stale-turn"
        self.send(person, "select_prompt", {"index": index, "turnId": turn_id})

    @rule(
        person=st.sampled_from(PEOPLE),
        event=st.sampled_from(["draw_start", "draw_move", "draw_end", "draw_shape", "draw_fill", "clear_canvas"]),
        x=st.floats(-0.2, 1.2),
        y=st.floats(-0.2, 1.2),
        fresh=st.booleans(),
    )
    def draw(self, person, event, x, y, fresh):
        room, _ = self.room_of(person)
        point = {"x": x, "y": y}
        payload = {
            "draw_start": {**point, "color": "#123456", "width": 4},
            "draw_move": {"points": [point, {"x": min(1.0, x + 0.01), "y": y}]},
            "draw_shape": {"shape": "ellipse", "from": point, "to": {"x": 0.5, "y": 0.5}, "color": "#654321", "width": 8},
            "draw_fill": {"x": min(max(x, 0.0), 0.999), "y": min(max(y, 0.0), 0.999), "color": "#abcdef"},
        }.get(event)
        frame = encode_live_drawing(event, payload)
        identity = None
        if event in {"draw_start", "draw_shape", "draw_fill", "clear_canvas"} and room and room.game:
            canvas = room.game.canvas
            sequence = canvas.sequence + 1 if fresh else next(self.sequences)
            identity = [canvas.generation, sequence, sequence]
        if identity is None:
            self.send(person, "draw", frame)
        else:
            self.send(person, "draw", frame, identity)

    @rule(person=st.sampled_from(PEOPLE), stale=st.booleans())
    def undo(self, person, stale):
        room, _ = self.room_of(person)
        if room and room.game and not stale:
            canvas = room.game.canvas
            payload = [canvas.generation, canvas.sequence + 1, canvas.revision, canvas.hash]
        else:
            payload = [0, 1, 0, 0]
        self.send(person, "undo_stroke", payload)

    @rule(person=st.sampled_from(PEOPLE), kind=st.sampled_from(["right", "right", "close", "wrong"]))
    def guess(self, person, kind):
        room, player = self.room_of(person)
        game = room.game if room else None
        prompt = game.prompt if game and game.prompt else "walrus"
        text = {"right": prompt, "close": prompt[:-1] or "x", "wrong": "definitely not it"}[kind]
        before = len(game.correct_guessers) if game else 0
        self.send(person, "guess", {"text": text, "id": next(self.guess_ids), "turnId": game.current_turn_id if game else None})
        if game and player and player.id in game.correct_guessers and len(game.correct_guessers) > before:
            REACHED["correct_guess"] += 1

    @rule(person=st.sampled_from(PEOPLE), text=st.sampled_from(["hi", "", "x" * 500]))
    def chat(self, person, text):
        self.send(person, "send_chat", {"text": text})

    @rule(person=st.sampled_from(PEOPLE), slot=st.integers(-1, 8))
    def buy_hint(self, person, slot):
        self.send(person, "buy_hint", {"slot": slot})

    @rule(person=st.sampled_from(PEOPLE), letter=st.sampled_from(["a", "e", "z", "ä", "", "ab"]))
    def buy_letter(self, person, letter):
        self.send(person, "buy_wheel_letter", {"letter": letter})

    @rule(person=st.sampled_from(PEOPLE), whom=st.sampled_from(PEOPLE), action=st.sampled_from(["kick", "afk"]))
    def vote(self, person, whom, action):
        _, player = self.room_of(whom)
        self.send(person, "vote_player", {"targetPlayerId": player.id if player else "nobody", "action": action})

    @rule(person=st.sampled_from(PEOPLE), vote=st.booleans())
    def restart_vote(self, person, vote):
        self.send(person, "cast_restart_vote", {"vote": vote})

    @rule(person=st.sampled_from(PEOPLE), afk=st.sampled_from([True, False, None]))
    def toggle_afk(self, person, afk):
        self.send(person, "toggle_afk", {"afk": afk})

    @rule(person=st.sampled_from(PEOPLE), act=_sometimes)
    def disconnect(self, person, act):
        """The socket drops. The person comes back on a new one, later, by
        joining again - or does not, and the grace runs out."""
        if not act:
            return
        sid = self.sids[person]

        async def drop():
            await self.sio._trigger_event("disconnect", "/", sid, self.sio.reason.TRANSPORT_CLOSE)
            await settle()
            await settle_deferred(self.ctx)

        self.run(drop())
        self._generation[person] += 1
        new_sid = f"{person.lower()}-{self._generation[person]}"
        self.sessions.sessions[new_sid] = {"user_id": f"user-{person.lower()}"}
        self.sids[person] = new_sid
        REACHED["disconnected"] += 1

    @rule(seconds=st.sampled_from([1, 5, 16, 31, 61, 121]))
    def advance_clock(self, seconds):
        async def advance():
            await self.clock.advance(seconds)
            await settle()
            # Whatever games finished are replayed into the history now, as
            # the handoff loop would.
            await replay_staged(self.ctx)

        self.run(advance())

    @rule(person=st.sampled_from(PEOPLE), command=st.data(), shape=st.sampled_from(["nothing", "one", "two"]))
    def anything(self, person, command, shape):
        """Any command, with any JSON - or no payload at all (#1235)."""
        name = command.draw(st.sampled_from(self.commands))
        if shape == "nothing":
            self.send(person, name)
        elif shape == "one":
            self.send(person, name, command.draw(_json))
        else:
            self.send(person, name, command.draw(_json), command.draw(_json))

    def _person(self, player) -> str | None:
        return next((name for name in PEOPLE if player and player.user_id == f"user-{name.lower()}"), None)

    @precondition(lambda self: any(
        room.state == "waiting" and len(room.active_players()) >= 2
        for room in self.room_manager.rooms.values()
    ))
    @rule()
    def host_starts(self):
        """The host of a room with two players starts it - which random
        commands from four people almost never line up to do."""
        room = next(
            room for room in self.room_manager.rooms.values()
            if room.state == "waiting" and len(room.active_players()) >= 2
        )
        host = next((p for p in room.players.values() if p.is_host), None)
        person = self._person(host)
        if person is not None and host.sid == self.sids[person]:
            self.send(person, "start_game", None)

    # Directed rules. Every other rule is about as likely as any other, and
    # four people doing random things scatter rather than play: a game needs
    # two people in one room, the host to start it, the drawer to choose and
    # draw and someone to guess, in that order. These make the next move a
    # game is waiting for, so play gets deep enough for the random rules
    # around it to land in the middle of turns.

    def _seat_holder(self, room, player) -> str | None:
        """The person sitting in `player`'s seat, on their current socket - back
        through `join_room` first if the seat is still waiting out a dropped
        one, as a reconnecting browser would."""
        person = self._person(player)
        if person is None:
            return None
        if player.sid != self.sids[person]:
            self.send(person, "join_room", {"code": room.code, "nickname": person})
        return person if player.sid == self.sids[person] else None

    @precondition(lambda self: any(
        room.state == "waiting" and len(room.active_players()) < 2 and room.players
        for room in self.room_manager.rooms.values()
    ))
    @rule(person=st.sampled_from(PEOPLE))
    def gather(self, person):
        room = next(
            room for room in self.room_manager.rooms.values()
            if room.state == "waiting" and len(room.active_players()) < 2 and room.players
        )
        self.send(person, "join_room", {"code": room.code, "nickname": person})

    @precondition(lambda self: any(len(room.players) >= 2 for room in self.room_manager.rooms.values()))
    @rule(pick=st.integers(0, 3))
    def host_leaves(self, pick):
        """The host of a room someone else is in walks out, so the role has
        to pass on - to a player, or with none left to a spectator, and back
        to the next player to sit down (R-ROOM-16)."""
        rooms = [room for room in self.room_manager.rooms.values() if len(room.players) >= 2]
        room = rooms[pick % len(rooms)]
        host = next((p for p in room.players.values() if p.is_host), None)
        person = self._person(host)
        if person is not None and host.sid == self.sids[person]:
            self.send(person, "leave_room", None)

    @precondition(lambda self: any(room.game for room in self.room_manager.rooms.values()))
    @rule(pick=st.integers(0, 3), action=st.sampled_from(["draw", "guess", "guess", "wait"]))
    def play_on(self, pick, action):
        """The next move the game is waiting for - carried on within the step
        when it opens another, so a chosen prompt can be drawn or guessed."""
        rooms = [room for room in self.room_manager.rooms.values() if room.game]
        room = rooms[pick % len(rooms)]
        game = room.game

        def drawer_person():
            drawer = room.players.get(game.current_drawer) if game.current_drawer else None
            return self._seat_holder(room, drawer) if drawer else None

        def live(phase) -> bool:
            return room.game is game and game.phase == phase

        if live(Phase.CHOOSING_PROMPT):
            person = drawer_person() if action != "wait" else None
            if person:
                self.send(person, "select_prompt", {"index": 0, "turnId": game.current_turn_id})
            else:
                self.advance_clock(16)
        if live(Phase.DRAWING):
            if action == "draw" and (person := drawer_person()):
                canvas = game.canvas
                identity = [canvas.generation, canvas.sequence + 1, canvas.sequence + 1]
                frame = encode_live_drawing("draw_start", {"x": 0.3, "y": 0.3, "color": "#000000", "width": 4})
                self.send(person, "draw", frame, identity)
            elif action == "guess":
                for player in list(room.players.values()):
                    if player.is_spectator or player.id == game.current_drawer or player.id in game.correct_guessers:
                        continue
                    person = self._seat_holder(room, player)
                    if person and live(Phase.DRAWING):
                        self.guess(person, "right")
                        break
            else:
                # Nobody guesses: the turn runs out on its clock.
                self.advance_clock(game.drawing_seconds + 1)
        elif live(Phase.TURN_RESULTS):
            self.advance_clock(6)

    # --- Invariants --------------------------------------------------------------

    @invariant()
    def nothing_was_logged_as_an_error(self):
        if self.errors.records:
            record = self.errors.records[0]
            detail = logging.Formatter().format(record)
            raise AssertionError(f"the server logged an error: {detail}")

    @invariant()
    def rooms_hold_together(self):
        sockets: dict[str, str] = {}
        for room in self.room_manager.rooms.values():
            assert room.state in ("waiting", "playing"), room.state
            assert (room.state == "playing") == (room.game is not None), (room.state, room.game)
            seated = room.seated_players()
            assert len(seated) <= room.max_players, (len(seated), room.max_players)
            hosts = [p.nickname for p in room.players.values() if p.is_host]
            if room.players:
                assert len(hosts) == 1, f"{room.code} has hosts {hosts}"
            for player in room.players.values():
                if player.sid:
                    assert player.sid not in sockets, f"socket {player.sid} holds two seats"
                    sockets[player.sid] = room.code
            if room.game:
                REACHED[f"phase:{room.game.phase.value}"] += 1

    @invariant()
    def nothing_leaked(self):
        assert not self.leaks, self.leaks[0]

    def _check_emit(self, event, data, kwargs) -> None:
        rooms = {room.id: room for room in self.room_manager.rooms.values()}
        target = kwargs.get("room") or kwargs.get("to")
        # `to` may name one socket, several, or a room.
        targets = target if isinstance(target, (list, tuple, set)) else [target]
        for one in targets:
            self._check_delivery(event, data, kwargs, rooms, one)

    def _check_delivery(self, event, data, kwargs, rooms, target) -> None:
        room = rooms.get(target)
        if room is not None:
            # A broadcast: nothing that identifies a player to the server.
            assert not contains_secret(data, object()), f"{event} broadcast a credential: {data!r}"
        game_rooms = [room] if room is not None else [
            r for r in rooms.values() if any(p.sid == target for p in r.players.values())
        ]
        for live in game_rooms:
            game = live.game
            if not game or not game.prompt or game.phase not in (Phase.CHOOSING_PROMPT, Phase.DRAWING):
                continue
            readers = (
                live.player_list()
                if room is not None
                else [p for p in live.players.values() if p.sid == target]
            )
            # Still guessing is whoever the game itself shows a masked prompt
            # to; a seat's own chat line echoed back to it is what it typed.
            # And what the drawer or a correct guesser chooses to type reaches
            # spectators by design (R-SPEC-03): theirs to spoil.
            author = data.get("playerId") if event == "chat_message" and isinstance(data, dict) else None
            spoiler_allowed = author is not None and (
                author == game.current_drawer or author in game.correct_guessers
            )
            guessing = [
                p for p in readers
                if p.sid != kwargs.get("skip_sid")
                and p.id != author
                and not (spoiler_allowed and p.is_spectator)
                and game.masked_prompt(
                    p.id, is_spectator=p.is_spectator, spectators_see_prompt=live.spectators_see_prompt
                ) != game.prompt
            ]
            if guessing:
                assert not contains_secret(data, game.prompt), (
                    f"{event} handed the prompt to a guesser: {data!r}"
                )


def test_the_handlers_survive_any_game():
    REACHED.clear()
    run_state_machine_as_test(
        HandlerMachine,
        settings=settings(max_examples=budget(200), stateful_step_count=80),
    )
    # A run that never gets past the front door compares nothing: games have
    # to start and reach drawing, and junk and dropped connections have to be
    # met. Only floors that held over every seed tried: the derandomized draws
    # move with any edit to this file, and the rules that steer play read the
    # live state, so how deep one run gets varies several-fold between seeds -
    # a correct guess in all of them, on a few seeds only a handful. That a
    # whole turn can be played through this machine is pinned below instead.
    assert REACHED["answered:start_game"] >= 8, REACHED
    assert REACHED[f"phase:{Phase.DRAWING.value}"] >= 3, REACHED
    assert REACHED["refused:invalid_payload"] >= 500, REACHED
    assert REACHED["disconnected"] >= 40, REACHED


def test_the_machine_plays_a_whole_game():
    """The machine's own plumbing - sessions, the virtual clock, the history
    handoff - walked through one game by hand, so a harness that can no longer
    reach a correct guess or a recorded game fails here, on every run, rather
    than as a thin random run that the floors above are too low to notice."""
    REACHED.clear()
    machine = HandlerMachine()
    try:
        machine.create_room("Ann", {"rounds": 1}, True)
        machine.join_room("Bob", 0, False)
        room = next(iter(machine.room_manager.rooms.values()))
        assert len(room.active_players()) == 2
        machine.host_starts()
        assert room.game is not None and room.game.phase == Phase.CHOOSING_PROMPT
        machine.play_on(0, "draw")
        assert room.game.phase == Phase.DRAWING
        machine.play_on(0, "guess")
        assert REACHED["correct_guess"] == 1
        # The guess ended the first turn; the second drawer's turn runs out.
        for _ in range(6):
            if room.game is None:
                break
            machine.play_on(0, "wait")
        assert room.game is None, room.game.phase
        machine.nothing_leaked()
        machine.nothing_was_logged_as_an_error()
        machine.rooms_hold_together()
    finally:
        machine.teardown()
    assert REACHED["games_recorded"] == 1
