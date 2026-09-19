"""What a `watch_lobby` answer costs, first time and resumed, and a herd of them (#885).

Seeds ``--online`` accounts with presence sockets, ``--rooms`` public rooms and a
full chat backlog of retained lines, ticks the broadcaster once, then reports:

- the acknowledgement's size, raw and deflated through a fresh 32 KB window
  (the ``permessage-deflate`` context a new socket starts with), split by feed;
- the same with ``chatSince`` naming all but the last ``--newer`` lines, as a
  resync, a reconnect or a just-named visitor's re-handshake now sends;
- ``--herd`` lobbies asking between two ticks, as after a restart: wall time
  and how many presence/room baselines were built for them.

Runs in-process against the real handlers, with the socket layer stubbed.

    backend/.venv/bin/python benchmarks/lobby_baseline.py --online 100 400
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from time import perf_counter
from unittest.mock import AsyncMock

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

import socketio  # noqa: E402

from app.handlers import register_all_handlers  # noqa: E402
from app.rooms import RoomManager  # noqa: E402
from app.services.lobby_chat import LOBBY_CHAT_BACKLOG  # noqa: E402
from app.services.presence import LobbyBroadcaster, PresenceIdentity  # noqa: E402

LINES = [
    "anyone up for a round?", "gg", "that was close", "who wants to draw",
    "new room open, join!", "nice drawing", "how do I invite a friend", "hi all",
]


def _sizes(value) -> tuple[int, int]:
    raw = json.dumps(value, separators=(",", ":")).encode()
    deflate = zlib.compressobj(6, zlib.DEFLATED, -15)
    return len(raw), len(deflate.compress(raw) + deflate.flush(zlib.Z_SYNC_FLUSH))


async def measure(online: int, rooms: int, newer: int, herd: int) -> dict:
    manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_all_handlers(sio, manager)
    sessions: dict[str, dict] = {}
    sio.get_session = AsyncMock(side_effect=lambda sid, namespace=None: sessions.setdefault(sid, {}))
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()

    accounts = [str(uuid.uuid4()) for _ in range(online)]
    for index, account in enumerate(accounts):
        ctx.presence_identities.remember(
            PresenceIdentity(account, f"player_{index:04}", "#4f9", index % 5 == 0)
        )
        ctx.presence.note_socket_opened(f"sid-{index}", account)
        sessions[f"sid-{index}"] = {"user_id": account}
    for index in range(rooms):
        room = manager.create_room(name=f"Room number {index}", is_public=True)
        manager.add_player(room, f"seat{index}", user_id=accounts[-1 - index], is_anonymous=False)
    said = datetime.now(timezone.utc) - timedelta(hours=1)
    for index in range(LOBBY_CHAT_BACKLOG):
        author = index % 15
        ctx.lobby_chat.append(
            user_id=accounts[author], display_name=f"player_{author:04}", name_color="#4f9",
            is_anonymous=False, text=LINES[index % len(LINES)],
            sent_at=said + timedelta(seconds=37 * index), retained_message_id=str(uuid.uuid4()),
        )
    await ctx.presence_broadcaster.flush()
    watch = sio.handlers["/"]["watch_lobby"]

    full = await watch("sid-0", None)
    resumed = await watch(
        "sid-1",
        {"chatSince": ctx.lobby_chat.last_seq - newer, "chatEpoch": full["chatEpoch"]},
    )

    builds = 0
    original = LobbyBroadcaster.baseline_for_watcher

    def counting(self):
        nonlocal builds
        before = self._baseline_key
        answer = original(self)
        builds += self._baseline_key != before or before is None
        return answer

    LobbyBroadcaster.baseline_for_watcher = counting
    ctx.presence_broadcaster._baseline_key = None  # as if a tick had just moved
    started = perf_counter()
    for index in range(herd):
        sid = f"sid-{index % online}"
        ctx.clear_command_budget(sid)
        await watch(sid, None)
    herd_ms = (perf_counter() - started) * 1000
    LobbyBroadcaster.baseline_for_watcher = original

    return {
        "online": online,
        "rooms": rooms,
        "ack_raw_deflated": _sizes(full),
        "by_feed_deflated": {
            "presence": _sizes(full["players"])[1],
            "rooms": _sizes(full["rooms"])[1],
            "chat": _sizes(full["chat"])[1],
        },
        "resumed_ack_raw_deflated": _sizes(resumed),
        "resumed_lines": len(resumed["chat"]),
        "chat_line_deflated": round(_sizes(full["chat"])[1] / len(full["chat"]), 1),
        "herd": herd,
        "herd_ms": round(herd_ms, 1),
        "baselines_built_for_herd": builds,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--online", type=int, nargs="+", default=[100, 400])
    parser.add_argument("--rooms", type=int, default=40)
    parser.add_argument("--newer", type=int, default=3)
    parser.add_argument("--herd", type=int, default=400)
    args = parser.parse_args()
    for online in args.online:
        print(json.dumps(asyncio.run(measure(online, args.rooms, args.newer, args.herd))))


if __name__ == "__main__":
    main()
