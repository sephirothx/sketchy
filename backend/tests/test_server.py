"""The production runner drains before Uvicorn closes established sockets."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import uvicorn

from app.server import DrainingServer


def _server(coordinator):
    """A DrainingServer wired to run Uvicorn's real shutdown path."""

    server = DrainingServer(uvicorn.Config("app.main:app"), coordinator=coordinator)
    # serve() would install these; shutdown() is being exercised on its own.
    server.lifespan = coordinator
    return server


@pytest.mark.asyncio
async def test_listener_closes_then_application_drains_then_uvicorn_disconnects():
    timeline = []

    class Coordinator:
        async def begin_shutdown(self, sio, *, should_abort=None):
            timeline.append("drain")

        async def shutdown(self):
            # Uvicorn's own shutdown ends by running ASGI lifespan cleanup, so
            # this landing at the end proves the drain happened before it.
            timeline.append("lifespan")

    server = _server(Coordinator())
    listener = SimpleNamespace(
        close=Mock(side_effect=lambda: timeline.append("listener")),
        wait_closed=AsyncMock(),
    )
    inherited_socket = SimpleNamespace(
        close=Mock(side_effect=lambda: timeline.append("socket"))
    )
    server.servers = [listener]

    await server.shutdown([inherited_socket])

    # Stock Uvicorn closes the listeners again once it takes over; what matters
    # is that the drain sits between the first close and the lifespan cleanup.
    assert timeline == ["listener", "socket", "drain", "listener", "lifespan"]


@pytest.mark.asyncio
async def test_a_forced_exit_is_offered_to_the_drain():
    """A second termination signal must be able to cut the window short."""

    captured = []

    class Coordinator:
        async def begin_shutdown(self, sio, *, should_abort=None):
            captured.append(should_abort)

        async def shutdown(self):
            pass

    server = _server(Coordinator())
    server.servers = []

    await server.shutdown([])

    should_abort = captured[0]
    assert should_abort is not None
    assert should_abort() is False
    server.force_exit = True
    assert should_abort() is True
