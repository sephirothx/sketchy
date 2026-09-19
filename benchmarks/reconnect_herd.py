"""A server's clients all coming back at once, as after a restart, before and after #872.

Provisions ``--clients`` registered accounts, then replays what each browser
does when its connection returns, under two schedules:

- ``before``: socket.io's default first retry, 0.5-1.5 s after the close, and
  the REST refetches (friends, recovery address) fired the moment it connects;
- ``after``: the first attempt held a uniform 0-``--spread`` s, as a
  ``server_shutdown`` naming ``reconnectSpreadMs`` now asks, and the refetches
  spread 0-3 s behind the connection (`frontend/src/lib/reconnectPolicy.ts`).

Each client's return is the handshake, a ``watch_lobby`` (a lobby is the only
place a restarted process can put anyone: rooms died with the old one), and
``GET /api/friends`` + ``GET /api/auth/email``. Reports, per schedule, how long
until every client had its lobby back (p50/p95/max), how long a lobby baseline
took to answer, and the database pool's wait and timeouts over the herd, read
from ``/metrics``.

Needs a server with a PostgreSQL pool behind it (SQLite has no pool to wait
on), a metrics token, and provisioning limits raised for the setup:

    createdb ... sketchy_bench_herd && DATABASE_URL=... backend/.venv/bin/python -m app.db.migrate
    DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_bench_herd \\
      METRICS_TOKEN=x GUEST_PROVISION_LIMIT=100000 GUEST_PROVISION_DAILY_LIMIT=100000 \\
      AUTH_REGISTER_LIMIT=100000 AUTH_LOOKUP_LIMIT=100000 \\
      ./benchmarks/with_server.sh benchmarks/reconnect_herd.py --clients 400 --metrics-token x
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import secrets
import statistics
import sys
import time

import aiohttp
import socketio

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from app.protocol import PROTOCOL_VERSION  # noqa: E402

COOKIE = "sketchy_session"
POST_RECONNECT_JITTER_S = 3.0


def _cookie_of(response: aiohttp.ClientResponse) -> str | None:
    for name, morsel in response.cookies.items():
        if name.endswith(COOKIE):
            return f"{name}={morsel.value}"
    return None


async def provision(http: aiohttp.ClientSession, base: str, index: int, run: str) -> str:
    name = f"herd{run}{index:04}"
    async with http.post(f"{base}/api/auth/display-name", json={"displayName": name}) as response:
        if response.status != 200:
            raise RuntimeError(f"guest {name}: HTTP {response.status}")
        cookie = _cookie_of(response)
    async with http.post(
        f"{base}/api/auth/register",
        json={"username": name, "password": secrets.token_urlsafe(12)},
        headers={"Cookie": cookie},
    ) as response:
        if response.status != 200:
            raise RuntimeError(f"register {name}: HTTP {response.status} {await response.text()}")
        return _cookie_of(response) or cookie


async def scrape(http: aiohttp.ClientSession, base: str, token: str) -> dict:
    async with http.get(f"{base}/metrics", headers={"Authorization": f"Bearer {token}"}) as response:
        if response.status != 200:
            raise RuntimeError(f"/metrics: HTTP {response.status}")
        text = await response.text()
    buckets: dict[float, float] = {}
    values: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name, _, raw = line.rpartition(" ")
        try:
            number = float(raw)
        except ValueError:
            continue
        if name.startswith("sketchy_db_pool_wait_seconds_bucket{"):
            le = name.split('le="')[1].split('"')[0]
            buckets[float("inf") if le == "+Inf" else float(le)] = number
        elif name in ("sketchy_db_pool_wait_seconds_sum", "sketchy_db_pool_wait_seconds_count"):
            values[name] = number
        elif name.startswith("sketchy_db_pool_timeouts_total"):
            values["timeouts"] = values.get("timeouts", 0.0) + number
    return {"buckets": buckets, **values}


def pool_delta(before: dict, after: dict) -> dict:
    """The herd's own share of the pool histogram: an upper bound per quantile."""
    edges = sorted(after["buckets"])
    counts = [after["buckets"][e] - before["buckets"].get(e, 0.0) for e in edges]
    total = counts[-1] if counts else 0.0

    def quantile(fraction: float) -> float | None:
        if total <= 0:
            return None
        for edge, count in zip(edges, counts, strict=True):
            if count >= fraction * total:
                return edge
        return edges[-1]

    waited = after.get("sketchy_db_pool_wait_seconds_sum", 0.0) - before.get(
        "sketchy_db_pool_wait_seconds_sum", 0.0
    )
    return {
        "checkouts": int(total),
        "wait_total_s": round(waited, 3),
        "wait_p95_le_s": quantile(0.95),
        "wait_max_le_s": quantile(1.0),
        "timeouts": int(after.get("timeouts", 0.0) - before.get("timeouts", 0.0)),
    }


async def come_back(
    base: str, cookie: str, schedule: str, spread: float, http: aiohttp.ClientSession, rng: random.Random
) -> dict:
    hold = rng.uniform(0.5, 1.5) if schedule == "before" else rng.uniform(0.0, spread)
    started = time.monotonic()
    await asyncio.sleep(hold)
    sio = socketio.AsyncClient(reconnection=False, websocket_extra_options={"compress": 15})
    try:
        await sio.connect(
            base, headers={"Cookie": cookie}, auth={"protocol": PROTOCOL_VERSION},
            transports=["websocket"], wait_timeout=30,
        )

        async def refetch() -> float:
            if schedule == "after":
                await asyncio.sleep(rng.uniform(0.0, POST_RECONNECT_JITTER_S))
            began = time.monotonic()
            for path in ("/api/friends", "/api/auth/email"):
                async with http.get(f"{base}{path}", headers={"Cookie": cookie}) as response:
                    await response.read()
            return time.monotonic() - began

        rest = asyncio.create_task(refetch())
        asked = time.monotonic()
        answer = await sio.call("watch_lobby", {}, timeout=30)
        baseline_s = time.monotonic() - asked
        back_s = time.monotonic() - started
        rest_s = await rest
        return {
            "ok": bool(answer and answer.get("ok")),
            "back_s": back_s,
            "baseline_s": baseline_s,
            "rest_s": rest_s,
            "done_s": time.monotonic() - started,
        }
    except Exception as error:  # noqa: BLE001 - a failed return is a result
        return {"ok": False, "error": type(error).__name__}
    finally:
        await sio.disconnect()


def _q(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * fraction))], 3)


async def herd(base: str, cookies: list[str], schedule: str, spread: float, token: str, seed: int) -> dict:
    rng = random.Random(seed)
    connector = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=connector) as http:
        before = await scrape(http, base, token)
        began = time.monotonic()
        results = await asyncio.gather(
            *(come_back(base, cookie, schedule, spread, http, rng) for cookie in cookies)
        )
        wall = time.monotonic() - began
        await asyncio.sleep(1.5)  # let the last histogram observations land
        after = await scrape(http, base, token)
    ok = [r for r in results if r["ok"]]
    backs = [r["back_s"] for r in ok]
    baselines = [r["baseline_s"] for r in ok]
    rests = [r["rest_s"] for r in ok]
    return {
        "schedule": schedule,
        "clients": len(cookies),
        "failed": len(results) - len(ok),
        "all_back_s": round(max(backs), 3) if backs else None,
        "back_p50_s": _q(backs, 0.5) if backs else None,
        "back_p95_s": _q(backs, 0.95) if backs else None,
        "baseline_p50_s": _q(baselines, 0.5) if baselines else None,
        "baseline_p95_s": _q(baselines, 0.95) if baselines else None,
        "rest_p95_s": _q(rests, 0.95) if rests else None,
        "wall_s": round(wall, 3),
        "pool": pool_delta(before, after),
    }


async def main_async(args) -> None:
    base = args.base_url.rstrip("/")
    run = secrets.token_hex(2)
    connector = aiohttp.TCPConnector(limit=32)
    async with aiohttp.ClientSession(connector=connector) as http:
        cookies = []
        for start in range(0, args.clients, 32):
            batch = range(start, min(start + 32, args.clients))
            cookies += await asyncio.gather(*(provision(http, base, i, run) for i in batch))
    print(f"provisioned {len(cookies)} registered accounts", file=sys.stderr)
    for schedule in args.schedules:
        # Quiet between runs, so one herd's tail is not the next one's load.
        await asyncio.sleep(3)
        print(json.dumps(await herd(base, cookies, schedule, args.spread, args.metrics_token, args.seed)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--clients", type=int, default=400)
    parser.add_argument("--spread", type=float, default=10.0, help="reconnectSpreadMs, in seconds")
    parser.add_argument("--schedules", nargs="+", default=["before", "after"], choices=["before", "after"])
    parser.add_argument("--metrics-token", default=os.environ.get("METRICS_TOKEN"))
    parser.add_argument("--seed", type=int, default=872)
    args = parser.parse_args()
    if not args.metrics_token:
        parser.error("--metrics-token (or METRICS_TOKEN) is required: the pool is read from /metrics")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
