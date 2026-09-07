#!/usr/bin/env python3
"""The release load gate: a production-like room population, sustained (#461).

The documented scale target is 50 simultaneously active rooms and 400 connected
player seats on one worker (`docs/requirements.md`, *Scale target*). Nothing
checked in exercised anything like it: the other benchmarks are one canvas, one
handler, or a database read. This drives that population against a running
server with real Socket.IO clients over WebSocket - the same protocol path, the
same permessage-deflate contexts, the same handshake a browser makes - and
reports the numbers that decide whether a host can carry it, each against a
threshold. It exits non-zero on a breach, which is what makes it a gate rather
than a chart.

What every room does, continuously, for the whole run: the host opens it and
the seats join, the host starts a game, whoever is offered prompts picks one
and draws a real recorded hand stroke set (`fixtures/live_strokes/hand-long.json`)
at its recorded timing, frame identities included; the other seats chat every
few seconds and guess, wrongly at first and - in half the turns - correctly
after a while, so turns end both ways; when the game ends the host starts
another. A share of seats drop and reconnect on a schedule, taking their seat
back through the reconnect grace (R-CONN-01), and a set of lobby watchers hold
the lobby channel open for the whole run so presence and room-list deltas are
being fanned out too.

What is measured, client-side with one clock for every seat:

- **Acknowledgement latency** of every command that has one, p50/p95/p99.
- **Draw fan-out latency**: the drawer stamps each frame as it sends it; every
  viewer stamps it as it arrives. The gap is what a viewer's lag *is*, before
  the playback interval it adds on purpose (#559).
- **Timer overrun**: a turn that ran its full length ends `seconds` after
  `turn_started`; how late `turn_ended` arrives is how far behind the server's
  timers are, which is the number that fails a game before CPU looks busy.
- **Disconnects** nobody asked for, and reconnects that did not get the seat back.

And server-side, scraped from `/metrics` before, during and after: event-loop
lag (the histogram's p99 estimate and its worst sample), resident memory and its
growth over the run, sockets held, packets rejected at the door, canvas recovery
notices, database query latency. A breach in any of them fails the run.

The thresholds are release criteria for the *reference environment* named in
the report, not truths about every host; a production host is re-measured with
the same script. They are diagnostic baselines in the sense of R-ENG-11 - this
is not a CI job - and a gate in the sense of #461: it is run before a release,
and a breach is a decision, not a warning.

Usage (the server needs the limits a swarm from one address trips; use the
wrapper, which starts one with them set):
  benchmarks/run_load.sh                                  # 50 rooms x 8 seats, 5 minutes
  benchmarks/run_load.sh --rooms 5 --seats 4 --duration 60
  benchmarks/run_load.sh --json-output /tmp/load.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp
import socketio

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.protocol import PROTOCOL_VERSION

TRACE = Path(ROOT_DIR) / "fixtures" / "live_strokes" / "hand-long.json"
COOKIE = "sketchy_session"

# ---------------------------------------------------------------- thresholds

DEFAULT_THRESHOLDS = {
    "ackP95Ms": 100.0,
    "ackP99Ms": 250.0,
    "drawFanoutP95Ms": 150.0,
    "timerOverrunP95Ms": 250.0,
    "eventLoopLagP99Ms": 100.0,
    "eventLoopLagMaxMs": 250.0,
    "rssGrowthPercent": 25.0,
    "dbQueryP99Ms": 50.0,
    "unexpectedDisconnects": 0,
    "failedReconnects": 0,
    "packetsRejected": 0,
    # Sockets closed for their backlog: none without slow viewers in the run
    # (the harness adds the slow viewers' own closures back as expected).
    "unexpectedBacklogClosures": 0,
    # Notices that mean a canvas went wrong. `deferred` is excluded: a seat
    # that reconnects mid-turn inside a spent resync window is told to wait,
    # which is the bound working as designed (R-DRAW-13), not a fault.
    "faultNotices": 0,
}

FAULT_NOTICE_REASONS = ("invalid_frame", "refused_tool", "stale_generation", "unknown_sequence", "dropped_frame")


# ---------------------------------------------------------------- recording


@dataclass
class Samples:
    ack_ms: dict[str, list[float]] = field(default_factory=dict)
    fanout_ms: list[float] = field(default_factory=list)
    overrun_ms: list[float] = field(default_factory=list)
    turns_started: int = 0
    turns_ended: int = 0
    turns_skipped: int = 0
    games_started: int = 0
    guesses: int = 0
    chats: int = 0
    frames_sent: int = 0
    frames_received: int = 0
    unexpected_disconnects: int = 0
    reconnects: int = 0
    failed_reconnects: int = 0
    errors: list[str] = field(default_factory=list)

    def ack(self, command: str, ms: float) -> None:
        self.ack_ms.setdefault(command, []).append(ms)

    def all_acks(self) -> list[float]:
        return [ms for values in self.ack_ms.values() for ms in values]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


# ---------------------------------------------------------------- one seat


class Seat:
    """One connected player: an account, a socket, and what it is doing."""

    def __init__(self, harness: Harness, room: RoomRun, name: str) -> None:
        self.harness = harness
        self.room = room
        self.name = name
        self.token: str | None = None
        self.sio: socketio.AsyncClient | None = None
        self.player_id: str | None = None
        self.canvas: list | None = None
        self.turn_deadline: float | None = None
        self.turn_full_length: bool = True
        self.closing = False

    async def provision(self, http: aiohttp.ClientSession) -> None:
        async with http.post(
            f"{self.harness.base_url}/api/auth/display-name",
            json={"displayName": self.name},
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"provisioning {self.name}: HTTP {response.status}")
            # Read off the response: aiohttp's jar ignores cookies an IP host
            # sets, and the server here is one.
            cookie = response.cookies.get(COOKIE)
        if cookie is None:
            raise RuntimeError(f"provisioning {self.name}: no session cookie")
        self.token = cookie.value

    async def connect(self) -> None:
        sio = socketio.AsyncClient(reconnection=False)
        self.sio = sio
        samples = self.harness.samples

        @sio.event
        async def disconnect():
            if not self.closing and not self.harness.stopping:
                samples.unexpected_disconnects += 1

        @sio.on("your_prompt_choices")
        async def on_choices(payload):
            self.harness.spawn(self.choose_and_draw(payload["choices"]))

        @sio.on("canvas_reset")
        async def on_reset(payload):
            self.canvas = list(payload)

        @sio.on("turn_started")
        async def on_turn(payload):
            self.turn_deadline = time.monotonic() + float(payload["seconds"])
            self.turn_full_length = True
            if self.room.seats[0] is self:
                samples.turns_started += 1
                self.room.prompt = None
                self.room.correct_guesser = None
                self.room.turn_index += 1
                self.room.guess_correctly = self.room.turn_index % 2 == 0

        @sio.on("turn_ended")
        async def on_turn_ended(payload):
            # Whatever this seat was drawing belongs to a turn that is over:
            # a browser stops at once, and so must this, or the next stroke
            # opens with a generation the server has moved past.
            self.canvas = None
            if self.room.seats[0] is self:
                samples.turns_ended += 1
                if self.turn_deadline is not None and self.turn_full_length:
                    samples.overrun_ms.append((time.monotonic() - self.turn_deadline) * 1000)
            self.turn_deadline = None

        @sio.on("game_ended")
        async def on_game_ended(payload):
            if self.room.seats[0] is self:
                self.harness.spawn(self.room.start_game(delay=2.0))

        @sio.on("correct_guess")
        async def on_correct_guess(payload):
            # A correct guess ends the turn early once everyone has guessed
            # (or here, where one guesser is enough to change the timing):
            # the turn is no longer a full-length one for the overrun sample.
            self.turn_full_length = False

        @sio.on("draw")
        async def on_draw(frame, commit=None):
            samples.frames_received += 1
            sent_at = self.room.frame_sent_at.get(frame if isinstance(frame, (str, int)) else bytes(frame))
            if sent_at is not None:
                samples.fanout_ms.append((time.monotonic() - sent_at) * 1000)

        if (
            self.harness.capture is not None
            and self.harness.captured_seat in (None, self)
            and self.room.seats
            and self.room.seats[0] is not self
        ):
            # A guest, not the host: a host draws the first turn and would
            # record its own commits rather than a viewer's stream. Bound to
            # the seat, not to its first socket, so the stream carries on
            # across the seat's scheduled reconnects on the new client.
            # One seat's inbound stream, raw, in order, with a time: what a
            # viewer's compressor actually sees (#493). Hooked on the handler
            # the client registered with Engine.IO, which is what real
            # packets reach (the instance attribute is not, see #669).
            self.harness.captured_seat = self
            capture = self.harness.capture
            started = self.harness.capture_started
            handler = sio.eio.handlers["message"]

            async def recording(data):
                capture.write(json.dumps({
                    "atMs": round((time.monotonic() - started) * 1000, 1),
                    "seat": self.name,
                    "text": data if isinstance(data, str) else None,
                    "binaryBytes": None if isinstance(data, str) else len(data),
                }) + "\n")
                await handler(data)

            sio.eio.handlers["message"] = recording

        await sio.connect(
            self.harness.base_url,
            headers={"Cookie": f"{COOKIE}={self.token}"},
            auth={"protocol": PROTOCOL_VERSION},
            transports=["websocket"],
            wait_timeout=30,
        )

    async def call(self, command: str, payload: dict) -> dict | None:
        if self.sio is None or not self.sio.connected:
            return None
        started = time.monotonic()
        try:
            answer = await self.sio.call(command, payload, timeout=30)
        except (socketio.exceptions.TimeoutError, socketio.exceptions.BadNamespaceError) as error:
            self.harness.samples.errors.append(f"{command} on {self.name}: {error.__class__.__name__}")
            return None
        self.harness.samples.ack(command, (time.monotonic() - started) * 1000)
        if isinstance(answer, dict):
            return answer
        return {"ok": True} if answer is not None else None

    async def choose_and_draw(self, choices: list[str]) -> None:
        answer = await self.call("select_prompt", {"prompt": choices[0]})
        if not answer or not answer.get("ok"):
            return
        self.room.prompt = choices[0]
        self.room._drawer = self
        # The canvas identity arrives on `canvas_reset` before or right after.
        for _ in range(50):
            if self.canvas is not None:
                break
            await asyncio.sleep(0.1)
        if self.canvas is None:
            # The turn was over (a correct guess, or the game) before its
            # canvas identity reached this seat: nothing to draw on.
            self.harness.samples.turns_skipped += 1
            return
        _revision, generation, sequence, _hash = self.canvas
        deadline = self.turn_deadline or (time.monotonic() + 60)
        for stroke in self.harness.strokes:
            if self.harness.stopping or self.sio is None or not self.sio.connected:
                return
            if self.canvas is None or self.canvas[1] != generation:
                return  # the turn ended under the pen
            if time.monotonic() + stroke["duration"] > deadline - 2:
                break
            sequence += 1
            started = time.monotonic()
            for frame in stroke["frames"]:
                wait = started + frame["atMs"] / 1000 - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                if not self.sio.connected or self.canvas is None:
                    return
                data = frame["data"]
                self.room.frame_sent_at[data] = time.monotonic()
                self.harness.samples.frames_sent += 1
                if frame["identity"]:
                    await self.sio.emit("draw", (data, [generation, sequence]))
                else:
                    await self.sio.emit("draw", data)
            await asyncio.sleep(0.3)

    async def chatter(self) -> None:
        """Chat every few seconds; guess while a turn is on."""
        while not self.harness.stopping:
            await asyncio.sleep(random.uniform(4.0, 9.0))
            if self.sio is None or not self.sio.connected or self.room.prompt is None:
                continue
            if self.room.drawer_is(self):
                continue
            if self.turn_deadline is None:
                await self.call("send_chat", {"text": f"hello from {self.name}"})
                self.harness.samples.chats += 1
                continue
            elapsed = self.turn_deadline - time.monotonic()
            correct = self.room.guess_correctly and elapsed < 45 and self.room.correct_guesser is None
            text = self.room.prompt if correct else f"maybe {random.choice(WRONG)}"
            if correct:
                self.room.correct_guesser = self
            # The receipt is bare (wire §4), so the count is the acknowledgements'.
            await self.call("guess", {"text": text, "code": self.room.code})
            self.harness.samples.guesses += 1

    async def heartbeat(self) -> None:
        while not self.harness.stopping:
            await asyncio.sleep(5.0)
            await self.call("session_ping", {})

    async def reconnect_cycle(self) -> None:
        """Drop and come back, taking the seat back inside the grace."""
        while not self.harness.stopping:
            await asyncio.sleep(random.uniform(30.0, 60.0))
            if self.harness.stopping or self.sio is None or self.room.drawer_is(self):
                continue
            self.closing = True
            await self.sio.disconnect()
            await asyncio.sleep(random.uniform(1.0, 4.0))
            self.closing = False
            try:
                await self.connect()
                answer = await self.call("join_room", {"code": self.room.code, "nickname": self.name})
            except Exception as error:  # noqa: BLE001 - counted, not raised
                self.harness.samples.failed_reconnects += 1
                self.harness.samples.errors.append(f"reconnect {self.name}: {error}")
                continue
            if answer and answer.get("ok"):
                self.harness.samples.reconnects += 1
            else:
                self.harness.samples.failed_reconnects += 1

    async def close(self) -> None:
        self.closing = True
        if self.sio is None:
            return
        if self.sio.connected:
            await self.sio.disconnect()
        http = getattr(self.sio.eio, "http", None)
        if http is not None and not http.closed:
            await http.close()


WRONG = ["cat", "house", "tree", "boat", "sun", "car", "fish", "hat"]


class SlowViewer:
    """A seat that joins a room and then stops reading (#602).

    A raw WebSocket rather than a Socket.IO client, because a client library
    reads for you. It performs the Engine.IO and Socket.IO handshakes, joins
    the room as a spectator, then reads **one message a second**, answering
    pings, while asking for a full canvas sync every resync window. A reader
    that stops altogether is not the case: the ping timeout closes it in
    ~45 s, and at a seat's ordinary traffic the kernel's and transport's
    buffers would take an hour to fill before anything queued on the server
    anyway (measured while building this). The socket the budget exists for
    is one that keeps answering but cannot keep up - a slow device, a
    throttled link - and syncs are the bursts that put it behind: once its
    buffers are full the server's queue for it grows, the oldest packet ages,
    and the budget closes it. Expected to be closed by the server, and
    counted as such rather than as an unexpected disconnect.
    """

    def __init__(self, harness: Harness, room: RoomRun, name: str) -> None:
        self.harness = harness
        self.room = room
        self.name = name
        self.token: str | None = None
        self.ws = None
        self.session: aiohttp.ClientSession | None = None
        self.joined = False

    async def provision(self, http: aiohttp.ClientSession) -> None:
        await Seat.provision(self, http)  # type: ignore[arg-type]

    async def connect(self) -> None:
        self.session = aiohttp.ClientSession()
        url = self.harness.base_url.replace("http", "ws", 1) + "/socket.io/?EIO=4&transport=websocket"
        self.ws = await self.session.ws_connect(url, headers={"Cookie": f"{COOKIE}={self.token}"})
        opened = await self.ws.receive_str()
        assert opened.startswith("0"), opened
        await self.ws.send_str("40" + json.dumps({"protocol": PROTOCOL_VERSION}))
        # Read until the Socket.IO CONNECT answer, then join and stop reading.
        for _ in range(20):
            message = await self.ws.receive_str()
            if message.startswith("40"):
                break
        await self.ws.send_str('421["join_room",' + json.dumps({"code": self.room.code, "nickname": self.name, "asSpectator": True}) + "]")
        self.joined = True
        self.harness.spawn(self.pull_syncs())
        self.harness.spawn(self.read_slowly())

    async def pull_syncs(self) -> None:
        """Ask for the whole canvas once per resync window."""
        request_id = 1
        while not self.harness.stopping and self.ws is not None and not self.ws.closed:
            await asyncio.sleep(2.2)
            request_id += 1
            try:
                await self.ws.send_str(f'42{request_id}["request_sync_strokes",[{request_id}]]')
            except (ConnectionResetError, aiohttp.ClientError, RuntimeError):
                return

    async def read_slowly(self) -> None:
        """One message a second, pings answered, everything else unread."""
        while not self.harness.stopping and self.ws is not None and not self.ws.closed:
            await asyncio.sleep(1.0)
            try:
                message = await asyncio.wait_for(self.ws.receive(), 5.0)
            except (asyncio.TimeoutError, ConnectionResetError, aiohttp.ClientError, RuntimeError):
                continue
            if message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                return
            if message.type == aiohttp.WSMsgType.TEXT and message.data == "2":
                try:
                    await self.ws.send_str("3")
                except (ConnectionResetError, aiohttp.ClientError, RuntimeError):
                    return

    async def close(self) -> None:
        if self.ws is not None and not self.ws.closed:
            await self.ws.close()
        if self.session is not None and not self.session.closed:
            await self.session.close()


# ---------------------------------------------------------------- one room


class RoomRun:
    def __init__(self, harness: Harness, index: int, seats: int) -> None:
        self.harness = harness
        self.index = index
        self.seats: list[Seat] = [Seat(harness, self, f"L{index}s{seat}") for seat in range(seats)]
        self.code: str | None = None
        self.prompt: str | None = None
        self.turn_index = 0
        self.guess_correctly = False
        self.correct_guesser: Seat | None = None
        self.frame_sent_at: dict = {}

    _drawer: Seat | None = None

    def drawer_is(self, seat: Seat) -> bool:
        return seat is self._drawer

    async def open(self) -> None:
        host = self.seats[0]
        answer = await host.call("create_room", {"nickname": host.name, "name": f"Load {self.index}", "isPublic": self.index % 2 == 0, "rounds": 2})
        if not answer or not answer.get("ok"):
            raise RuntimeError(f"room {self.index}: create refused: {answer}")
        self.code = answer["code"]
        for seat in self.seats[1:]:
            joined = await seat.call("join_room", {"code": self.code, "nickname": seat.name})
            if not joined or not joined.get("ok"):
                raise RuntimeError(f"room {self.index}: join refused for {seat.name}: {joined}")

    async def start_game(self, delay: float = 0.0) -> None:
        if delay:
            await asyncio.sleep(delay)
        if self.harness.stopping:
            return
        self.correct_guesser = None
        answer = await self.seats[0].call("start_game", {})
        if answer and answer.get("ok"):
            self.harness.samples.games_started += 1
        else:
            self.harness.samples.errors.append(f"room {self.index}: start refused: {answer}")


# ---------------------------------------------------------------- harness


class Harness:
    def __init__(self, args) -> None:
        self.base_url = args.base_url.rstrip("/")
        self.args = args
        self.samples = Samples()
        self.stopping = False
        self.tasks: set[asyncio.Task] = set()
        self.strokes = load_strokes()
        self.rooms: list[RoomRun] = []
        self.watchers: list[Seat] = []
        self.slow_viewers: list[SlowViewer] = []
        self.capture = args.capture_seat.open("w") if args.capture_seat else None
        self.capture_started = time.monotonic()
        self.captured_seat: Seat | None = None

    def spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def metrics(self, http: aiohttp.ClientSession) -> dict[str, float]:
        """One scrape of `/metrics`. The server-side half of the gate is read
        from here, so a scrape that is not one - no token, a refusal, a
        page that is not Prometheus text - is a failed run, never a row of
        zeros that happens to pass every threshold."""
        if not self.args.metrics_token:
            raise RuntimeError("METRICS_TOKEN is not set; the gate cannot read the server's side")
        async with http.get(
            f"{self.base_url}/metrics", headers={"Authorization": f"Bearer {self.args.metrics_token}"}
        ) as response:
            text = await response.text()
            if response.status != 200:
                raise RuntimeError(f"/metrics answered HTTP {response.status}; is METRICS_TOKEN the server's?")
        values = parse_metrics(text)
        if "rss_bytes" not in values or "sockets" not in values:
            raise RuntimeError("/metrics did not carry the series the gate reads")
        return values

    async def run(self) -> dict:
        args = self.args
        random.seed(7)
        async with aiohttp.ClientSession() as http:
            before = await self.metrics(http)
            # Provision every account through a jar of its own.
            seats = [seat for room in self.rooms for seat in room.seats] + self.watchers
            for seat in seats:
                async with aiohttp.ClientSession() as own:
                    await seat.provision(own)
            started = time.monotonic()
            for seat in seats:
                await seat.connect()
            connect_seconds = time.monotonic() - started
            for room in self.rooms:
                await room.open()
            for watcher in self.watchers:
                await watcher.call("watch_lobby", {})
            for viewer in self.slow_viewers:
                async with aiohttp.ClientSession() as own:
                    await viewer.provision(own)
                await viewer.connect()
            open_seconds = time.monotonic() - started
            for room in self.rooms:
                self.spawn(room.start_game())
                for seat in room.seats:
                    self.spawn(seat.chatter())
                    self.spawn(seat.heartbeat())
                for seat in room.seats[1:]:
                    if random.random() < args.reconnect_share:
                        self.spawn(seat.reconnect_cycle())
            for watcher in self.watchers:
                self.spawn(watcher.heartbeat())

            during: list[dict[str, float]] = []
            run_started = time.monotonic()
            while time.monotonic() - run_started < args.duration:
                await asyncio.sleep(min(15.0, args.duration))
                during.append(await self.metrics(http))
            self.stopping = True
            for task in list(self.tasks):
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            for seat in seats:
                await seat.close()
            for viewer in self.slow_viewers:
                await viewer.close()
            await asyncio.sleep(1.0)
            after = await self.metrics(http)
        if self.capture is not None:
            self.capture.close()
        return self.report(before, during, after, connect_seconds, open_seconds)

    def report(self, before, during, after, connect_seconds, open_seconds) -> dict:
        s = self.samples
        acks = s.all_acks()
        lag_samples = [m.get("lag_p99_ms", 0.0) for m in during + [after] if m]
        lag_max = max([m.get("lag_max_ms", 0.0) for m in during + [after] if m] or [0.0])
        rss_before = before.get("rss_bytes", 0.0)
        rss_samples = [m.get("rss_bytes", 0.0) for m in during + [after] if m]
        rss_peak = max(rss_samples or [0.0])
        # Growth is measured across the sustained phase, from the first scrape
        # with the whole population connected and playing: the step from an
        # idle server to 400 seats and 50 rooms is what the seats cost, not a
        # leak, and is reported on its own as memory per seat.
        # The first quarter of the run is warm-up: the first games allocate
        # their histories, contexts and caches in one step. What matters is
        # whether memory keeps climbing after that, so growth is judged from
        # the end of the warm-up to the peak.
        warm = max(1, len(rss_samples) // 4)
        rss_loaded = rss_samples[warm - 1] if rss_samples else 0.0
        seats = max(1, self.args.rooms * self.args.seats + self.args.lobby_watchers)
        measured = {
            "ackP50Ms": percentile(acks, 0.50),
            "ackP95Ms": percentile(acks, 0.95),
            "ackP99Ms": percentile(acks, 0.99),
            "ackByCommand": {c: {"n": len(v), "p95Ms": percentile(v, 0.95)} for c, v in sorted(s.ack_ms.items())},
            "drawFanoutP50Ms": percentile(s.fanout_ms, 0.50),
            "drawFanoutP95Ms": percentile(s.fanout_ms, 0.95),
            "timerOverrunP95Ms": percentile(s.overrun_ms, 0.95),
            "timerOverrunMaxMs": max(s.overrun_ms, default=0.0),
            "eventLoopLagP99Ms": max(lag_samples, default=0.0),
            "eventLoopLagMaxMs": lag_max,
            "rssIdleMB": rss_before / 1e6,
            "rssLoadedMB": rss_loaded / 1e6,
            "rssPeakMB": rss_peak / 1e6,
            "rssPerSeatKB": ((rss_peak - rss_before) / seats / 1e3) if rss_before else 0.0,
            "rssGrowthPercent": ((rss_peak - rss_loaded) / rss_loaded * 100) if rss_loaded else 0.0,
            "dbQueryP99Ms": max([m.get("db_p99_ms", 0.0) for m in during + [after] if m] or [0.0]),
            "socketsConnectedPeak": max([m.get("sockets", 0.0) for m in during if m] or [0.0]),
            "packetsRejected": (after.get("rejected", 0.0) - before.get("rejected", 0.0)) if after else 0.0,
            "recoveryNotices": {
                key[len("notice:"):]: after.get(key, 0.0) - before.get(key, 0.0)
                for key in sorted(after) if key.startswith("notice:")
            } if after else {},
            "faultNotices": sum(
                after.get(f"notice:{reason}", 0.0) - before.get(f"notice:{reason}", 0.0)
                for reason in FAULT_NOTICE_REASONS
            ) if after else 0.0,
            # The outbound budget (#602): how much any one socket ever had
            # queued, and how many sockets were closed for passing it. With
            # slow viewers in the run the closures are the point; without
            # them they must be zero, and the high-water is what healthy
            # play reaches, which is what the budget is sized against.
            "backlogBytesMax": after.get("backlog_bytes_max", 0.0) if after else 0.0,
            "backlogAgeMaxMs": after.get("backlog_age_max_ms", 0.0) if after else 0.0,
            "backlogClosures": {
                key[len("backlog_closure:"):]: after.get(key, 0.0) - before.get(key, 0.0)
                for key in sorted(after) if key.startswith("backlog_closure:")
            } if after else {},
            "slowViewers": len(self.slow_viewers),
            # What each event costs before compression, summed over every
            # recipient (#493): the room_state share is what a delta
            # protocol could at most touch.
            "emitBytesByEvent": {
                key[len("emit:"):-len(":sum")]: {
                    "bytes": after.get(key, 0.0) - before.get(key, 0.0),
                    "count": after.get(key[:-len(":sum")] + ":count", 0.0) - before.get(key[:-len(":sum")] + ":count", 0.0),
                }
                for key in sorted(after) if key.startswith("emit:") and key.endswith(":sum")
            } if after else {},
            "unexpectedBacklogClosures": max(0.0, sum(
                after.get(key, 0.0) - before.get(key, 0.0)
                for key in after if key.startswith("backlog_closure:")
            ) - len(self.slow_viewers)) if after else 0.0,
            "rssSeriesMB": [round(m.get("rss_bytes", 0.0) / 1e6, 1) for m in during if m],
            "lagP99SeriesMs": [round(m.get("lag_p99_ms", 0.0), 1) for m in during if m],
            "bytesOutMB": ((after.get("bytes_out", 0.0) - before.get("bytes_out", 0.0)) / 1e6) if after else 0.0,
            "bytesInMB": ((after.get("bytes_in", 0.0) - before.get("bytes_in", 0.0)) / 1e6) if after else 0.0,
            "unexpectedDisconnects": s.unexpected_disconnects,
            "reconnects": s.reconnects,
            "failedReconnects": s.failed_reconnects,
            "turnsStarted": s.turns_started,
            "turnsEnded": s.turns_ended,
            "turnsSkipped": s.turns_skipped,
            "gamesStarted": s.games_started,
            "guesses": s.guesses,
            "chats": s.chats,
            "framesSent": s.frames_sent,
            "framesReceived": s.frames_received,
            "connectAllSeconds": connect_seconds,
            "openAllSeconds": open_seconds,
            "errors": s.errors[:20],
            "errorCount": len(s.errors),
        }
        thresholds = dict(DEFAULT_THRESHOLDS)
        breaches = [
            key for key, limit in thresholds.items()
            if key in measured and isinstance(measured[key], (int, float)) and measured[key] > limit
        ]
        return {
            "environment": {
                "machine": platform.machine(),
                "system": f"{platform.system()} {platform.release()}",
                "python": platform.python_version(),
                "cpuCount": os.cpu_count(),
                "processor": platform.processor(),
            },
            "scenario": {
                "rooms": self.args.rooms, "seatsPerRoom": self.args.seats,
                "seats": self.args.rooms * self.args.seats, "lobbyWatchers": self.args.lobby_watchers,
                "durationSeconds": self.args.duration, "reconnectShare": self.args.reconnect_share,
                "slowViewers": len(self.slow_viewers),
                "metricsScrapes": 2 + len(during),
            },
            "measured": measured,
            "thresholds": thresholds,
            "breaches": breaches,
            "passed": not breaches,
        }


def load_strokes() -> list[dict]:
    trace = json.loads(TRACE.read_text())
    strokes = []
    for stroke in trace["strokes"]:
        frames = []
        for frame in stroke["frames"]:
            raw = frame["frame"]
            frames.append({
                "atMs": frame["atMs"],
                "data": raw,  # an int control byte, or the base64 text a browser sends
                "identity": "identity" in frame,
            })
        if frames:
            strokes.append({"frames": frames, "duration": frames[-1]["atMs"] / 1000})
    return strokes


def parse_metrics(text: str) -> dict[str, float]:
    """The few series the gate reads, out of the Prometheus text."""
    values: dict[str, float] = {}
    buckets: list[tuple[float, float]] = []
    db_buckets: list[tuple[float, float]] = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name, _, value = line.rpartition(" ")
        try:
            number = float(value)
        except ValueError:
            continue
        if name.startswith("sketchy_event_loop_lag_seconds_bucket{"):
            le = name.split('le="')[1].split('"')[0]
            buckets.append((float("inf") if le == "+Inf" else float(le), number))
        elif name.startswith("sketchy_db_query_duration_seconds_bucket{"):
            le = name.split('le="')[1].split('"')[0]
            db_buckets.append((float("inf") if le == "+Inf" else float(le), number))
        elif name == "sketchy_event_loop_lag_last_seconds":
            values["lag_last_ms"] = number * 1000
        elif name == "sketchy_process_resident_memory_bytes":
            values["rss_bytes"] = number
        elif name == "sketchy_sockets_connected":
            values["sockets"] = number
        elif name == "sketchy_socket_bytes_out_total":
            values["bytes_out"] = number
        elif name == "sketchy_socket_bytes_in_total":
            values["bytes_in"] = number
        elif name.startswith("sketchy_socket_packets_rejected_total"):
            values["rejected"] = values.get("rejected", 0.0) + number
        elif name.startswith("sketchy_socket_emit_bytes_sum{") or name.startswith("sketchy_socket_emit_bytes_count{"):
            event = name.split('event="')[1].split('"')[0]
            kind = "sum" if "_sum{" in name else "count"
            values[f"emit:{event}:{kind}"] = number
        elif name == "sketchy_socket_backlog_bytes_max":
            values["backlog_bytes_max"] = number
        elif name == "sketchy_socket_backlog_age_seconds_max":
            values["backlog_age_max_ms"] = number * 1000
        elif name.startswith("sketchy_socket_backlog_closures_total{"):
            reason = name.split('reason="')[1].split('"')[0]
            values[f"backlog_closure:{reason}"] = number
        elif name.startswith("sketchy_canvas_recovery_notices_total{"):
            reason = name.split('reason="')[1].split('"')[0]
            values[f"notice:{reason}"] = number
    values["lag_p99_ms"] = histogram_quantile(buckets, 0.99) * 1000
    values["lag_max_ms"] = histogram_upper_bound(buckets) * 1000
    values["db_p99_ms"] = histogram_quantile(db_buckets, 0.99) * 1000
    return values


def histogram_quantile(buckets: list[tuple[float, float]], fraction: float) -> float:
    """The bucket bound the quantile falls under: an upper bound, as Prometheus's is."""
    if not buckets:
        return 0.0
    buckets = sorted(buckets)
    total = buckets[-1][1]
    if total == 0:
        return 0.0
    for bound, count in buckets:
        if count >= fraction * total:
            return bound if bound != float("inf") else buckets[-2][0]
    return buckets[-1][0]


def histogram_upper_bound(buckets: list[tuple[float, float]]) -> float:
    """The smallest bound every sample fell under: the worst lag, rounded up."""
    if not buckets:
        return 0.0
    buckets = sorted(buckets)
    total = buckets[-1][1]
    for bound, count in buckets:
        if count >= total:
            return bound if bound != float("inf") else buckets[-2][0]
    return buckets[-1][0]


def print_report(report: dict) -> None:
    m = report["measured"]
    t = report["thresholds"]
    env = report["environment"]
    sc = report["scenario"]
    print(f"\nLoad gate: {sc['rooms']} rooms x {sc['seatsPerRoom']} seats = {sc['seats']} seats, "
          f"{sc['lobbyWatchers']} lobby watchers, {sc['durationSeconds']} s")
    print(f"  on {env['system']} {env['machine']} ({env['cpuCount']} cpus), Python {env['python']}")
    print(f"  {m['gamesStarted']} games, {m['turnsStarted']} turns started, {m['turnsEnded']} ended, "
          f"{m['guesses']} guesses, {m['chats']} chats, {m['framesSent']} frames sent, "
          f"{m['framesReceived']} received, {m['reconnects']} reconnects")
    print(f"  all seats connected in {m['connectAllSeconds']:.1f} s, rooms open in {m['openAllSeconds']:.1f} s; "
          f"{m['bytesOutMB']:.1f} MB out, {m['bytesInMB']:.1f} MB in")
    print(f"  {'metric':<24}{'measured':>12}{'limit':>10}")
    for key in DEFAULT_THRESHOLDS:
        value = m.get(key, 0.0)
        flag = "  BREACH" if key in report["breaches"] else ""
        print(f"  {key:<24}{value:>12.1f}{t[key]:>10.1f}{flag}")
    if m["recoveryNotices"]:
        print(f"  recovery notices by reason: {m['recoveryNotices']}")
    print(f"  outbound backlog high-water: {m['backlogBytesMax']:.0f} B, oldest {m['backlogAgeMaxMs']:.0f} ms; "
          f"closures {m['backlogClosures'] or 'none'} with {m['slowViewers']} slow viewers")
    print(f"  RSS every 15 s: {m['rssSeriesMB']}")
    by_event = sorted(m["emitBytesByEvent"].items(), key=lambda item: -item[1]["bytes"])
    total_emit = sum(item["bytes"] for _, item in by_event) or 1.0
    print("  emitted bytes by event (before compression, per recipient):")
    for event, item in by_event[:8]:
        print(f"    {event:<24}{item['count']:>8.0f} emits{item['bytes'] / 1e6:>9.2f} MB{100 * item['bytes'] / total_emit:>6.1f}%")
    print(f"  ack p50 {m['ackP50Ms']:.1f} ms; draw fan-out p50 {m['drawFanoutP50Ms']:.1f} ms; "
          f"timer overrun max {m['timerOverrunMaxMs']:.1f} ms; RSS idle {m['rssIdleMB']:.0f} MB, after warm-up {m['rssLoadedMB']:.0f} MB, "
          f"peak {m['rssPeakMB']:.0f} MB ({m['rssPerSeatKB']:.0f} KB per seat above idle); "
          f"sockets peak {m['socketsConnectedPeak']:.0f}")
    for command, stats in m["ackByCommand"].items():
        print(f"    {command:<18} n={stats['n']:<6} p95 {stats['p95Ms']:.1f} ms")
    if m["errorCount"]:
        print(f"  {m['errorCount']} errors, first: {m['errors'][:5]}")
    print("  PASSED" if report["passed"] else f"  FAILED: {', '.join(report['breaches'])}")


RECORD_BEGIN = "<!-- load-gate-result:begin -->"
RECORD_END = "<!-- load-gate-result:end -->"


def record_result(report: dict, path: Path) -> None:
    """Write the run into the slot `docs/requirements.md` keeps under the scale
    target, replacing the previous record: the target stays a measurement."""
    m = report["measured"]
    env = report["environment"]
    sc = report["scenario"]
    rows = [
        ("Acknowledgement latency p50 / p95 / p99", f"{m['ackP50Ms']:.1f} / {m['ackP95Ms']:.1f} / {m['ackP99Ms']:.1f} ms", f"p95 ≤ {report['thresholds']['ackP95Ms']:.0f}, p99 ≤ {report['thresholds']['ackP99Ms']:.0f} ms"),
        ("Draw fan-out latency p50 / p95", f"{m['drawFanoutP50Ms']:.1f} / {m['drawFanoutP95Ms']:.1f} ms", f"p95 ≤ {report['thresholds']['drawFanoutP95Ms']:.0f} ms"),
        ("Timer overrun p95 / max", f"{m['timerOverrunP95Ms']:.1f} / {m['timerOverrunMaxMs']:.1f} ms", f"p95 ≤ {report['thresholds']['timerOverrunP95Ms']:.0f} ms"),
        ("Event-loop lag p99 / worst (histogram bucket bounds)", f"≤ {m['eventLoopLagP99Ms']:.0f} / ≤ {m['eventLoopLagMaxMs']:.0f} ms", f"≤ {report['thresholds']['eventLoopLagP99Ms']:.0f} / ≤ {report['thresholds']['eventLoopLagMaxMs']:.0f} ms"),
        ("Resident memory idle → after warm-up → peak", f"{m['rssIdleMB']:.0f} → {m['rssLoadedMB']:.0f} → {m['rssPeakMB']:.0f} MB ({m['rssPerSeatKB']:.0f} KB per seat above idle)", f"growth after warm-up ≤ {report['thresholds']['rssGrowthPercent']:.0f} % (measured {m['rssGrowthPercent']:.1f} %)"),
        ("Database query p99 (bucket bound)", f"≤ {m['dbQueryP99Ms']:.0f} ms", f"≤ {report['thresholds']['dbQueryP99Ms']:.0f} ms"),
        ("Unexpected disconnects / failed reconnects", f"{m['unexpectedDisconnects']:.0f} / {m['failedReconnects']:.0f} (of {m['reconnects']:.0f} reconnects)", "0 / 0"),
        ("Outbound backlog high-water (bytes / oldest) and closures", f"{m['backlogBytesMax']:.0f} B / {m['backlogAgeMaxMs']:.0f} ms; closures {', '.join(f'{k} {v:.0f}' for k, v in m['backlogClosures'].items()) or 'none'} with {m['slowViewers']} slow viewers", "closures = slow viewers; budget 10 s / 4 MiB"),
        ("Packets rejected / fault notices (all notices by reason)", f"{m['packetsRejected']:.0f} / {m['faultNotices']:.0f} ({', '.join(f'{k} {v:.0f}' for k, v in m['recoveryNotices'].items()) or 'none'})", "0 / 0"),
        ("Traffic", f"{m['bytesOutMB']:.1f} MB out, {m['bytesInMB']:.1f} MB in; {m['framesSent']} frames sent, {m['framesReceived']} received; {m['guesses']} guesses, {m['chats']} chats", "—"),
    ]
    lines = [
        f"**Last result** — {'PASSED' if report['passed'] else 'FAILED (' + ', '.join(report['breaches']) + ')'}: "
        f"{sc['rooms']} rooms × {sc['seatsPerRoom']} seats = {sc['seats']} seats and {sc['lobbyWatchers']} lobby watchers "
        f"for {sc['durationSeconds']:.0f} s ({m['gamesStarted']} games, {m['turnsStarted']} turns), "
        f"on {env['system']} {env['machine']}, {env['cpuCount']} CPUs, Python {env['python']} — the reference environment for now; "
        f"a production host is re-measured with the same script.",
        "",
        "| Signal | Measured | Threshold |",
        "| --- | --- | --- |",
    ] + [f"| {name} | {value} | {limit} |" for name, value, limit in rows]
    text = path.read_text()
    begin = text.index(RECORD_BEGIN) + len(RECORD_BEGIN)
    end = text.index(RECORD_END)
    path.write_text(text[:begin] + "\n" + "\n".join(lines) + "\n" + text[end:])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--rooms", type=int, default=50)
    parser.add_argument("--seats", type=int, default=8, help="seats per room, the host included")
    parser.add_argument("--lobby-watchers", type=int, default=20)
    parser.add_argument("--duration", type=float, default=300.0, help="seconds of sustained play")
    parser.add_argument("--reconnect-share", type=float, default=0.25, help="share of non-host seats that drop and reconnect on a schedule")
    parser.add_argument("--slow-viewers", type=int, default=4, help="spectators that join a room and stop reading, for the outbound budget (#602); each is expected to be closed by the server")
    parser.add_argument("--metrics-token", default=os.environ.get("METRICS_TOKEN"))
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--capture-seat", type=Path, help="write one seat's raw inbound stream, in order with times, as JSON lines (#493)")
    parser.add_argument("--record", type=Path, help="write the result into this document's load-gate slot (docs/requirements.md)")
    args = parser.parse_args()

    harness = Harness(args)
    harness.rooms = [RoomRun(harness, index, args.seats) for index in range(args.rooms)]
    harness.watchers = [Seat(harness, RoomRun(harness, -1, 0), f"Lw{index}") for index in range(args.lobby_watchers)]
    harness.slow_viewers = [
        SlowViewer(harness, harness.rooms[index % max(1, len(harness.rooms))], f"Lslow{index}")
        for index in range(args.slow_viewers)
    ] if harness.rooms else []
    report = asyncio.run(harness.run())
    print_report(report)
    if args.json_output:
        args.json_output.write_text(json.dumps(report, indent=2) + "\n")
    if args.record:
        record_result(report, args.record)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
