"""The threads CPU-bound drawing work runs on, so the event loop does not.

One worker (N-01) means one event loop for every room: a finished game's
drawings encoded on it, or the integrity audit's decode of a stored drawing,
stalls every room's strokes and timers for as long as it takes. Both run here
instead (#976, #1251). The work is pure Python for the most part and shares
the GIL, so the pool buys the loop its turns - a switch every few
milliseconds - and overlap with the database, not parallelism; that is why it
is narrow (`HISTORY_ENCODE_WORKERS`, two by default).

Its own threads rather than the default pool `asyncio.to_thread` shares with
blocking SMTP and everything else: a game's drawings must never wait behind a
slow mail relay for a thread (#976 review). Built on first use, so the value
that sizes it is one startup has validated.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from app.deployment import history_encode_workers

_POOL: ThreadPoolExecutor | None = None


def encode_pool() -> ThreadPoolExecutor:
    global _POOL
    if _POOL is None:
        _POOL = ThreadPoolExecutor(
            max_workers=history_encode_workers(), thread_name_prefix="history-encode"
        )
    return _POOL


async def off_loop(function, *args):
    """`function(*args)` on the pool, awaited from the loop."""
    return await asyncio.get_running_loop().run_in_executor(encode_pool(), function, *args)
