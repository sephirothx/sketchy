"""The production runner drains before Uvicorn closes established sockets."""

import signal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import uvicorn

from app import server
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


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_a_repeated_termination_signal_cuts_the_drain_short(sig):
    """R-SHUT-03: a *second* termination signal abandons the remaining window.

    Driven through `handle_exit` rather than by assigning `force_exit`, which
    is the whole point: Uvicorn's own handler escalates only on a repeated
    SIGINT, so a deployment sending SIGTERM twice - what a supervisor stop and
    a container stop both do - was held for the rest of the window with no way
    to say otherwise. A test that sets the flag itself cannot see that.
    """
    server = DrainingServer(uvicorn.Config("app.main:app"), coordinator=object())
    assert server.force_exit is False

    server.handle_exit(sig, None)
    assert server.should_exit is True
    assert server.force_exit is False, "the first signal starts the drain"

    server.handle_exit(sig, None)
    assert server.force_exit is True, "the second signal abandons it"


def test_an_unrelated_signal_does_not_abandon_the_drain():
    server = DrainingServer(uvicorn.Config("app.main:app"), coordinator=object())
    server.handle_exit(signal.SIGTERM, None)
    server.handle_exit(signal.SIGHUP, None)
    assert server.force_exit is False


def test_ctrl_c_exits_quietly_after_the_shutdown_it_already_completed():
    """Uvicorn re-raises the captured SIGINT; that must not print a traceback."""

    with (
        patch.object(server, "DrainingServer"),
        patch.object(server, "asyncio") as asyncio_module,
    ):
        asyncio_module.run.side_effect = KeyboardInterrupt
        with pytest.raises(SystemExit) as exit_info:
            server.run()

    assert exit_info.value.code == 130


def test_an_ordinary_return_from_serve_is_not_turned_into_an_error():
    with (
        patch.object(server, "DrainingServer"),
        patch.object(server, "asyncio") as asyncio_module,
    ):
        asyncio_module.run.return_value = None
        server.run()

    asyncio_module.run.assert_called_once()
