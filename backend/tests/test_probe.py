"""The probe's wire handling, checked without a server.

The end-to-end run against a live server is `tests/e2e/test_probe.py`; this
is the part that can be wrong on its own: the Engine.IO payload framing,
the Socket.IO packet grammar with acknowledgements and binary attachments,
and the textfile a scrape reads.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.probe import (
    DRAW_START_FRAME,
    PROBE_METRIC_NAMES,
    HttpResponse,
    PollingSocket,
    ProbeError,
    ProbeResult,
    _sessions,
    decode_payload,
    encode_payload,
    load_sessions,
    parse_message,
    save_sessions,
)


def test_a_polling_payload_round_trips_text_and_binary():
    packets = ["40", '42["guess",{"text":"cat"}]', b"\x10\xaa\xbb\xcc\x04\x20\x03\xb0\x04"]
    assert decode_payload(encode_payload(packets)) == packets
    assert decode_payload(b"") == []
    assert encode_payload([b"\x00\x01"]) == b"bAAE="


@pytest.mark.parametrize(
    ("packet", "expected"),
    [
        ('42["room_state",{"a":1}]', ("2", 0, None, ["room_state", {"a": 1}])),
        ('427["create_room",{"nickname":"x"}]', ("2", 0, 7, ["create_room", {"nickname": "x"}])),
        ("437[{\"ok\":true}]", ("3", 0, 7, [{"ok": True}])),
        ('451-["draw",{"_placeholder":true,"num":0}]', ("5", 1, None, ["draw", {"_placeholder": True, "num": 0}])),
        ('451-3["draw",{"_placeholder":true,"num":0},[1,2]]', ("5", 1, 3, ["draw", {"_placeholder": True, "num": 0}, [1, 2]])),
        ('40{"sid":"abc"}', ("0", 0, None, {"sid": "abc"})),
        ("40", ("0", 0, None, [])),
    ],
)
def test_socket_io_packets_are_split_into_kind_attachments_ack_and_data(packet, expected):
    assert parse_message(packet) == expected


def test_an_emit_with_binary_becomes_a_placeholder_packet_and_an_attachment():
    socket = PollingSocket("http://x", transport=None, cookie="", label="t")  # type: ignore[arg-type]
    packets = socket._packets("draw", (DRAW_START_FRAME, [3, 1]))
    assert packets == [
        '451-["draw",{"_placeholder":true,"num":0},[3,1]]',
        DRAW_START_FRAME,
    ]
    assert socket._packets("leave_room", ()) == ['42["leave_room"]']
    assert socket._packets("start_game", ({},), 4) == ['424["start_game",{}]']


def test_a_binary_event_is_delivered_once_its_attachment_has_arrived():
    socket = PollingSocket("http://x", transport=None, cookie="", label="t")  # type: ignore[arg-type]
    socket._handle('451-["draw",{"_placeholder":true,"num":0},[1,2,3,4]]')
    assert socket._events.empty()
    socket._handle(DRAW_START_FRAME)
    event = socket._events.get_nowait()
    assert event.name == "draw"
    assert event.args == [DRAW_START_FRAME, [1, 2, 3, 4]]


def test_the_textfile_carries_the_three_probe_series():
    result = ProbeResult(ok=True, steps={"guest": 0.1, "draw": 0.02}, duration_seconds=1.5)
    text = result.as_textfile()
    for name in PROBE_METRIC_NAMES:
        assert f"# TYPE {name} gauge" in text
    assert "sketchy_probe_success 1\n" in text
    assert 'sketchy_probe_step_seconds{step="draw"} 0.020' in text
    # The staleness page reads this; a file without it would never go stale.
    stamp = next(line for line in text.splitlines() if line.startswith("sketchy_probe_last_run_timestamp_seconds "))
    assert abs(int(stamp.split()[1]) - time.time()) < 5
    failed = ProbeResult(ok=False, failed_step="join", error="refused")
    assert "sketchy_probe_success 0\n" in failed.as_textfile()
    assert failed.as_json()["failedStep"] == "join"


# --- sessions kept between runs ---------------------------------------------------


class FakeServer:
    """Answers the two requests session handling makes, and counts provisioning."""

    def __init__(self, known: set[str], *, limit_after: int | None = None) -> None:
        self.known = set(known)
        self.provisioned = 0
        self.limit_after = limit_after

    rotates: set[str] = set()

    async def __call__(self, method, url, body, headers, *, wait_seconds=None):
        if url.endswith("/api/auth/me"):
            cookie = headers.get("Cookie", "")
            if cookie in self.rotates:
                successor = cookie + "-rotated"
                self.known.discard(cookie)
                self.known.add(successor)
                return HttpResponse(
                    200, {"set-cookie": successor + "; Path=/; HttpOnly"}, b'{"id":"u"}'
                )
            return HttpResponse(200, {}, b'{"id":"u"}' if cookie in self.known else b"null")
        if url.endswith("/api/auth/display-name"):
            if self.limit_after is not None and self.provisioned >= self.limit_after:
                return HttpResponse(429, {}, b"")
            self.provisioned += 1
            cookie = f"sketchy_session=fresh{self.provisioned}"
            self.known.add(cookie)
            return HttpResponse(200, {"set-cookie": cookie + "; Path=/; HttpOnly"}, b"{}")
        raise AssertionError(url)


@pytest.mark.asyncio
async def test_saved_sessions_are_reused_while_the_server_still_knows_them(tmp_path):
    state = tmp_path / "sessions.json"
    server = FakeServer(known=set())

    host, guest, provisioned = await _sessions("http://x/", server, state, "probe")
    assert provisioned and server.provisioned == 2
    assert load_sessions(state, "http://x") == {"host": host, "guest": guest}

    # A second run an hour later: nothing minted, the same cookies back.
    again = await _sessions("http://x/", server, state, "probe")
    assert again == (host, guest, False)
    assert server.provisioned == 2


@pytest.mark.asyncio
async def test_a_session_the_server_forgot_is_replaced_alone(tmp_path):
    state = tmp_path / "sessions.json"
    save_sessions(state, "http://x", {"host": "sketchy_session=old-host", "guest": "sketchy_session=old-guest"})
    server = FakeServer(known={"sketchy_session=old-guest"})

    host, guest, provisioned = await _sessions("http://x", server, state, "probe")
    assert provisioned and server.provisioned == 1
    assert guest == "sketchy_session=old-guest"
    assert host == "sketchy_session=fresh1"
    assert load_sessions(state, "http://x") == {"host": host, "guest": guest}


@pytest.mark.asyncio
async def test_a_state_file_for_another_server_is_not_trusted(tmp_path):
    state = tmp_path / "sessions.json"
    save_sessions(state, "http://elsewhere", {"host": "a", "guest": "b"})
    assert load_sessions(state, "http://x") == {}
    assert load_sessions(tmp_path / "missing.json", "http://x") == {}
    (tmp_path / "junk.json").write_text("not json")
    assert load_sessions(tmp_path / "junk.json", "http://x") == {}


@pytest.mark.asyncio
async def test_the_rate_limit_is_named_rather_than_reported_as_a_status():
    server = FakeServer(known=set(), limit_after=1)
    with pytest.raises(ProbeError) as caught:
        await _sessions("http://x", server, None, "probe")
    assert caught.value.step == "guest"
    assert "GUEST_PROVISION_LIMIT" in str(caught.value)


@pytest.mark.asyncio
async def test_a_rotated_session_is_adopted_not_kept(tmp_path):
    """Half a lifetime in, `/me` retires the cookie it was asked with and
    hands over a successor; the game must be played with the successor."""
    state = tmp_path / "sessions.json"
    save_sessions(state, "http://x", {"host": "sketchy_session=old-host", "guest": "sketchy_session=old-guest"})
    server = FakeServer(known={"sketchy_session=old-host", "sketchy_session=old-guest"})
    server.rotates = {"sketchy_session=old-host"}

    host, guest, provisioned = await _sessions("http://x", server, state, "probe")
    assert not provisioned
    assert host == "sketchy_session=old-host-rotated"
    assert guest == "sketchy_session=old-guest"
    assert load_sessions(state, "http://x") == {"host": host, "guest": guest}


# --- the receiver ------------------------------------------------------------------


class QuietThenChatty:
    """A transport whose first poll times out, whose second answers, and whose
    later polls hang the way a long-poll on a quiet socket does."""

    def __init__(self, *, then_fail: Exception | None = None) -> None:
        self.polls = 0
        self.waits: list[float | None] = []
        self.then_fail = then_fail

    async def __call__(self, method, url, body, headers, *, wait_seconds=None):
        assert method == "GET"
        self.polls += 1
        self.waits.append(wait_seconds)
        if self.polls == 1:
            raise TimeoutError("timed out")
        if self.polls == 2:
            return HttpResponse(200, {}, b'42["room_state",{"a":1}]')
        if self.then_fail is not None:
            raise self.then_fail
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_a_quiet_poll_is_retried_rather_than_ending_the_receiver():
    from app.probe import POLL_TIMEOUT_SECONDS

    transport = QuietThenChatty()
    socket = PollingSocket("http://x", transport, "c=1", label="t")
    socket.sid = "eio"
    socket._poller = asyncio.create_task(socket._poll_forever())
    try:
        event = await socket.expect("room_state", wait_seconds=2)
        assert event.args == [{"a": 1}]
        assert transport.waits[0] == POLL_TIMEOUT_SECONDS
        assert POLL_TIMEOUT_SECONDS > 25 + 20
    finally:
        await socket.close()


@pytest.mark.asyncio
async def test_a_failed_poll_is_reported_by_the_next_expect():
    transport = QuietThenChatty(then_fail=ConnectionRefusedError("gone"))
    socket = PollingSocket("http://x", transport, "c=1", label="draw")
    socket.sid = "eio"
    socket._poller = asyncio.create_task(socket._poll_forever())
    try:
        await socket.expect("room_state", wait_seconds=2)
        with pytest.raises(ProbeError) as caught:
            await socket.expect("draw", wait_seconds=2)
        assert "ConnectionRefusedError: gone" in str(caught.value)
        assert caught.value.step == "draw"
    finally:
        await socket.close()


class Scripted:
    """A transport that answers polls from a script, then hangs like a quiet long-poll."""

    def __init__(self, polls: list[bytes]) -> None:
        self._polls = list(polls)
        self.posted: list[bytes] = []

    async def __call__(self, method, url, body, headers, *, wait_seconds=None):
        if method == "POST":
            self.posted.append(body)
            return HttpResponse(200, {}, b"ok")
        if self._polls:
            return HttpResponse(200, {}, self._polls.pop(0))
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_a_refused_connection_fails_the_probe_with_the_servers_reason():
    """`44{...}` is the server saying no; it must not become a step timeout."""
    transport = Scripted([b'0{"sid":"eio1"}', b'44{"message":"This account is suspended."}'])
    socket = PollingSocket("http://x", transport, "c=1", label="connect")
    with pytest.raises(ProbeError) as caught:
        await socket.connect()
    assert "connection refused" in str(caught.value)
    assert "suspended" in str(caught.value)
    await socket.close()


@pytest.mark.asyncio
async def test_an_unreadable_packet_fails_the_waiting_call_and_expect():
    transport = Scripted([b'42["room_state",{"a":1}]', b"4}not json"])
    socket = PollingSocket("http://x", transport, "c=1", label="create")
    socket.sid = "eio"
    socket._poller = asyncio.create_task(socket._poll_forever())
    try:
        await socket.expect("room_state", wait_seconds=2)
        with pytest.raises(ProbeError) as caught:
            await socket.call("create_room", {"nickname": "x"}, wait_seconds=2)
        assert "unreadable packet" in str(caught.value)
        # And the socket stays failed for anything asked afterwards.
        with pytest.raises(ProbeError):
            await socket.expect("anything", wait_seconds=2)
    finally:
        await socket.close()
