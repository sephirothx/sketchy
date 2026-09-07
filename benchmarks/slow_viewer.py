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
4. The spectator comes back, joins again, and takes a fresh sync, whose
   history hash is checked against the header the server sent: recovery is a
   full, verified canvas, never a partial stream.

Usage:
  METRICS_TOKEN=x benchmarks/with_server.sh benchmarks/slow_viewer.py
  (benchmarks/run_load.sh sets the same environment; this script only needs
  the token and the raised guest limits)
"""
from __future__ import annotations

import asyncio
import json
import os
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
from app.live_drawing import encode_live_drawing
from app.protocol import PROTOCOL_VERSION

COOKIE = "sketchy_session"


async def provision(base: str, name: str) -> str:
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{base}/api/auth/display-name", json={"displayName": name}) as response:
            assert response.status == 200, response.status
            return response.cookies[COOKIE].value


async def metrics(base: str, token: str) -> dict[str, float]:
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{base}/metrics", headers={"Authorization": f"Bearer {token}"}) as response:
            text = await response.text()
    out: dict[str, float] = {}
    for line in text.splitlines():
        if line.startswith("sketchy_socket_backlog") or line.startswith("sketchy_sockets_connected"):
            name, _, value = line.rpartition(" ")
            out[name] = float(value)
    return out


async def client(base: str, name: str) -> socketio.AsyncClient:
    token = await provision(base, name)
    sio = socketio.AsyncClient(reconnection=False)
    await sio.connect(base, headers={"Cookie": f"{COOKIE}={token}"}, auth={"protocol": PROTOCOL_VERSION}, transports=["websocket"])
    return sio


async def raw_spectator(base: str, name: str, code: str):
    """A raw WebSocket spectator: session, socket, and the join sent."""
    token = await provision(base, name)
    session = aiohttp.ClientSession()
    ws = await session.ws_connect(base.replace("http", "ws", 1) + "/socket.io/?EIO=4&transport=websocket", headers={"Cookie": f"{COOKIE}={token}"})
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
            await sio.call("select_prompt", {"prompt": payload["choices"][0]})
            if not chosen.done():
                chosen.set_result(sio)

        async def on_reset(payload):
            identity["reset"] = payload

        sio.on("your_prompt_choices", on_choices)
        sio.on("canvas_reset", on_reset)

    wire(host)
    wire(guest)
    assert (await host.call("start_game", {}))["ok"]
    drawer = await asyncio.wait_for(chosen, 15)
    await asyncio.sleep(0.5)
    _, generation, sequence, _ = identity["reset"]

    # A near-ceiling drawing, paced under the drawing budget (100 frames
    # per 2 s): 120 strokes of 200 points is 24 000 of the 25 000 allowed.
    for stroke in range(120):
        sequence += 1
        await drawer.emit("draw", (encode_live_drawing("draw_start", {"x": 0.05, "y": 0.05, "color": "#000000", "width": 4}), [generation, sequence]))
        points = [{"x": 0.05 + (index % 40) / 50, "y": 0.05 + (index // 40) / 8} for index in range(200)]
        await drawer.emit("draw", encode_live_drawing("draw_move", {"points": points}))
        await drawer.emit("draw", encode_live_drawing("draw_end"))
        await asyncio.sleep(0.07)
    await asyncio.sleep(1.0)
    print(f"drawing staged: {sequence} actions on the canvas")

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
    await ws.close()
    await session.close()

    # Recovery: come back, join again, take the sync, check its hash.
    verified = False
    if closed_at is not None:
        session, ws = await raw_spectator(base, "Slowpoke", code)
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
    if not verified:
        print("FAILED: the recovered canvas did not verify")
        return 1
    print("PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
