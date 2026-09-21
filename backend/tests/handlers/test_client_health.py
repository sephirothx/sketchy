"""What only the client can see about its connection (#876, R-OBS-20).

A report is counts since the last one and the join-to-drawing times measured
since, sent at most once a minute and only when something happened. It is
observed into unlabelled series and nowhere else: labelled by the transport the
server sees it arrive on, never by anything the client chose, and never kept
against the account whose socket carried it.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, Mock

import socketio

from app.handlers import register_all_handlers as register_handlers
from app.handlers.budgets import SILENT_COMMANDS, CommandBudgetPolicy
from app.rooms import RoomManager
from app.services.afk import INACTIVITY_EXEMPT_COMMANDS
from app.services.telemetry import Telemetry

STORE_USERS = ("app.handlers.context", "app.handlers.connection")


def fresh_store(monkeypatch) -> Telemetry:
    store = Telemetry()
    for module in STORE_USERS:
        monkeypatch.setattr(f"{module}.telemetry", store)
    return store


def server(transport: str = "websocket"):
    sio = socketio.AsyncServer(async_mode="asgi")
    context = register_handlers(sio, RoomManager())
    sio.get_session = AsyncMock(return_value={})
    sio.emit = AsyncMock()
    sio.transport = Mock(return_value=transport)
    return sio, context


def report(sio, payload, sid="sid-1"):
    return sio.handlers["/"]["client_health"](sid, payload)


def counts(store: Telemetry) -> dict:
    return dict(store.client_health_events.items())


def joins(store: Telemetry) -> int:
    line = next(
        (l for l in store.prometheus_lines() if l.startswith("sketchy_client_join_to_drawing_seconds_count")),
        None,
    )
    return 0 if line is None else int(float(line.split()[-1]))


async def test_a_report_becomes_counts_labelled_by_the_transport_the_server_sees(monkeypatch):
    store = fresh_store(monkeypatch)
    sio, _ = server(transport="polling")

    answer = await report(sio, {
        "tailRejected": 1,
        "syncExhausted": 0,
        "droppedEmits": 3,
        "stallFallbacks": 1,
        "playbackCompressions": 7,
        "joinToDrawingMs": [420, 1800],
    })

    assert answer == {"ok": True}
    assert counts(store) == {
        ("tail_rejected", "polling"): 1,
        ("dropped_emit", "polling"): 3,
        ("stall_fallback", "polling"): 1,
        ("playback_compression", "polling"): 7,
    }, "a zero is not a series, and every label is the server's"
    assert dict(store.client_health_reports.items()) == {("polling",): 1}
    assert joins(store) == 2


async def test_a_report_is_every_field_optional_so_a_client_sends_what_it_has(monkeypatch):
    store = fresh_store(monkeypatch)
    sio, _ = server()

    assert await report(sio, {"joinToDrawingMs": [900]}) == {"ok": True}
    assert counts(store) == {}
    assert joins(store) == 1


async def test_anything_else_is_dropped_and_counted_and_nothing_is_observed(monkeypatch):
    """A report is bounded integers, so there is nothing in one for a client to
    put a name, an id or a sentence into - and anything shaped otherwise is
    refused whole rather than half-applied."""
    store = fresh_store(monkeypatch)
    sio, _ = server()

    malformed = [
        {"droppedEmits": True},  # a boolean is not a count
        {"droppedEmits": -1},
        {"droppedEmits": 1001},
        {"droppedEmits": 1.5},
        {"droppedEmits": "3"},
        {"playerId": "p-1", "droppedEmits": 1},  # nothing it does not name
        {"joinToDrawingMs": [60_001]},
        {"joinToDrawingMs": [-5]},
        {"joinToDrawingMs": [1, 2, 3, 4, 5, 6, 7, 8, 9]},
        {"joinToDrawingMs": ["fast"]},
        [1, 0, 3],
        "tailRejected",
        None,
    ]
    # One socket each: the budget is two a minute per socket, and the third
    # would be throttled - silently - before it was ever parsed.
    for index, payload in enumerate(malformed):
        answer = await report(sio, payload, sid=f"sid-{index}")
        assert answer["ok"] is False and answer["errorCode"] == "invalid_payload", payload

    assert counts(store) == {} and joins(store) == 0
    assert dict(store.client_health_reports.items()) == {}
    refused = dict(store.socket_refusals.items())
    assert refused.get(("client_health", "invalid_payload")) == len(malformed)


async def test_a_socket_the_server_cannot_read_is_labelled_unknown(monkeypatch):
    store = fresh_store(monkeypatch)
    sio, _ = server()
    sio.transport = Mock(side_effect=KeyError("gone"))

    await report(sio, {"stallFallbacks": 1})

    assert counts(store) == {("stall_fallback", "unknown"): 1}


async def test_nothing_about_a_report_is_logged(monkeypatch, caplog):
    """It arrives on an authenticated socket; the requirement is that it goes
    no further than the series (R-OBS-20)."""
    fresh_store(monkeypatch)
    sio, _ = server()

    with caplog.at_level(logging.DEBUG):
        await report(sio, {"droppedEmits": 2, "joinToDrawingMs": [700]})

    assert not [record for record in caplog.records if "client_health" in record.getMessage()]


def test_a_report_answers_to_its_own_budget_and_never_to_a_players():
    policy = CommandBudgetPolicy()
    assert policy.class_of("client_health") == "client_health"
    budget = policy.for_command("client_health")
    assert budget.limit == 2 and budget.window_seconds == 60.0


def test_a_report_is_fire_and_forget_and_says_nothing_about_the_keyboard():
    """Sent volatile, on the client's schedule: a refusal is not read, and a
    report is not a person doing something (the AFK check, #677)."""
    assert "client_health" in SILENT_COMMANDS
    assert "client_health" in INACTIVITY_EXEMPT_COMMANDS


async def test_a_third_report_inside_a_minute_is_throttled_without_a_word(monkeypatch):
    store = fresh_store(monkeypatch)
    sio, _ = server()

    first = await report(sio, {"droppedEmits": 1})
    second = await report(sio, {"droppedEmits": 1})
    third = await report(sio, {"droppedEmits": 1})

    assert first == second == {"ok": True}
    assert third is None, "fire-and-forget: a refusal nobody reads is only bytes"
    assert counts(store) == {("dropped_emit", "websocket"): 2}
