#!/usr/bin/env python3
"""A viewer that cannot keep up, and what the outbound budget does to it (#602).

Engine.IO queues every packet for a socket without a bound. A peer that stops
reading altogether is closed by the ping timeout in ~45 s, and at a seat's
ordinary traffic its buffers would take an hour to fill first; the socket the
budget exists for is one that keeps answering pings but reads slower than it
is sent to - a slow device, a throttled link - while the bursts a canvas sync
is put it further behind. This stages exactly that against a throwaway server
and watches the server's side of it:

1. A room with a large drawing (a drawer streams ~24 000 points at the
   drawing budget, so the canvas is near the turn's point ceiling and one
   sync is ~100 KB).
2. A spectator on a raw WebSocket that stops reading at the transport - its
   TCP window fills, then the server's send buffer, then the transport's
   slack, and only then the server's queue - while asking for a full sync
   every resync window. (A viewer that merely reads slowly never gets this
   far on a loopback: the kernel's buffers grow to absorb megabytes, which
   is measured here too, as the slack under the budget.)
3. `/metrics` every two seconds: the backlog high-water in bytes and age, and
   the moment the server closes the socket for passing the budget.
4. That the socket is *gone*, not only forgotten (#1235, #1249): the server's
   count of WebSocket handlers still running - whose writer, blocked on the
   peer, is what would hold the backlog - falls back to what it was before
   the spectator came, and the spectator's own connection, reading again,
   reaches its end within seconds. A closure counted, or the socket leaving
   the registry, is not taken as proof of either.
5. The spectator comes back under a new name (a guest's name is held for
   30 s, #859), joins again, asks for the canvas as a browser does (nothing
   is pushed on a join since #877) and takes a full sync, whose history hash
   is checked against the header the server sent: recovery is a full,
   verified canvas, never a partial stream.

Usage:
  METRICS_TOKEN=x benchmarks/with_server.sh benchmarks/slow_viewer.py
  (benchmarks/run_load.sh sets the same environment; this script only needs
  the token and the raised guest limits)
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time

import aiohttp
import socketio

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.canvas_history import (
    canvas_history_hash,
    decode_binary_canvas_history,
)
from app.handlers.payloads import MAX_ACTION_NONCE
from app.live_drawing import encode_live_drawing
from app.protocol import PROTOCOL_VERSION

COOKIE = "sketchy_session"
HANDLERS = "sketchy_websocket_handlers_open"
# How long the server has to finish a torn-down socket's handler, and the
# spectator's connection to reach its end once it reads again.
TEARDOWN_SECONDS = 5.0


def session_cookie(cookies) -> str:
    """`name=value` of the session cookie, under whichever name the server
    gave it: `__Host-`-prefixed in production (#467), plain elsewhere."""
    for name, morsel in cookies.items():
        if name.endswith(COOKIE):
            return f"{name}={morsel.value}"
    raise AssertionError("no session cookie was set")


async def provision(base: str, name: str) -> str:
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{base}/api/auth/display-name", json={"displayName": name}) as response:
            assert response.status == 200, response.status
            return session_cookie(response.cookies)


async def metrics(base: str, token: str) -> dict[str, float]:
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{base}/metrics", headers={"Authorization": f"Bearer {token}"}) as response:
            text = await response.text()
    out: dict[str, float] = {}
    for line in text.splitlines():
        if line.startswith(("sketchy_socket_backlog", "sketchy_sockets_connected", HANDLERS)):
            name, _, value = line.rpartition(" ")
            out[name] = float(value)
    return out


async def client(base: str, name: str) -> socketio.AsyncClient:
    cookie = await provision(base, name)
    sio = socketio.AsyncClient(reconnection=False)
    await sio.connect(base, headers={"Cookie": cookie}, auth={"protocol": PROTOCOL_VERSION}, transports=["websocket"])
    return sio


async def raw_spectator(base: str, name: str, code: str):
    """A raw WebSocket spectator: session, socket, and the join sent (ack id 1)."""
    cookie = await provision(base, name)
    session = aiohttp.ClientSession()
    ws = await session.ws_connect(base.replace("http", "ws", 1) + "/socket.io/?EIO=4&transport=websocket", headers={"Cookie": cookie})
    assert (await ws.receive_str()).startswith("0")
    await ws.send_str("40" + json.dumps({"protocol": PROTOCOL_VERSION}))
    while not (await ws.receive_str()).startswith("40"):
        pass
    await ws.send_str('421["join_room",' + json.dumps({"code": code, "nickname": name, "asSpectator": True}) + "]")
    return session, ws


async def main() -> int:
    base = sys.argv[sys.argv.index("--base-url") + 1] if "--base-url" in sys.argv else "http://127.0.0.1:8765"
    token = os.environ["METRICS_TOKEN"]

    host = await client(base, "SlowHost")
    guest = await client(base, "SlowGuest")
    code = (await host.call("create_room", {"nickname": "SlowHost", "rounds": 1}))["code"]
    assert (await guest.call("join_room", {"code": code, "nickname": "SlowGuest"}))["ok"]
    chosen: asyncio.Future = asyncio.get_running_loop().create_future()
    identity: dict = {}

    def wire(sio):
        async def on_choices(payload):
            await sio.call("select_prompt", {"index": 0})
            if not chosen.done():
                chosen.set_result(sio)

        async def on_turn_starting(payload):
            identity["reset"] = payload["canvas"]

        sio.on("your_prompt_choices", on_choices)
        sio.on("turn_starting", on_turn_starting)

    wire(host)
    wire(guest)
    assert (await host.call("start_game", {}))["ok"]
    drawer = await asyncio.wait_for(chosen, 15)
    await asyncio.sleep(0.5)
    _, generation, sequence, _ = identity["reset"]

    # A near-ceiling drawing, paced under the drawing budget (100 frames
    # per 2 s): 120 strokes of 200 points is 24 000 of the 25 000 allowed.
    for _stroke in range(120):
        sequence += 1
        # `[generation, sequence, nonce]`, the nonce required since #1102.
        opener = encode_live_drawing("draw_start", {"x": 0.05, "y": 0.05, "color": "#000000", "width": 4})
        await drawer.emit("draw", (opener, [generation, sequence, random.randint(1, MAX_ACTION_NONCE)]))
        points = [{"x": 0.05 + (index % 40) / 50, "y": 0.05 + (index // 40) / 8} for index in range(200)]
        await drawer.emit("draw", encode_live_drawing("draw_move", {"points": points}))
        await drawer.emit("draw", encode_live_drawing("draw_end"))
        await asyncio.sleep(0.07)
    await asyncio.sleep(1.0)
    print(f"drawing staged: {sequence} actions on the canvas")

    # The host's and the guest's: what the count returns to once the
    # spectator's socket is really gone.
    handlers_before = (await metrics(base, token)).get(HANDLERS)
    if handlers_before is None:
        print(f"FAILED: /metrics has no {HANDLERS}")
        return 1
    session, ws = await raw_spectator(base, "Slowpoke", code)
    # Read the join's answers, then stop reading at the transport: from here
    # the socket accepts nothing, and everything sent to it backs up.
    await asyncio.sleep(1.0)
    transport = ws._conn.transport if ws._conn is not None else None
    assert transport is not None
    transport.pause_reading()
    started = time.monotonic()
    closed_at: float | None = None
    request_id = 1
    last_report = 0.0
    last_request = 0.0
    high_water = {"bytes": 0.0, "age": 0.0}
    while time.monotonic() - started < 120:
        await asyncio.sleep(1.0)
        # One request per resync window (2 s), with a margin so none is
        # refused as too fast: the syncs are the load, and a refused one
        # sends nothing.
        if time.monotonic() - last_request < 2.3:
            continue
        last_request = time.monotonic()
        request_id += 1
        try:
            await ws.send_str(f'42{request_id}["request_sync_strokes",[{request_id}]]')
        except Exception as error:  # noqa: BLE001
            closed_at = time.monotonic() - started
            print(f"t={closed_at:5.1f}s the slow viewer's socket is gone ({error})")
            break
        if time.monotonic() - last_report >= 2.0:
            last_report = time.monotonic()
            m = await metrics(base, token)
            high_water["bytes"] = max(high_water["bytes"], m.get("sketchy_socket_backlog_bytes_max", 0.0))
            high_water["age"] = max(high_water["age"], m.get("sketchy_socket_backlog_age_seconds_max", 0.0))
            closures = {k.split('reason="')[1].rstrip('"}'): v for k, v in m.items() if k.startswith("sketchy_socket_backlog_closures_total{")}
            print(f"t={time.monotonic() - started:5.1f}s backlog high-water {m.get('sketchy_socket_backlog_bytes_max', 0):8.0f} B, "
                  f"oldest {m.get('sketchy_socket_backlog_age_seconds_max', 0):5.2f} s, closures {closures or 'none'}, sockets {m.get('sketchy_sockets_connected', 0):.0f}")
            if closures:
                closed_at = time.monotonic() - started
                print(f"t={closed_at:5.1f}s closed for the budget: {closures}")
                break

    torn_down = False
    if closed_at is not None:
        torn_down = await confirm_teardown(base, token, ws, transport, handlers_before)
    await ws.close()
    await session.close()

    # Recovery: come back, join again, ask for the canvas, check its hash.
    verified = False
    if closed_at is not None:
        session, ws = await raw_spectator(base, "Slowpoke2", code)
        while True:
            message = await asyncio.wait_for(ws.receive(), 10)
            if message.type != aiohttp.WSMsgType.TEXT:
                continue
            if message.data.startswith("431"):
                assert json.loads(message.data[3:])[0].get("ok"), message.data
                break
            if message.data == "2":
                await ws.send_str("3")
        await ws.send_str('422["request_sync_strokes",[2]]')
        header = None
        while True:
            message = await asyncio.wait_for(ws.receive(), 10)
            if message.type == aiohttp.WSMsgType.TEXT and message.data.startswith("451-") and "sync_strokes" in message.data:
                header = json.loads(message.data[message.data.index("["):])
            elif message.type == aiohttp.WSMsgType.BINARY and header is not None:
                history = decode_binary_canvas_history(message.data)
                # ["sync_strokes", placeholder, revision, generation, sequence, historyHash, requestId]
                sent_hash = header[5]
                verified = canvas_history_hash(history) == sent_hash
                print(f"recovered: a full sync of {len(message.data)} bytes, {len(history)} actions, "
                      f"hash {'matches' if verified else 'DOES NOT MATCH'} the header's {sent_hash}")
                break
        await ws.close()
        await session.close()
    await host.disconnect()
    await guest.disconnect()
    print(f"budget high-water seen: {high_water['bytes']:.0f} B, oldest {high_water['age']:.1f} s")
    if closed_at is None:
        print("FAILED: the slow viewer was never closed for its backlog")
        return 1
    if not torn_down:
        print("FAILED: the evicted socket was counted closed but its transport was not ended")
        return 1
    if not verified:
        print("FAILED: the recovered canvas did not verify")
        return 1
    print("PASSED")
    return 0


async def confirm_teardown(base: str, token: str, ws, transport, handlers_before: float) -> bool:
    """That the evicted socket's transport ended, from both sides.

    The server's: its WebSocket handler returned, which the library does only
    after the writer holding the backlog has. The spectator's: reading again,
    it drains what the kernel still held and reaches the end of the
    connection, where a transport left open would go on being written to."""
    deadline = time.monotonic() + TEARDOWN_SECONDS
    handlers = None
    while time.monotonic() < deadline:
        handlers = (await metrics(base, token)).get(HANDLERS)
        if handlers is not None and handlers <= handlers_before:
            break
        await asyncio.sleep(0.2)
    server_side = handlers is not None and handlers <= handlers_before
    print(f"server: {HANDLERS} {handlers:.0f} (before the spectator {handlers_before:.0f}) - "
          f"{'handler and writer finished' if server_side else 'STILL RUNNING'}")

    transport.resume_reading()
    drained = 0
    ended = False
    while time.monotonic() < deadline + TEARDOWN_SECONDS:
        try:
            message = await asyncio.wait_for(ws.receive(), deadline + TEARDOWN_SECONDS - time.monotonic())
        except (asyncio.TimeoutError, TimeoutError):
            break
        if message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            ended = True
            break
        drained += len(message.data) if isinstance(message.data, (bytes, str)) else 0
    print(f"client: drained {drained} bytes the kernel held, then "
          f"{'the connection ended' if ended else 'it was STILL OPEN'}")
    return server_side and ended


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
