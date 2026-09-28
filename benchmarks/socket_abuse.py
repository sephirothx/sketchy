#!/usr/bin/env python3
"""What one hostile client costs the socket door, measured on a real server (#1229).

Starts its own throwaway server (the production runner, a scratch SQLite
database, its log captured to a file) so it can read that process's CPU time,
resident memory and log volume around each attack, then runs one scenario:

``garbage``   #1235. ``--sockets`` raw WebSockets each send undecodable text
              (``42[bad``) at ``--rate`` packets/s for ``--seconds``, ignoring
              any CLOSE the server queues. Reports what the server parsed,
              when (if ever) it cut each socket off, its CPU and its log.
``noargs``    #1235. Commands with no argument and an ack id
              (``421["join_room"]``): answered, or a traceback each.
``bomb``      #1234. ``--sockets`` raw WebSockets each send one text message
              of ``--megabytes`` MiB that permessage-deflate shrinks to a few
              KB. Reports the upload and the server's memory before, at peak
              and after.
``stream``    #1234. One connected socket streaming valid ~1 MB
              ``session_ping`` packets as fast as it can: how many the server
              took, and how long before it closed the socket.
``eio-only``  #1234/#1232. ``--sockets`` Engine.IO WebSockets that never send a
              Socket.IO CONNECT, held for ``--seconds``: how many are still
              open, and what they cost in memory.
``flood``     #1232. One address opens ``--sockets`` cookieless connected
              sockets, then a visitor from another address connects: is the
              visitor admitted, or told the server is full? Addresses are
              set with ``X-Forwarded-For``, which the server trusts from
              127.0.0.1 as production trusts its proxy.

``--backend`` runs the server from another checkout's ``backend/`` - a
worktree of the parent branch, say - so a before and an after run the same
script.

Usage (from the repository root)::

    backend/.venv/bin/python benchmarks/socket_abuse.py --scenario garbage

Numbers are this machine's: compare a run before a change with one after it,
on the same machine, rather than against a figure from elsewhere.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


# --- the server under test ----------------------------------------------------


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Server:
    """A throwaway `app.server` whose process this script can measure."""

    def __init__(self, env: dict[str, str], backend: Path = BACKEND) -> None:
        self.backend = backend
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self._scratch = tempfile.TemporaryDirectory(prefix="sketchy-abuse-")
        self.log_path = Path(self._scratch.name) / "server.log"
        self._env = {
            **os.environ,
            "HOST": "127.0.0.1",
            "PORT": str(self.port),
            "LOG_LEVEL": "warning",
            "SHUTDOWN_DRAIN_SECONDS": "0",
            "DATABASE_URL": f"sqlite+aiosqlite:///{self._scratch.name}/abuse.db",
            **env,
        }
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        self._log = open(self.log_path, "wb")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "app.server"],
            cwd=self.backend, env=self._env, stdout=self._log, stderr=subprocess.STDOUT,
        )

    async def ready(self) -> None:
        deadline = time.monotonic() + 30
        async with aiohttp.ClientSession() as http:
            while time.monotonic() < deadline:
                try:
                    async with http.get(f"{self.base}/api/health") as response:
                        if response.status == 200:
                            return
                except aiohttp.ClientError:
                    pass
                await asyncio.sleep(0.2)
        raise RuntimeError(f"server did not start; see {self.log_path}")

    def stop(self) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self._log.close()
        self._scratch.cleanup()

    def sample(self) -> dict[str, float]:
        """CPU seconds, resident memory (MB) and log bytes so far."""
        assert self.process is not None
        out = subprocess.run(
            ["ps", "-o", "rss=,time=", "-p", str(self.process.pid)],
            capture_output=True, text=True, check=True,
        ).stdout.split()
        rss_kb, cpu = int(out[0]), out[1]
        seconds = 0.0
        for part in cpu.replace("-", ":").split(":"):
            seconds = seconds * 60 + float(part)
        return {
            "cpu_s": seconds,
            "rss_mb": rss_kb / 1024,
            "log_bytes": self.log_path.stat().st_size,
            "tracebacks": self.log_path.read_bytes().count(b"Traceback"),
        }


def _delta(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    return {key: round(after[key] - before[key], 3) for key in before}


# --- clients ------------------------------------------------------------------


async def open_engine(http: aiohttp.ClientSession, base: str, *, compress: int = 15, address: str | None = None):
    """A raw Engine.IO WebSocket, with the OPEN packet read."""
    ws = await http.ws_connect(
        base.replace("http", "ws", 1) + "/socket.io/?EIO=4&transport=websocket",
        compress=compress,
        max_msg_size=0,
        headers={"X-Forwarded-For": address} if address else None,
    )
    opened = await ws.receive(timeout=10)
    assert opened.type == aiohttp.WSMsgType.TEXT and opened.data.startswith("0"), opened
    return ws


async def open_connected(http: aiohttp.ClientSession, base: str, *, address: str | None = None, told: list | None = None):
    """A raw WebSocket that has completed the Socket.IO CONNECT. A
    `server_full` notice on the way is appended to `told`."""
    from app.protocol import PROTOCOL_VERSION

    ws = await open_engine(http, base, address=address)
    await ws.send_str("40" + json.dumps({"protocol": PROTOCOL_VERSION}))
    while True:
        message = await ws.receive(timeout=10)
        if message.type != aiohttp.WSMsgType.TEXT:
            raise RuntimeError(f"CONNECT not answered: {message}")
        if message.data.startswith('42["server_full"') and told is not None:
            told.append(message.data)
        if message.data.startswith("40"):
            return ws
        if message.data == "2":
            await ws.send_str("3")


async def _keep_sending(ws, packet: str, rate: float, seconds: float) -> dict:
    """Send `packet` at `rate`/s until `seconds` pass or the server closes."""
    sent = 0
    started = time.monotonic()
    closed_after = None
    interval = 1.0 / rate
    reader = asyncio.create_task(_drain(ws))
    try:
        while time.monotonic() - started < seconds:
            if ws.closed or reader.done():
                closed_after = time.monotonic() - started
                break
            try:
                await ws.send_str(packet)
            except (ConnectionResetError, RuntimeError, aiohttp.ClientError):
                closed_after = time.monotonic() - started
                break
            sent += 1
            await asyncio.sleep(interval)
    finally:
        reader.cancel()
        await ws.close()
    return {"sent": sent, "closed_after_s": None if closed_after is None else round(closed_after, 2)}


async def _drain(ws) -> None:
    """Read everything and answer pings; return when the transport ends. A
    CLOSE packet ("1") is deliberately ignored: a hostile client does."""
    async for message in ws:
        if message.type == aiohttp.WSMsgType.TEXT and message.data == "2":
            await ws.send_str("3")


# --- scenarios ----------------------------------------------------------------


async def garbage(server: Server, args) -> dict:
    async with aiohttp.ClientSession() as http:
        sockets = [await open_engine(http, server.base) for _ in range(args.sockets)]
        before = server.sample()
        results = await asyncio.gather(*(
            _keep_sending(ws, "42[bad", args.rate, args.seconds) for ws in sockets
        ))
        await asyncio.sleep(1)
        after = server.sample()
    return {"per_socket": results, "server": _delta(before, after)}


async def noargs(server: Server, args) -> dict:
    answered = 0
    async with aiohttp.ClientSession() as http:
        ws = await open_connected(http, server.base)
        before = server.sample()
        for index in range(args.packets):
            await ws.send_str(f'42{index}["join_room"]')
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                message = await ws.receive(timeout=deadline - time.monotonic())
            except asyncio.TimeoutError:
                break
            if message.type != aiohttp.WSMsgType.TEXT:
                break
            if message.data.startswith("43"):
                answered += 1
        await ws.close()
        after = server.sample()
    return {"sent": args.packets, "acked": answered, "server": _delta(before, after)}


async def bomb(server: Server, args) -> dict:
    payload = "42" + json.dumps(["send_chat", {"text": "x" * (args.megabytes * 1024 * 1024)}])
    before = server.sample()
    peak = dict(before)
    wire = 0

    async def one(http):
        nonlocal wire
        ws = await open_engine(http, server.base)
        # aiohttp compresses the message with the negotiated deflate: a
        # megabytes-long run of one letter is a few kilobytes on the wire.
        await ws.send_str(payload)
        try:
            message = await ws.receive(timeout=5)
            return message.type.name
        except asyncio.TimeoutError:
            return "open"
        finally:
            await ws.close()

    async def watch(stop: asyncio.Event):
        while not stop.is_set():
            sample = server.sample()
            peak["rss_mb"] = max(peak["rss_mb"], sample["rss_mb"])
            await asyncio.sleep(0.2)

    stop = asyncio.Event()
    watcher = asyncio.create_task(watch(stop))
    async with aiohttp.ClientSession() as http:
        outcomes = await asyncio.gather(*(one(http) for _ in range(args.sockets)))
    import zlib

    compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
    wire = len(compressor.compress(payload.encode()) + compressor.flush(zlib.Z_SYNC_FLUSH)) * args.sockets
    await asyncio.sleep(3)
    stop.set()
    await watcher
    after = server.sample()
    return {
        "sockets": args.sockets,
        "inflated_mib_each": args.megabytes,
        "wire_bytes_total_approx": wire,
        "outcomes": {name: outcomes.count(name) for name in set(outcomes)},
        "rss_mb": {"before": round(before["rss_mb"], 1), "peak": round(peak["rss_mb"], 1), "after": round(after["rss_mb"], 1)},
        "cpu_s": round(after["cpu_s"] - before["cpu_s"], 3),
    }


async def stream(server: Server, args) -> dict:
    blob = "x" * (1024 * 1024 - 64)
    packet = "42" + json.dumps(["session_ping", {"pad": blob}])
    async with aiohttp.ClientSession() as http:
        ws = await open_connected(http, server.base)
        before = server.sample()
        result = await _keep_sending(ws, packet, args.rate, args.seconds)
        await asyncio.sleep(1)
        after = server.sample()
    return {"packet_bytes": len(packet), **result, "server": _delta(before, after)}


async def eio_only(server: Server, args) -> dict:
    before = server.sample()
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as http:
        sockets = []
        refused = 0
        for _ in range(args.sockets):
            try:
                sockets.append(await open_engine(http, server.base))
            except Exception:
                refused += 1
        opened = server.sample()
        readers = [asyncio.create_task(_drain(ws)) for ws in sockets]
        await asyncio.sleep(args.seconds)
        still_open = sum(1 for reader in readers if not reader.done())
        for reader in readers:
            reader.cancel()
        # And whether an ordinary visitor still gets in.
        try:
            visitor = await open_connected(http, server.base)
            admitted = True
            await visitor.close()
        except Exception:
            admitted = False
        for ws in sockets:
            await ws.close()
        after = server.sample()
    return {
        "opened": len(sockets),
        "refused": refused,
        f"open_after_{args.seconds:g}s": still_open,
        "visitor_admitted": admitted,
        "rss_mb": {"before": round(before["rss_mb"], 1), "opened": round(opened["rss_mb"], 1), "after": round(after["rss_mb"], 1)},
        "cpu_s": round(after["cpu_s"] - before["cpu_s"], 3),
    }


async def flood(server: Server, args) -> dict:
    before = server.sample()
    admitted, refused, told = 0, 0, []
    started = time.monotonic()
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as http:
        held = []

        async def one():
            nonlocal admitted, refused
            try:
                held.append(await open_connected(http, server.base, address="198.51.100.1", told=told))
                admitted += 1
            except Exception:
                refused += 1

        await asyncio.gather(*(one() for _ in range(args.sockets)))
        flood_seconds = time.monotonic() - started
        visitor_told: list = []
        try:
            visitor = await open_connected(http, server.base, address="203.0.113.9", told=visitor_told)
            visitor_outcome = "told server_full" if visitor_told else "admitted"
            await visitor.close()
        except Exception as error:
            visitor_outcome = f"refused ({type(error).__name__})"
        for ws in held:
            await ws.close()
    after = server.sample()
    return {
        "flood_sockets": args.sockets,
        "flood_seconds": round(flood_seconds, 2),
        "flood_admitted": admitted,
        "flood_told_full": len(told),
        "flood_refused": refused,
        "visitor": visitor_outcome,
        "cpu_s": round(after["cpu_s"] - before["cpu_s"], 3),
    }


SCENARIOS = {
    "garbage": garbage,
    "noargs": noargs,
    "bomb": bomb,
    "stream": stream,
    "eio-only": eio_only,
    "flood": flood,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    parser.add_argument("--sockets", type=int, default=6)
    parser.add_argument("--rate", type=float, default=480.0, help="packets per second per socket")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--packets", type=int, default=50)
    parser.add_argument("--megabytes", type=int, default=15)
    parser.add_argument("--backend", type=Path, default=BACKEND, help="the backend/ directory to run the server from")
    args = parser.parse_args()
    sys.path.insert(0, str(BACKEND))

    server = Server({}, backend=args.backend.resolve())

    async def run() -> dict:
        await server.ready()
        return await SCENARIOS[args.scenario](server, args)

    server.start()
    try:
        result = asyncio.run(run())
    finally:
        server.stop()
    print(json.dumps({"scenario": args.scenario, **result}, indent=2))


if __name__ == "__main__":
    main()
