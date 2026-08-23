"""Production Uvicorn runner that drains before closing live WebSockets."""

from __future__ import annotations

import asyncio
import os
import socket

import uvicorn

from app.deployment import shutdown_drain_seconds
from app.main import shutdown_coordinator, sio


class DrainingServer(uvicorn.Server):
    """Stop listeners, drain existing games, then run normal Uvicorn shutdown."""

    def __init__(self, config: uvicorn.Config, *, coordinator=shutdown_coordinator):
        super().__init__(config)
        self.shutdown_coordinator = coordinator

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        # Stock Uvicorn closes live WebSockets before sending ASGI lifespan
        # shutdown. Close only the listeners here, keeping established
        # connections playable for the application-owned bounded drain.
        for server in self.servers:
            server.close()
        for sock in sockets or []:
            sock.close()

        # A second termination signal sets force_exit; honour it instead of
        # holding the process open for the rest of the configured window.
        await self.shutdown_coordinator.begin_shutdown(
            sio, should_abort=lambda: self.force_exit
        )

        # The listeners/sockets are already closed. Uvicorn now disconnects
        # established connections, waits its remaining tasks, and invokes the
        # lifespan cleanup; that cleanup sees the coordinator already stopped.
        await super().shutdown(sockets=[])


def _boolean_environment(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def run() -> None:
    shutdown_drain_seconds()
    config = uvicorn.Config(
        "app.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "info"),
        proxy_headers=_boolean_environment("PROXY_HEADERS", True),
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        # This bound begins after the application drain. Leave enough time for
        # the ordinary 10-second atomic finished-history write to settle.
        timeout_graceful_shutdown=15,
    )
    asyncio.run(DrainingServer(config).serve())


if __name__ == "__main__":
    run()
