"""The served stack, run for real: uvloop, httptools, and h11's head bound (#977)."""
from __future__ import annotations

import asyncio
import logging
import socket
import threading

import pytest
import uvicorn

from app.http_transport import MAX_REQUEST_HEAD_BYTES
from app.server import EVENT_LOOP, HTTP_PROTOCOL, DrainingServer


async def _app(scope, receive, send):
    if scope["type"] != "http":
        return
    # Read the request whole before answering: closing on unread bytes makes
    # Linux reset the connection, which a client reads as no answer at all.
    received = 0
    while True:
        message = await receive()
        received += len(message.get("body", b""))
        if not message.get("more_body"):
            break
    body = b"%s %s" % (scope["method"].encode(), b"ok" if not received else b"%d" % received)
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class _NoDrain:
    async def begin_shutdown(self, _sio, should_abort=None):
        return None


@pytest.fixture
def served(caplog):
    """A real server on the production loop factory and parser, in a thread."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    config = uvicorn.Config(_app, loop=EVENT_LOOP, http=HTTP_PROTOCOL, log_level="info", log_config=None, lifespan="off")
    server = DrainingServer(config, coordinator=_NoDrain())
    caplog.set_level(logging.INFO, logger="sketchy.server")

    def run():
        asyncio.run(server.serve(sockets=[listener]), loop_factory=config.get_loop_factory())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        threading.Event().wait(0.01)
    try:
        yield listener.getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()


def _exchange(port: int, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(request)
        client.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := client.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks)


def test_the_production_stack_serves_and_says_what_it_runs_on(served, caplog):
    answer = _exchange(served, b"GET / HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n")
    assert answer.startswith(b"HTTP/1.1 200") and answer.endswith(b"GET ok")
    # Logged as the server started, which was during the fixture's setup.
    started = [record.getMessage() for record in caplog.get_records("setup")]
    assert "serving on uvloop.Loop with BoundedHttpToolsProtocol" in started


def test_a_request_head_past_the_bound_is_refused_with_431(served):
    """httptools alone held a 300 MB header whole: 39 MB -> 7.35 GB."""
    big = b"x" * (MAX_REQUEST_HEAD_BYTES + 1024)
    answer = _exchange(served, b"GET / HTTP/1.1\r\nHost: t\r\nX-Big: " + big + b"\r\n\r\n")
    assert answer.startswith(b"HTTP/1.1 431")


def test_a_body_is_never_counted_as_head(served):
    """A large body that arrives in the same reads as its headers is a body."""
    body = b"y" * (MAX_REQUEST_HEAD_BYTES * 8)
    request = (
        b"POST / HTTP/1.1\r\nHost: t\r\nConnection: close\r\nContent-Length: "
        + str(len(body)).encode() + b"\r\n\r\n" + body
    )
    answer = _exchange(served, request)
    assert answer.startswith(b"HTTP/1.1 200") and answer.endswith(b"POST %d" % len(body))


def test_headers_just_under_the_bound_are_accepted(served):
    filler = b"z" * (MAX_REQUEST_HEAD_BYTES - 200)
    answer = _exchange(served, b"GET / HTTP/1.1\r\nHost: t\r\nConnection: close\r\nX-Fill: " + filler + b"\r\n\r\n")
    assert answer.startswith(b"HTTP/1.1 200")


def test_a_head_that_never_completes_is_refused_before_it_grows(served):
    """The memory case: a header sent a piece at a time and never finished."""
    with socket.create_connection(("127.0.0.1", served), timeout=5) as client:
        client.sendall(b"GET / HTTP/1.1\r\nHost: t\r\nX-Big: ")
        answer = b""
        try:
            for _ in range(64):
                client.sendall(b"x" * 4096)
                threading.Event().wait(0.002)
        except (BrokenPipeError, ConnectionResetError):
            pass
        try:
            while chunk := client.recv(65536):
                answer += chunk
        except ConnectionResetError:
            pass
    assert answer.startswith(b"HTTP/1.1 431")
