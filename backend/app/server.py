"""Production Uvicorn runner that drains before closing live WebSockets."""

from __future__ import annotations

import asyncio
import os
import signal
import socket

import uvicorn

from app.deployment import shutdown_drain_seconds
from app.main import shutdown_coordinator, sio


# What an operator or a supervisor sends to stop the process. A repeat of any
# of them means "stop waiting", not "start again".
_TERMINATION_SIGNALS = frozenset({signal.SIGINT, signal.SIGTERM})


class DrainingServer(uvicorn.Server):
    """Stop listeners, drain existing games, then run normal Uvicorn shutdown."""

    def __init__(self, config: uvicorn.Config, *, coordinator=shutdown_coordinator):
        super().__init__(config)
        self.shutdown_coordinator = coordinator

    def handle_exit(self, sig: int, frame) -> None:
        """Let a *second* termination signal cut the drain short, whichever it is.

        R-SHUT-03 says a second termination signal abandons the remaining
        window, and an operator who has waited long enough sends the same
        signal again rather than a different one. Uvicorn's own handler only
        escalates on a repeated SIGINT, so a deployment sending SIGTERM twice -
        which is what a supervisor and a container stop both do - would be held
        for the rest of the window with no way to say otherwise.

        Set before delegating, so the escalation is in place by the time the
        drain next asks.
        """
        if self.should_exit and sig in _TERMINATION_SIGNALS:
            self.force_exit = True
        super().handle_exit(sig, frame)

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
    try:
        asyncio.run(DrainingServer(config).serve())
    except KeyboardInterrupt:
        # Uvicorn re-raises the SIGINT it captured once its own graceful
        # shutdown has finished, and asyncio.run turns that into a traceback.
        # The drain and the lifespan cleanup have both already run by now, so
        # printing a stack trace over a completed shutdown only makes an
        # operator wonder what crashed. Report the status a process killed by
        # SIGINT would report, which is what stock Uvicorn ends up with too.
        raise SystemExit(130) from None


if __name__ == "__main__":
    run()
