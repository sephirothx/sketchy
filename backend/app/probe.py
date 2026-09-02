"""A synthetic player, for telling "the server is up" from "a game can be played".

Readiness says the process can reach its database. The scrape says what the
handlers have been doing. Neither says whether a stranger arriving right now
could open a room, be joined, and draw a line that the other seat sees - the
one thing the service is for. This does that, from outside, the way a
browser would: two guest sessions over HTTP, two sockets over Socket.IO, a
room, a game, one stroke, and a check that the stroke arrived.

It speaks Socket.IO's long-polling transport with the standard library, so
it can run from a cron entry or a node_exporter textfile job on a host that
has Python and nothing else. Polling is also the transport a client falls
back to when WebSockets are blocked, so exercising it is not a shortcut.

    python -m app.probe --base-url https://sketchy.example
    python -m app.probe --base-url http://localhost:8000 --json
    python -m app.probe --base-url ... --textfile /var/lib/node_exporter/sketchy.prom

Exit status is 0 when every step passed and 1 otherwise, so an alert can
be as simple as "the probe has not succeeded in five minutes".

The two guest sessions are kept between runs (`--state`, on by default),
because provisioning a guest is rate-limited per client - sixty an hour by
default - and a probe that minted two every minute would page on its own
rate limit after half an hour. A saved session is checked with one request
before it is used and replaced only when the server no longer knows it.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import struct
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path


PROBE_SUCCESS_METRIC = "sketchy_probe_success"
PROBE_DURATION_METRIC = "sketchy_probe_duration_seconds"
PROBE_STEP_METRIC = "sketchy_probe_step_seconds"
# When the file was last written, so a rule can tell "the last game passed"
# from "the last game passed, an hour ago, and nothing has run since".
PROBE_LAST_RUN_METRIC = "sketchy_probe_last_run_timestamp_seconds"
PROBE_METRIC_NAMES = (
    PROBE_SUCCESS_METRIC,
    PROBE_DURATION_METRIC,
    PROBE_STEP_METRIC,
    PROBE_LAST_RUN_METRIC,
)

STEPS = ("guest", "connect", "create", "join", "start", "prompt", "draw", "leave")
DEFAULT_STATE_PATH = Path.home() / ".cache" / "sketchy" / "probe-sessions.json"
DEFAULT_TIMEOUT_SECONDS = 20.0
STEP_TIMEOUT_SECONDS = 8.0
# A quiet long-poll is held by the server until a packet or its ping
# (25 s by default, 20 s more before it gives up on us), so a poll must be
# allowed to wait longer than any step. Only the poll gets this.
POLL_TIMEOUT_SECONDS = 60.0
RECORD_SEPARATOR = "\x1e"

# One `draw_start` frame, exactly as the wire-protocol document lays it out:
# header (version 1, tag 0), RGB, width, x, y in quarter-pixels.
DRAW_START_FRAME = struct.pack("<B3sBhh", 0x10, b"\xaa\xbb\xcc", 4, 800, 1200)
DRAW_END_FRAME = 0x12


class ProbeError(RuntimeError):
    def __init__(self, step: str, message: str) -> None:
        super().__init__(f"{step}: {message}")
        self.step = step


# --- transport -------------------------------------------------------------------


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


# (method, url, body, headers, *, wait_seconds=None) -> response. Injected so a
# test can drive the probe through a fake, and production can use the
# standard library. A transport raises `TimeoutError` when the wait it was
# given runs out, and any other exception for a failure to reach the server.
Transport = Callable[..., Awaitable[HttpResponse]]


def urllib_transport(timeout: float = STEP_TIMEOUT_SECONDS) -> Transport:
    def fetch(
        method: str, url: str, body: bytes | None, headers: dict[str, str], wait: float
    ) -> HttpResponse:
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=wait) as response:  # noqa: S310 - the operator names the URL
                return HttpResponse(
                    response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
                )
        except urllib.error.HTTPError as error:
            return HttpResponse(
                error.code, {k.lower(): v for k, v in error.headers.items()}, error.read()
            )
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise TimeoutError(str(error.reason)) from error
            raise

    async def transport(method, url, body, headers, *, wait_seconds: float | None = None):
        return await asyncio.to_thread(
            fetch, method, url, body, headers, wait_seconds or timeout_default
        )

    timeout_default = timeout
    return transport


# --- a Socket.IO polling client ----------------------------------------------------


def encode_payload(packets: list[str | bytes]) -> bytes:
    """Engine.IO v4 polling: text packets as they are, binary as `b` + base64."""
    parts = [
        "b" + base64.b64encode(packet).decode("ascii") if isinstance(packet, bytes) else packet
        for packet in packets
    ]
    return RECORD_SEPARATOR.join(parts).encode("utf-8")


def decode_payload(body: bytes) -> list[str | bytes]:
    if not body:
        return []
    packets: list[str | bytes] = []
    for part in body.decode("utf-8").split(RECORD_SEPARATOR):
        if part.startswith("b"):
            packets.append(base64.b64decode(part[1:]))
        else:
            packets.append(part)
    return packets


@dataclass
class Event:
    name: str
    args: list
    ack_id: int | None = None


@dataclass
class Ack:
    ack_id: int
    args: list


def parse_message(packet: str) -> tuple[str, int, int | None, list]:
    """Split a Socket.IO message packet into (kind, attachments, ack id, data).

    `42["event", ...]`, `431[...]`, `451-2["draw", {"_placeholder": true, "num": 0}]`
    - the kind digit, an optional attachment count before `-`, an optional
    ack id, then JSON.
    """
    kind = packet[1]
    rest = packet[2:]
    attachments = 0
    if kind in ("5", "6"):
        count, rest = rest.split("-", 1)
        attachments = int(count)
    index = 0
    while index < len(rest) and rest[index].isdigit():
        index += 1
    ack_id = int(rest[:index]) if index else None
    data = json.loads(rest[index:]) if rest[index:] else []
    return kind, attachments, ack_id, data


def _fill_placeholders(value, attachments: list[bytes]):
    if isinstance(value, dict):
        if value.get("_placeholder") is True and "num" in value:
            return attachments[int(value["num"])]
        return {key: _fill_placeholders(item, attachments) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill_placeholders(item, attachments) for item in value]
    return value


class PollingSocket:
    """One Socket.IO connection over long-polling, enough for a probe.

    Not a general client: no namespaces but the default, no reconnect, no
    upgrade to WebSocket, and every received packet is kept in one queue
    the flow reads from.
    """

    def __init__(self, base_url: str, transport: Transport, cookie: str, *, label: str) -> None:
        self._base = base_url.rstrip("/") + "/socket.io/?EIO=4&transport=polling"
        self._transport = transport
        self._headers = {"Cookie": cookie, "Accept": "*/*"}
        self.label = label
        self.sid: str | None = None
        self.socket_sid: str | None = None
        self._events: asyncio.Queue[Event] = asyncio.Queue()
        self._acks: dict[int, asyncio.Future[list]] = {}
        self._next_ack = 0
        self._poller: asyncio.Task[None] | None = None
        self._pending_binary: tuple[str, int, int | None, list, list[bytes]] | None = None
        # The canvas identity the server last announced, kept as it passes:
        # it arrives *before* the prompt choices, and a reader waiting for
        # those would otherwise let it go by.
        self.canvas_reset: list | None = None
        # Why the receiver stopped, if it did: surfaced by the next `expect`
        # rather than left as a silent gap where the events should be.
        self.failure: str | None = None

    def _url(self) -> str:
        url = f"{self._base}&t={int(time.time() * 1000)}"
        return f"{url}&sid={self.sid}" if self.sid else url

    async def _get(self, *, wait: float | None = None) -> list[str | bytes]:
        response = await self._transport(
            "GET", self._url(), None, self._headers, wait_seconds=wait
        )
        if response.status != 200:
            raise ProbeError(self.label, f"poll answered {response.status}")
        return decode_payload(response.body)

    async def _post(self, packets: list[str | bytes]) -> None:
        headers = {**self._headers, "Content-Type": "text/plain;charset=UTF-8"}
        response = await self._transport("POST", self._url(), encode_payload(packets), headers)
        if response.status != 200:
            raise ProbeError(self.label, f"send answered {response.status}")

    async def connect(self) -> None:
        opened = await self._get()
        if not opened or not isinstance(opened[0], str) or not opened[0].startswith("0"):
            raise ProbeError(self.label, "no Engine.IO open packet")
        self.sid = json.loads(opened[0][1:])["sid"]
        await self._post(["40"])
        self._poller = asyncio.create_task(self._poll_forever(), name=f"probe-poll-{self.label}")
        while self.socket_sid is None:
            event = await asyncio.wait_for(self._events.get(), STEP_TIMEOUT_SECONDS)
            if event.name == "__failed__":
                raise ProbeError(self.label, f"the connection failed: {self.failure}")
            if event.name == "__connected__":
                self.socket_sid = event.args[0]
            else:
                # Anything the server says before we know our own id is kept.
                self._events.put_nowait(event)
                await asyncio.sleep(0)

    async def _poll_forever(self) -> None:
        """Receive until cancelled or until something is wrong.

        Nothing may raise out of here: an exception in a background task is
        a line on stderr nobody reads, and the flow would then sit on an
        empty queue until its step timed out with the wrong reason. Every
        failure - the poll, a packet that cannot be read, a connection the
        server refused - goes through `_fail`, which is what `connect`,
        `expect` and `call` all watch.
        """
        while True:
            try:
                packets = await self._get(wait=POLL_TIMEOUT_SECONDS)
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                # A quiet socket: the server had nothing to say within the
                # wait, which is longer than its own ping. Ask again.
                continue
            except Exception as error:  # noqa: BLE001 - reported, not raised, from a background task
                self._fail(f"{type(error).__name__}: {error}")
                return
            try:
                for packet in packets:
                    self._handle(packet)
            except asyncio.CancelledError:
                raise
            except ProbeError as error:
                self._fail(str(error).split(": ", 1)[-1])
                return
            except Exception as error:  # noqa: BLE001 - as above
                self._fail(f"unreadable packet: {type(error).__name__}: {error}")
                return

    def _fail(self, reason: str) -> None:
        """Mark the socket dead and wake everything waiting on it."""
        self.failure = reason
        self._events.put_nowait(Event("__failed__", []))
        for future in self._acks.values():
            if not future.done():
                future.set_exception(
                    ProbeError(self.label, f"the connection failed: {reason}")
                )
        self._acks.clear()

    def _handle(self, packet: str | bytes) -> None:
        if isinstance(packet, bytes):
            pending = self._pending_binary
            if pending is None:
                return
            kind, attachments, ack_id, data, received = pending
            received.append(packet)
            if len(received) == attachments:
                self._pending_binary = None
                self._deliver(kind, ack_id, _fill_placeholders(data, received))
            return
        if packet == "2":  # ping
            asyncio.create_task(self._post(["3"]))
            return
        if not packet.startswith("4"):
            return
        kind, attachments, ack_id, data = parse_message(packet)
        if kind == "0":
            self._events.put_nowait(Event("__connected__", [data.get("sid")]))
            return
        if kind == "4":
            raise ProbeError(self.label, f"connection refused: {data}")
        if attachments:
            self._pending_binary = (kind, attachments, ack_id, data, [])
            return
        self._deliver(kind, ack_id, data)

    def _deliver(self, kind: str, ack_id: int | None, data: list) -> None:
        if kind in ("2", "5"):
            if data and data[0] == "canvas_reset" and len(data) > 1:
                self.canvas_reset = list(data[1])
            self._events.put_nowait(Event(str(data[0]), list(data[1:]), ack_id))
        elif kind in ("3", "6") and ack_id is not None:
            future = self._acks.pop(ack_id, None)
            if future is not None and not future.done():
                future.set_result(list(data))

    async def call(self, event: str, *args, wait_seconds: float = STEP_TIMEOUT_SECONDS) -> list:
        """Emit and wait for the acknowledgement."""
        self._next_ack += 1
        ack_id = self._next_ack
        future: asyncio.Future[list] = asyncio.get_running_loop().create_future()
        self._acks[ack_id] = future
        await self._post([self._encode(event, args, ack_id)])
        if self.failure is not None:
            raise ProbeError(self.label, f"the connection failed: {self.failure}")
        try:
            return await asyncio.wait_for(future, wait_seconds)
        except TimeoutError as error:
            raise ProbeError(self.label, f"no acknowledgement for {event}") from error

    async def emit(self, event: str, *args) -> None:
        await self._post(self._packets(event, args))

    def _encode(self, event: str, args: tuple, ack_id: int | None) -> str:
        packets = self._packets(event, args, ack_id)
        if len(packets) != 1:
            raise ProbeError(self.label, "an acknowledged event cannot carry binary here")
        return packets[0]  # type: ignore[return-value]

    def _packets(self, event: str, args: tuple, ack_id: int | None = None) -> list[str | bytes]:
        attachments: list[bytes] = []

        def placeholders(value):
            if isinstance(value, (bytes, bytearray)):
                attachments.append(bytes(value))
                return {"_placeholder": True, "num": len(attachments) - 1}
            return value

        data = json.dumps([event, *(placeholders(arg) for arg in args)], separators=(",", ":"))
        suffix = "" if ack_id is None else str(ack_id)
        if attachments:
            return [f"45{len(attachments)}-{suffix}{data}", *attachments]
        return [f"42{suffix}{data}"]

    async def expect(self, name: str, *, wait_seconds: float = STEP_TIMEOUT_SECONDS) -> Event:
        """The next event of that name, skipping the rest."""
        deadline = time.monotonic() + wait_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeError(self.label, f"never received {name}")
            event = await asyncio.wait_for(self._events.get(), remaining)
            if event.name == "__failed__":
                raise ProbeError(self.label, f"the connection failed: {self.failure}")
            if event.name == name:
                return event

    async def close(self) -> None:
        if self._poller is not None:
            self._poller.cancel()
            try:
                await self._poller
            except (asyncio.CancelledError, Exception):
                pass
        if self.sid:
            try:
                await self._post(["41", "1"])
            except Exception:
                pass


# --- the flow ----------------------------------------------------------------------


@dataclass
class ProbeResult:
    ok: bool
    steps: dict[str, float] = field(default_factory=dict)
    duration_seconds: float = 0.0
    failed_step: str | None = None
    error: str | None = None
    provisioned: bool = False

    def as_json(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "durationMs": round(self.duration_seconds * 1000, 1),
            "steps": {step: round(seconds * 1000, 1) for step, seconds in self.steps.items()},
            "failedStep": self.failed_step,
            "error": self.error,
            "provisioned": self.provisioned,
        }

    def as_textfile(self) -> str:
        lines = [
            f"# HELP {PROBE_SUCCESS_METRIC} Whether the last synthetic game succeeded.",
            f"# TYPE {PROBE_SUCCESS_METRIC} gauge",
            f"{PROBE_SUCCESS_METRIC} {1 if self.ok else 0}",
            f"# HELP {PROBE_DURATION_METRIC} How long the whole synthetic game took.",
            f"# TYPE {PROBE_DURATION_METRIC} gauge",
            f"{PROBE_DURATION_METRIC} {self.duration_seconds:.3f}",
            f"# HELP {PROBE_STEP_METRIC} How long each step of the synthetic game took.",
            f"# TYPE {PROBE_STEP_METRIC} gauge",
        ]
        for step, seconds in self.steps.items():
            lines.append(f'{PROBE_STEP_METRIC}{{step="{step}"}} {seconds:.3f}')
        lines += [
            f"# HELP {PROBE_LAST_RUN_METRIC} Unix time this file was last written by a probe run.",
            f"# TYPE {PROBE_LAST_RUN_METRIC} gauge",
            f"{PROBE_LAST_RUN_METRIC} {int(time.time())}",
        ]
        return "\n".join(lines) + "\n"


async def _guest(base_url: str, transport: Transport, name: str) -> str:
    """A guest session's cookie, the way the lobby's name box makes one."""
    body = json.dumps({"displayName": name}).encode("utf-8")
    response = await transport(
        "POST",
        f"{base_url.rstrip('/')}/api/auth/display-name",
        body,
        {"Content-Type": "application/json", "Accept": "application/json"},
    )
    if response.status == 429:
        raise ProbeError(
            "guest",
            "guest provisioning is rate-limited for this host; keep the probe's "
            "state file so sessions are reused, or raise GUEST_PROVISION_LIMIT",
        )
    if response.status != 200:
        raise ProbeError("guest", f"display-name answered {response.status}")
    cookie = response.headers.get("set-cookie", "")
    if not cookie:
        raise ProbeError("guest", "no session cookie was set")
    return cookie.split(";", 1)[0]


async def _session_check(base_url: str, transport: Transport, cookie: str) -> str | None:
    """The cookie to keep using, if the server still knows this one.

    `/api/auth/me` answers `null` for a session it does not know, and for
    one older than half its lifetime it answers with the account *and* a
    successor in `Set-Cookie`, revoking the one it was asked with. A
    browser adopts that silently; so does this, or the game that follows
    would be played with a token the server just retired.
    """
    try:
        response = await transport(
            "GET",
            f"{base_url.rstrip('/')}/api/auth/me",
            None,
            {"Cookie": cookie, "Accept": "application/json"},
        )
    except Exception:
        return None
    if response.status != 200:
        return None
    try:
        if json.loads(response.body or b"null") is None:
            return None
    except ValueError:
        return None
    rotated = response.headers.get("set-cookie", "")
    return rotated.split(";", 1)[0] if rotated else cookie


def load_sessions(path: Path | None, base_url: str) -> dict[str, str]:
    """The cookies a previous run saved for this server, if any."""
    if path is None:
        return {}
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(stored, dict) or stored.get("baseUrl") != base_url.rstrip("/"):
        return {}
    sessions = stored.get("sessions")
    return dict(sessions) if isinstance(sessions, dict) else {}


def save_sessions(path: Path | None, base_url: str, sessions: dict[str, str]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"baseUrl": base_url.rstrip("/"), "sessions": sessions}, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
        path.chmod(0o600)
    except OSError:
        # A probe that cannot remember still probes; it just provisions again.
        pass


async def _sessions(
    base_url: str, transport: Transport, state_path: Path | None, name_prefix: str
) -> tuple[str, str, bool]:
    """The host's and guest's cookies, reused from the state file when the
    server still knows them, provisioned otherwise. The flag says whether
    anything was provisioned, for the report."""
    saved = load_sessions(state_path, base_url)
    cookies: dict[str, str] = {}
    provisioned = False
    # Names are 3-16 characters from a small alphabet, so: a short prefix,
    # one letter for the seat, and the seconds of the clock.
    stamp = str(int(time.time()))[-6:]
    for seat in ("host", "guest"):
        cookie = saved.get(seat)
        usable = await _session_check(base_url, transport, cookie) if cookie else None
        if usable:
            cookies[seat] = usable
            continue
        cookies[seat] = await _guest(base_url, transport, f"{name_prefix[:8]}{seat[0]}{stamp}")
        provisioned = True
    if provisioned or cookies != saved:
        save_sessions(state_path, base_url, cookies)
    return cookies["host"], cookies["guest"], provisioned


async def run_probe(
    base_url: str,
    *,
    transport: Transport | None = None,
    budget_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    name_prefix: str = "probe",
    state_path: Path | None = DEFAULT_STATE_PATH,
) -> ProbeResult:
    transport = transport or urllib_transport()
    result = ProbeResult(ok=False)
    started = time.monotonic()
    step_started = started
    sockets: list[PollingSocket] = []

    def done(step: str) -> None:
        nonlocal step_started
        now = time.monotonic()
        result.steps[step] = now - step_started
        step_started = now

    async def flow() -> None:
        host_cookie, guest_cookie, result.provisioned = await _sessions(
            base_url, transport, state_path, name_prefix
        )
        done("guest")

        host = PollingSocket(base_url, transport, host_cookie, label="connect")
        guest = PollingSocket(base_url, transport, guest_cookie, label="connect")
        sockets.extend((host, guest))
        await host.connect()
        await guest.connect()
        done("connect")

        host.label = "create"
        created = await host.call("create_room", {"nickname": "probehost"})
        if not created or created[0].get("ok") is not True:
            raise ProbeError("create", f"refused: {created}")
        code = created[0]["code"]
        done("create")

        guest.label = "join"
        joined = await guest.call("join_room", {"code": code, "nickname": "probeguest"})
        if not joined or joined[0].get("ok") is not True:
            raise ProbeError("join", f"refused: {joined}")
        await host.expect("player_joined")
        done("join")

        host.label = guest.label = "start"
        begun = await host.call("start_game", {})
        if not begun or begun[0].get("ok") is not True:
            raise ProbeError("start", f"refused: {begun}")
        done("start")

        # Whichever seat is the drawer is offered the prompts.
        host.label = guest.label = "prompt"
        choices_task = asyncio.create_task(host.expect("your_prompt_choices"))
        guest_choices_task = asyncio.create_task(guest.expect("your_prompt_choices"))
        finished, pending = await asyncio.wait(
            {choices_task, guest_choices_task},
            timeout=STEP_TIMEOUT_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if not finished:
            raise ProbeError("prompt", "nobody was offered a prompt")
        drawer, viewer = (host, guest) if choices_task in finished else (guest, host)
        choices = next(iter(finished)).result().args[0]["choices"]
        chosen = await drawer.call("select_prompt", {"prompt": choices[0]})
        if not chosen or chosen[0].get("ok") is not True:
            raise ProbeError("prompt", f"refused: {chosen}")
        await viewer.expect("turn_started")
        if drawer.canvas_reset is None:
            raise ProbeError("prompt", "the drawer was never told which canvas this turn is")
        _revision, generation, sequence, _hash = drawer.canvas_reset
        done("prompt")

        drawer.label = viewer.label = "draw"
        await drawer.emit("draw", DRAW_START_FRAME, [generation, sequence + 1])
        await drawer.emit("draw", DRAW_END_FRAME)
        seen = await viewer.expect("draw")
        if not seen.args or seen.args[0] != DRAW_START_FRAME:
            raise ProbeError("draw", "the other seat received something other than the stroke")
        done("draw")

        host.label = guest.label = "leave"
        await guest.emit("leave_room")
        await host.emit("leave_room")
        done("leave")

    try:
        await asyncio.wait_for(flow(), budget_seconds)
        result.ok = True
    except ProbeError as error:
        result.failed_step = error.step
        result.error = str(error)
    except TimeoutError:
        result.failed_step = next((s for s in STEPS if s not in result.steps), "timeout")
        result.error = f"the whole probe did not finish within {budget_seconds:g}s"
    except Exception as error:  # noqa: BLE001 - a probe reports, it does not crash
        result.failed_step = next((s for s in STEPS if s not in result.steps), "unknown")
        result.error = f"{type(error).__name__}: {error}"
    finally:
        for socket in sockets:
            await socket.close()
        result.duration_seconds = time.monotonic() - started
    return result


# --- command line ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.probe",
        description="Play one synthetic game against a running Sketchy and report whether it worked.",
    )
    parser.add_argument("--base-url", required=True, help="e.g. https://sketchy.example")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument(
        "--textfile",
        type=Path,
        help="write Prometheus textfile-collector metrics here (atomically)",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="where the two guest sessions are kept between runs (default: %(default)s)",
    )
    parser.add_argument(
        "--no-state",
        action="store_true",
        help="provision fresh guests every run; mind GUEST_PROVISION_LIMIT",
    )
    args = parser.parse_args(argv)

    result = asyncio.run(
        run_probe(
            args.base_url,
            budget_seconds=args.timeout,
            state_path=None if args.no_state else args.state,
        )
    )

    if args.textfile is not None:
        tmp = args.textfile.with_suffix(args.textfile.suffix + ".tmp")
        tmp.write_text(result.as_textfile(), encoding="utf-8")
        tmp.replace(args.textfile)
    if args.json:
        print(json.dumps(result.as_json()))
    elif result.ok:
        print(f"ok in {result.duration_seconds * 1000:.0f}ms: " + ", ".join(
            f"{step} {seconds * 1000:.0f}ms" for step, seconds in result.steps.items()
        ))
    else:
        print(f"FAILED at {result.failed_step}: {result.error}", file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
