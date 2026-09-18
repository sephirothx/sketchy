"""The sizing facts storage decisions have been guessing at (#895).

Each one is recorded where the thing is written, after it is written, and
carries no user identifier: a format, a table, a message kind and audience.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain_values import RuntimeEventType
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from app.services.runtime_metrics import (
    RuntimeMetrics,
    daily_totals,
    flush_events,
    size_bucket_label,
)
from app.services.telemetry import telemetry

from tests.dbfixtures import create_test_db
from tests.test_drawing_reactions import record_game, registered


def _counts(histogram) -> dict[tuple[str, ...], int]:
    return {row["labels"]: row["count"] for row in histogram.per_label()}


async def test_a_written_game_reports_its_drawings_and_rows_per_table(monkeypatch):
    import app.repositories.sqlalchemy as repository

    recorder = RuntimeMetrics()
    monkeypatch.setattr(repository, "metrics", recorder)
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        history = SqlAlchemyGameHistoryRepository(factory)
        drawer = await registered(users, "Drawer")
        guesser = await registered(users, "Guesser")
        stored_before = _counts(telemetry.drawing_stored_bytes)
        rows_before = _counts(telemetry.game_rows)

        await record_game(history, drawer=drawer.id, reactor=guesser.id, reactions="default")

        stored = _counts(telemetry.drawing_stored_bytes)
        formats = {key for key in stored if stored[key] != stored_before.get(key, 0)}
        assert len(formats) == 1 and next(iter(formats))[0] in {"SKCD", "SKCH"}
        assert telemetry.drawing_actions.count() >= 1
        rows = _counts(telemetry.game_rows)
        grew = {key[0] for key in rows if rows[key] != rows_before.get(key, 0)}
        assert {"game_records", "game_participants", "turn_records", "turn_drawings",
                "turn_drawing_reactions", "turn_participant_outcomes"} <= grew
        # The long view: the stored size as a runtime event, beside the wire size.
        encoded = [event for event in recorder.snapshot(100)
                   if event.event_type == RuntimeEventType.DRAWING_ENCODED.value]
        assert len(encoded) == 1 and encoded[0].value > 0
        assert encoded[0].user_id is None and encoded[0].room_id is None
    finally:
        await engine.dispose()


def test_sizes_fall_into_fixed_named_buckets():
    assert size_bucket_label(0) == "le_1k"
    assert size_bucket_label(1024) == "le_1k"
    assert size_bucket_label(1025) == "le_4k"
    assert size_bucket_label(200_000) == "le_256k"
    assert size_bucket_label(1_048_576) == "le_1m"
    assert size_bucket_label(1_048_577) == "gt_1m"


async def test_the_daily_roll_up_keeps_the_drawing_size_distribution():
    """Raw events go after thirty days; the daily table is permanent but keeps
    a count, a sum and a maximum. The buckets are what survive of the shape."""
    factory, engine = await create_test_db()
    try:
        recorder = RuntimeMetrics()
        at = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
        for size in (500, 3000, 3500, 2_000_000):
            recorder.record(RuntimeEventType.DRAWING_STORED, value=size, now=at)
        recorder.record(RuntimeEventType.DRAWING_ENCODED, value=900, now=at)
        recorder.record(RuntimeEventType.GAME_STARTED, now=at)
        await flush_events(factory, recorder=recorder)

        totals = {row["metric"]: row["occurrences"] for row in await daily_totals(factory, days=3650, now=at)}
        assert totals["drawing.stored"] == 4
        assert totals["drawing.stored.le_1k"] == 1
        assert totals["drawing.stored.le_4k"] == 2
        assert totals["drawing.stored.gt_1m"] == 1
        assert totals["drawing.encoded.le_1k"] == 1
        assert not any(metric.startswith("game.started.") for metric in totals)
    finally:
        await engine.dispose()


def test_retained_lines_count_by_kind_and_audience_with_their_recipients():
    before = telemetry.messages_retained.get(("chat", "room"))
    telemetry.message_retained("chat", "room", 6)
    assert telemetry.messages_retained.get(("chat", "room")) == before + 1
    assert any(row["labels"] == ("room",) for row in telemetry.message_recipients.per_label())
    exposition = "\n".join(telemetry.prometheus_lines())
    for family in (
        "sketchy_drawing_stored_bytes",
        "sketchy_drawing_raw_bytes",
        "sketchy_drawing_actions",
        "sketchy_drawing_encode_seconds",
        "sketchy_history_rows_per_game",
        "sketchy_handoff_envelope_bytes",
        "sketchy_messages_retained_total",
        "sketchy_message_recipients",
        "sketchy_export_artifact_bytes",
    ):
        assert f"# TYPE {family} " in exposition, family
