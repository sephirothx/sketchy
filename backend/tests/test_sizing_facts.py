"""The sizing facts storage decisions have been guessing at (#895).

Each one is recorded where the thing is written, after it is written, and
carries no user identifier: a format, a table, a message kind and audience.
"""
from __future__ import annotations

from app.domain_values import RuntimeEventType
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from app.services.runtime_metrics import RuntimeMetrics
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
        # Counted, and nothing more (#965): the distribution is the histogram
        # above, kept by Prometheus for as long as its retention says, so the
        # database holds no row per drawing and no daily size buckets.
        assert recorder.totals().get(RuntimeEventType.DRAWING_ENCODED.value) == 1
        assert not [event for event in recorder.snapshot(100)
                    if event.event_type == RuntimeEventType.DRAWING_ENCODED.value]
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
