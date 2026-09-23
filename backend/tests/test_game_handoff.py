"""The durable handoff of finished games (#541), on the real store.

Every crash point the issue names is a row state here: before and after
staging, after the claim, after the history commit, after the usage commit,
and a claim whose holder died. The in-memory store under `tests/handlers`
proves the flow; this proves the SQL store and the replay against the real
repositories, on SQLite by default and on PostgreSQL under
`TEST_DATABASE_URL`.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, update

import app.services.game_handoff as handoff_module
from app.db.models import FinishedGameEnvelope as EnvelopeRow
from app.db.models import GameRecord, PromptUsageBatch, PromptUsageFact, TurnDrawing
from app.db.models import generate_uuid
from app.repositories.interfaces import (
    BundledPromptDefinition,
    GameHistoryConflictError,
    GameParticipantInput,
    GameRecordInput,
    PromptPickTotals,
    PromptUsage,
    PromptUsageConflictError,
    ScoreEventInput,
    TurnDrawingInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)
from app.services.game_handoff import (
    ENVELOPE_VERSION,
    MAX_ATTEMPTS,
    RETRY_BACKOFF_SECONDS,
    STALE_CLAIM_AFTER,
    EnvelopeConflictError,
    EnvelopeTooLarge,
    FinishedGameEnvelope,
    FinishedGameHandoffWorker,
    ReplayOutcome,
    SqlEnvelopeStore,
    StageOutcome,
    decode_envelope,
    encode_envelope,
)
from app.services.game_history import GameHistoryWrite
from app.services.sweeps import SweepBudget
from tests.dbfixtures import create_test_db


_FRAMES = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "canvas_protocol_v1.json").read_text()
)["histories"]


def _frame(index: int) -> bytes:
    """A real binary canvas history: the store refuses anything else."""
    return bytes.fromhex(_FRAMES[index]["binary"])

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now


class RecordingPrompts:
    """A prompt-list repository that only remembers the usage it was handed."""

    def __init__(self, *, raise_with: Exception | None = None) -> None:
        self.batches: list[tuple[tuple[str, ...], PromptUsage]] = []
        self.raise_with = raise_with

    async def record_prompt_usage(self, revision_ids, usage) -> None:
        if self.raise_with is not None:
            raise self.raise_with
        self.batches.append((tuple(revision_ids), usage))


@pytest_asyncio.fixture
async def env():
    session_factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(session_factory)
    history = SqlAlchemyGameHistoryRepository(session_factory)
    store = SqlEnvelopeStore(session_factory)
    try:
        yield session_factory, users, history, store
    finally:
        await engine.dispose()


def history_for(game_id: str, winner: str, loser: str, *, drawing: bytes | None = None) -> GameHistoryWrite:
    drawing = _frame(0) if drawing is None else drawing
    winner_seat, loser_seat, turn_id = (str(generate_uuid()) for _ in range(3))
    return GameHistoryWrite(
        record=GameRecordInput(
            id=game_id,
            room_name="Studio",
            scoring_mode="default",
            scoring_version=1,
            score_ledger_version=1,
            rule_snapshot_version=1,
            rule_snapshot={"schemaVersion": 1, "scoring": {"mode": "default"}},
            hint_mode="checkpoints",
            drawing_seconds=90,
            total_rounds=1,
            player_count=2,
            started_at=NOW,
            finished_at=NOW + timedelta(minutes=10),
            visibility="public",
        ),
        participants=[
            GameParticipantInput(user_id=winner, final_score=300, final_rank=1, seat_id=winner_seat, display_name="Ann"),
            GameParticipantInput(user_id=loser, final_score=100, final_rank=2, seat_id=loser_seat, display_name="Bob"),
        ],
        turns=[
            TurnRecordInput(
                id=turn_id,
                round_number=1,
                turn_number=1,
                drawer_user_id=winner,
                drawer_seat_id=winner_seat,
                prompt="jackpot",
                duration_seconds=42.5,
                guesser_count=1,
                participant_outcomes=(
                    TurnParticipantOutcomeInput(
                        seat_id=loser_seat,
                        user_id=loser,
                        eligible=True,
                        eligibility_reason="eligible",
                        outcome="correct",
                        terminal_state="active",
                        correct_guess_time_seconds=12.0,
                        points_awarded=100,
                    ),
                ),
            )
        ],
        score_events=[
            ScoreEventInput(participant_seat_id=loser_seat, participant_user_id=loser, turn_id=turn_id, event_order=1, event_type="guess_award", points_delta=100),
            ScoreEventInput(participant_seat_id=winner_seat, participant_user_id=winner, turn_id=turn_id, event_order=2, event_type="drawer_bonus", points_delta=100),
            ScoreEventInput(participant_seat_id=winner_seat, participant_user_id=winner, event_order=3, event_type="correction", points_delta=200, corrects_event_order=2),
        ],
        drawings=[TurnDrawingInput(turn_id=turn_id, payload=drawing)],
        reactions=[],
    )


def usage_for(game_id: str) -> PromptUsage:
    return PromptUsage(
        offers={"11111111-1111-7111-8111-111111111111": 2},
        picks={"11111111-1111-7111-8111-111111111111": PromptPickTotals(1, 1, 1)},
        batch_id=game_id,
        occurred_at=NOW + timedelta(minutes=10),
        scoring_mode="default",
        hint_mode="checkpoints",
    )


async def two_players(users):
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    return ann.id, bob.id


def worker_for(store, history, prompts=None, *, clock=None, **kwargs) -> FinishedGameHandoffWorker:
    return FinishedGameHandoffWorker(
        store, game_history_repo=history, prompt_list_repo=prompts, clock=clock or Clock(), **kwargs
    )


async def rows(session_factory) -> list[EnvelopeRow]:
    async with session_factory() as session:
        return list((await session.scalars(select(EnvelopeRow))).all())


# --- the envelope -----------------------------------------------------------


def test_an_envelope_survives_the_round_trip_whole():
    game_id = str(generate_uuid())
    envelope = FinishedGameEnvelope(history_for(game_id, "a", "b"), usage_for(game_id), ("rev-1",))

    decoded = decode_envelope(encode_envelope(envelope), ENVELOPE_VERSION)

    assert decoded == envelope
    assert decoded.history.record.started_at.tzinfo is not None
    assert decoded.history.drawings[0].payload == _frame(0)


def test_a_version_this_build_cannot_read_is_refused_not_guessed():
    envelope = FinishedGameEnvelope(history_for(str(generate_uuid()), "a", "b"))
    with pytest.raises(handoff_module.EnvelopeUnreadable):
        decode_envelope(encode_envelope(envelope), ENVELOPE_VERSION + 1)
    with pytest.raises(handoff_module.EnvelopeUnreadable):
        decode_envelope(b"not an envelope", ENVELOPE_VERSION)


# --- staging ---------------------------------------------------------------------


async def test_staging_is_idempotent_by_content_and_refuses_a_different_game_under_the_same_id(env):
    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    game_id = str(generate_uuid())
    worker = worker_for(store, history)

    envelope = FinishedGameEnvelope(history_for(game_id, ann, bob))
    assert await worker.stage(envelope) is StageOutcome.STAGED
    assert await worker.stage(envelope) is StageOutcome.DUPLICATE
    # The same id with different content is a bug, and says so.
    with pytest.raises(EnvelopeConflictError):
        await worker.stage(FinishedGameEnvelope(history_for(game_id, ann, bob, drawing=_frame(1))))
    [row] = await rows(session_factory)
    assert (row.state, row.attempts, row.history_state, row.usage_state) == ("pending", 0, "pending", "none")


async def test_an_envelope_past_the_ceiling_is_refused_before_it_is_written(env):
    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    worker = worker_for(store, history, max_bytes=64)
    with pytest.raises(EnvelopeTooLarge):
        await worker.stage(FinishedGameEnvelope(history_for(str(generate_uuid()), ann, bob)))
    assert await rows(session_factory) == []


# --- replay --------------------------------------------------------------------


async def test_a_staged_game_is_written_into_history_and_the_row_goes(env):
    from app.services.telemetry import telemetry

    writes_before = telemetry.history_write_seconds.count()
    lags_before = telemetry.history_persist_lag.count()
    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    game_id = str(generate_uuid())
    outcomes: list[tuple[str, str]] = []
    worker = worker_for(store, history, RecordingPrompts(), on_outcome=lambda g, s: outcomes.append((g, s)))
    await worker.stage(FinishedGameEnvelope(history_for(game_id, ann, bob), usage_for(game_id), ("rev-1",)))

    report = await worker.drain()

    assert (report.recorded, report.retried, report.failed) == (1, 0, 0)
    assert await rows(session_factory) == []
    assert outcomes == [(game_id, "recorded")]
    # Timed, and its lateness measured against the game's end (#892).
    assert telemetry.history_write_seconds.count() == writes_before + 1
    assert telemetry.history_persist_lag.count() == lags_before + 1
    games = await history.get_user_games(ann, requesting_user_id=ann)
    assert [g.id for g in games] == [game_id]
    async with session_factory() as session:
        [drawing] = (await session.scalars(select(TurnDrawing))).all()
        assert drawing.status == "ready"
    [(revision_ids, usage)] = worker._prompt_list_repo.batches
    assert revision_ids == ("rev-1",) and usage.batch_id == game_id


async def test_a_crash_between_the_two_parts_resumes_only_what_is_missing(env):
    """History committed, then the process died before the usage write. The
    next claim finds `history_state = done` and writes the usage alone."""
    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    game_id = str(generate_uuid())
    dying_prompts = RecordingPrompts(raise_with=RuntimeError("process died here"))
    clock = Clock()
    worker = worker_for(store, history, dying_prompts, clock=clock)
    await worker.stage(FinishedGameEnvelope(history_for(game_id, ann, bob), usage_for(game_id), ("rev-1",)))

    assert (await worker.replay_one()).outcome is ReplayOutcome.RETRIED
    [row] = await rows(session_factory)
    assert (row.state, row.history_state, row.usage_state) == ("pending", "done", "pending")

    saves = 0
    original = history.save_game

    async def counting_save(*args, **kwargs):
        nonlocal saves
        saves += 1
        return await original(*args, **kwargs)

    history.save_game = counting_save  # type: ignore[method-assign]
    dying_prompts.raise_with = None
    clock.advance(RETRY_BACKOFF_SECONDS[0])
    assert (await worker.replay_one()).outcome is ReplayOutcome.RECORDED
    assert saves == 0, "the history half is not written twice"
    assert len(dying_prompts.batches) == 1
    assert await rows(session_factory) == []


async def test_a_commit_whose_outcome_was_never_learned_is_simply_tried_again(env):
    """The write landed, the acknowledgement did not (a timeout on the way
    back). The retry meets its own content under the same id: idempotent
    (R-HIST-02), one row, and the envelope is done."""
    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    game_id = str(generate_uuid())
    clock = Clock()
    worker = worker_for(store, history, clock=clock)
    await worker.stage(FinishedGameEnvelope(history_for(game_id, ann, bob)))

    original = history.save_game
    lost_acks = {"left": 1}

    async def committed_but_unacknowledged(*args, **kwargs):
        result = await original(*args, **kwargs)
        if lost_acks["left"]:
            lost_acks["left"] -= 1
            raise TimeoutError("acknowledgement lost")
        return result

    history.save_game = committed_but_unacknowledged  # type: ignore[method-assign]
    assert (await worker.replay_one()).outcome is ReplayOutcome.RETRIED
    clock.advance(RETRY_BACKOFF_SECONDS[0])
    assert (await worker.replay_one()).outcome is ReplayOutcome.RECORDED
    async with session_factory() as session:
        assert len((await session.scalars(select(GameRecord))).all()) == 1
    assert await rows(session_factory) == []


async def test_transient_failures_back_off_on_the_schedule_and_then_give_up(env):
    from app.services.telemetry import telemetry

    retried_before = telemetry.db_retries.get(("save_game", "retried"))
    exhausted_before = telemetry.db_retries.get(("save_game", "exhausted"))
    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    game_id = str(generate_uuid())
    clock = Clock()
    outcomes: list[tuple[str, str]] = []
    worker = worker_for(store, history, clock=clock, on_outcome=lambda g, s: outcomes.append((g, s)))
    await worker.stage(FinishedGameEnvelope(history_for(game_id, ann, bob)))

    async def refusing(*args, **kwargs):
        raise RuntimeError("database unavailable")

    history.save_game = refusing  # type: ignore[method-assign]
    for attempt, wait in enumerate(RETRY_BACKOFF_SECONDS, start=1):
        assert (await worker.replay_one()).outcome is ReplayOutcome.RETRIED
        [row] = await rows(session_factory)
        assert (row.state, row.attempts) == ("pending", attempt)
        assert row.next_attempt_at == clock.now + timedelta(seconds=wait)
        assert await worker.replay_one() is None, "not due before its wait"
        clock.advance(wait)

    outcome, code, history_recorded = await worker.replay_one()
    assert (outcome, code, history_recorded) == (ReplayOutcome.FAILED, "exhausted", False)
    # Every retry and the final give-up are counted as such (#892).
    assert telemetry.db_retries.get(("save_game", "retried")) - retried_before == len(RETRY_BACKOFF_SECONDS)
    assert telemetry.db_retries.get(("save_game", "exhausted")) - exhausted_before == 1
    [row] = await rows(session_factory)
    assert (row.state, row.attempts, row.failure_code) == ("failed", MAX_ATTEMPTS, "exhausted")
    assert row.payload is None and row.failed_at == clock.now
    assert row.last_error and "database unavailable" in row.last_error
    assert outcomes == [(game_id, "failed")]
    assert await worker.replay_one() is None, "a failed row is never claimed again"


async def test_a_conflict_with_what_history_already_holds_fails_on_first_sight(env):
    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    game_id = str(generate_uuid())
    worker = worker_for(store, history)
    await worker.stage(FinishedGameEnvelope(history_for(game_id, ann, bob, drawing=_frame(0))))
    # Meanwhile the same id was written with other content.
    other = history_for(game_id, ann, bob, drawing=_frame(1))
    await history.save_game(other.record, other.participants, other.turns, other.score_events, other.drawings, other.reactions)

    outcome, code, history_recorded = await worker.replay_one()

    assert (outcome, code, history_recorded) == (ReplayOutcome.FAILED, "conflict", False)
    [row] = await rows(session_factory)
    assert (row.state, row.attempts, row.payload) == ("failed", 1, None)


async def test_a_usage_conflict_fails_the_envelope_but_leaves_the_history_written(env):
    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    game_id = str(generate_uuid())
    prompts = RecordingPrompts(raise_with=PromptUsageConflictError("different facts"))
    outcomes: list[tuple[str, str]] = []
    worker = worker_for(store, history, prompts, on_outcome=lambda g, s: outcomes.append((g, s)))
    await worker.stage(FinishedGameEnvelope(history_for(game_id, ann, bob), usage_for(game_id), ("rev-1",)))

    outcome, code, history_recorded = await worker.replay_one()

    assert (outcome, code, history_recorded) == (ReplayOutcome.FAILED, "conflict", True)
    # The room is told the game is recorded - it is - not that it failed.
    assert outcomes == [(game_id, "recorded")]
    [row] = await rows(session_factory)
    assert (row.history_state, row.usage_state) == ("done", "pending")
    assert [g.id for g in await history.get_user_games(ann, requesting_user_id=ann)] == [game_id]


async def test_bytes_that_fail_their_checksum_or_their_version_are_given_up_on(env):
    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    worker = worker_for(store, history)
    corrupt, ancient = str(generate_uuid()), str(generate_uuid())
    await worker.stage(FinishedGameEnvelope(history_for(corrupt, ann, bob)))
    await worker.stage(FinishedGameEnvelope(history_for(ancient, ann, bob)))
    async with session_factory() as session:
        async with session.begin():
            await session.execute(update(EnvelopeRow).where(EnvelopeRow.game_id == handoff_module._entity(corrupt)).values(payload=b"garbage"))
            await session.execute(update(EnvelopeRow).where(EnvelopeRow.game_id == handoff_module._entity(ancient)).values(envelope_version=99))

    report = await worker.drain()

    assert (report.failed, report.recorded) == (2, 0)
    assert {row.failure_code for row in await rows(session_factory)} == {"unreadable"}
    assert all(row.payload is None for row in await rows(session_factory))


# --- claims --------------------------------------------------------------------


async def test_a_claim_is_a_lease_and_a_stale_one_is_taken_over_with_a_new_token(env):
    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    worker = worker_for(store, history)
    await worker.stage(FinishedGameEnvelope(history_for(str(generate_uuid()), ann, bob)))

    first = await store.claim_next(now=NOW, stale_after=STALE_CLAIM_AFTER)
    assert first is not None and first.attempts == 1
    assert await store.claim_next(now=NOW + timedelta(minutes=1), stale_after=STALE_CLAIM_AFTER) is None, "held"

    later = NOW + STALE_CLAIM_AFTER + timedelta(seconds=1)
    second = await store.claim_next(now=later, stale_after=STALE_CLAIM_AFTER)
    assert second is not None and second.token != first.token and second.attempts == 2

    # The first holder, back from the dead, is fenced out of every write.
    assert await store.mark_part(first, "history", "done") is False
    assert await store.release(first, next_attempt_at=later) is False
    assert await store.fail(first, code="exhausted", error="x", now=later) is False
    assert await store.complete(first) is False
    [row] = await rows(session_factory)
    assert (row.state, row.history_state) == ("processing", "pending")
    assert await store.complete(second) is True
    assert await rows(session_factory) == []


async def test_a_replay_interrupted_by_shutdown_hands_its_row_back_at_once(env):
    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    clock = Clock()
    worker = worker_for(store, history, clock=clock)
    await worker.stage(FinishedGameEnvelope(history_for(str(generate_uuid()), ann, bob)))
    started = asyncio.Event()

    async def hanging(*args, **kwargs):
        started.set()
        await asyncio.sleep(3600)

    history.save_game = hanging  # type: ignore[method-assign]
    task = asyncio.create_task(worker.replay_one())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    [row] = await rows(session_factory)
    assert (row.state, row.claim_token, row.next_attempt_at) == ("pending", None, clock.now)


async def test_a_replay_that_hangs_is_bounded_and_retried(env, monkeypatch):
    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    worker = worker_for(store, history)
    await worker.stage(FinishedGameEnvelope(history_for(str(generate_uuid()), ann, bob)))

    async def hanging(*args, **kwargs):
        await asyncio.sleep(3600)

    history.save_game = hanging  # type: ignore[method-assign]
    monkeypatch.setattr(handoff_module, "REPLAY_TIMEOUT_SECONDS", 0.05)
    assert (await worker.replay_one()).outcome is ReplayOutcome.RETRIED


# --- housekeeping ----------------------------------------------------------------


async def test_failed_rows_are_kept_thirty_days_then_purged_and_counted_meanwhile(env):
    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    clock = Clock()
    worker = worker_for(store, history, clock=clock)
    old, recent, waiting = (str(generate_uuid()) for _ in range(3))
    for game_id in (old, recent):
        await worker.stage(FinishedGameEnvelope(history_for(game_id, ann, bob)))
        claim = await store.claim_next(now=clock.now, stale_after=STALE_CLAIM_AFTER)
        await store.fail(claim, code="conflict", error="x", now=clock.now)
        clock.advance(20 * 86400)
    await worker.stage(FinishedGameEnvelope(history_for(waiting, ann, bob)))

    depth = await store.depth(now=clock.now)
    assert (depth.pending, depth.failed) == (1, 2)
    assert depth.oldest == clock.now

    purged = await worker.purge_failed(budget=SweepBudget())
    assert purged == 1
    assert {str(row.game_id) for row in await rows(session_factory)} == {recent, waiting}


# --- the repositories' side of the contract -------------------------------------


async def test_a_retry_with_different_drawing_bytes_is_a_conflict_not_a_silent_accept(env):
    """`save_game` hashed everything but the drawings (#541)."""
    _, users, history, _ = env
    ann, bob = await two_players(users)
    game_id = str(generate_uuid())
    first = history_for(game_id, ann, bob, drawing=_frame(0))
    await history.save_game(first.record, first.participants, first.turns, first.score_events, first.drawings, first.reactions)
    await history.save_game(first.record, first.participants, first.turns, first.score_events, first.drawings, first.reactions)

    second = GameHistoryWrite(first.record, first.participants, first.turns, first.score_events, [TurnDrawingInput(turn_id=first.turns[0].id, payload=_frame(1))], [])
    with pytest.raises(GameHistoryConflictError):
        await history.save_game(second.record, second.participants, second.turns, second.score_events, second.drawings, second.reactions)


async def test_a_usage_batch_is_a_fact_of_its_own(env):
    """Identical retry: one batch. Different facts under the same id: a
    conflict. A game that offered nothing from its lists: a batch of zero
    facts, which is not the same as a batch never written."""
    session_factory, *_ = env
    prompts = SqlAlchemyPromptListRepository(session_factory)
    await prompts.upsert_bundled(
        slug="standard", name="Standard", description="Words", language="en",
        prompts=[BundledPromptDefinition(str(generate_uuid()), "apple")], version=1,
    )
    selection = await prompts.resolve_selection(["standard"])
    apple = selection.prompt_version_ids["apple"]
    batch_id = str(generate_uuid())
    usage = PromptUsage(offers={apple: 1}, picks={apple: PromptPickTotals(1, 1, 2)}, batch_id=batch_id)

    await prompts.record_prompt_usage(selection.revision_ids, usage)
    await prompts.record_prompt_usage(selection.revision_ids, usage)
    with pytest.raises(PromptUsageConflictError):
        await prompts.record_prompt_usage(
            selection.revision_ids,
            PromptUsage(offers={apple: 2}, picks={}, batch_id=batch_id, occurred_at=usage.occurred_at),
        )

    empty_id = str(generate_uuid())
    await prompts.record_prompt_usage(
        selection.revision_ids, PromptUsage(offers={str(generate_uuid()): 1}, picks={}, batch_id=empty_id)
    )
    async with session_factory() as session:
        batches = {str(b.batch_id): b.fact_count for b in (await session.scalars(select(PromptUsageBatch))).all()}
        facts = (await session.scalars(select(PromptUsageFact))).all()
    assert batches == {batch_id: 1, empty_id: 0}
    assert len(facts) == 1


async def test_no_drawing_is_encoded_on_the_event_loop_at_game_end(env, monkeypatch):
    """The envelope's deflate, its decode, and each drawing's storage encoding
    run on worker threads (#976): on the loop they were ~27 ms for an ordinary
    game and ~325 ms for a stroke-heavy one, every room waiting - part of it
    inside the transaction holding each player's `users` row. What is stored
    is unchanged, byte for byte."""
    import threading

    import app.repositories.sqlalchemy as repository_module
    from app.canvas_storage import prepare_stored_drawing

    on_loop: list[str] = []

    ran_on: dict[str, set[str]] = {}

    def watched(name, function):
        def call(*args, **kwargs):
            thread = threading.current_thread()
            if thread is threading.main_thread():
                on_loop.append(name)
            ran_on.setdefault(name, set()).add(thread.name)
            return function(*args, **kwargs)
        return call

    monkeypatch.setattr(handoff_module, "encode_envelope", watched("encode", handoff_module.encode_envelope))
    monkeypatch.setattr(handoff_module, "decode_envelope", watched("decode", handoff_module.decode_envelope))
    monkeypatch.setattr(handoff_module, "envelope_checksum", watched("checksum", handoff_module.envelope_checksum))
    monkeypatch.setattr(repository_module, "prepare_stored_drawing", watched("prepare", prepare_stored_drawing))
    monkeypatch.setattr(
        repository_module.SqlAlchemyGameHistoryRepository,
        "_payload_hash",
        staticmethod(watched("digest", repository_module.SqlAlchemyGameHistoryRepository._payload_hash)),
    )
    session_factory, users, history, store = env
    # In order, every statement and every drawing prepared: the drawings must
    # all be ready before the write transaction's first statement, never
    # inside the transaction that locks the players' rows.
    from sqlalchemy import event

    order: list[str] = []
    event.listen(
        session_factory.kw["bind"].sync_engine,
        "before_cursor_execute",
        lambda _c, _cur, statement, *_a: order.append(statement),
    )
    real_prepare = repository_module.prepare_stored_drawing
    monkeypatch.setattr(
        repository_module,
        "prepare_stored_drawing",
        watched("prepare", lambda payload: (order.append("<prepare>"), real_prepare(payload))[1]),
    )
    ann, bob = await two_players(users)
    worker = worker_for(store, history)
    frame = _path_heavy_frame()
    await worker.stage(FinishedGameEnvelope(history_for(str(generate_uuid()), ann, bob, drawing=frame)))
    report = await worker.drain()

    assert report.recorded == 1
    assert on_loop == []
    # On the history write's own pools, not the default one `asyncio.to_thread`
    # shares with blocking SMTP: a staging that waits there for a thread can
    # spend its ten-second bound and lose the game (#976 review).
    assert all(name.startswith("history-envelope") for name in ran_on["encode"]), ran_on
    assert all(name.startswith("history-envelope") for name in ran_on["decode"]), ran_on
    assert all(name.startswith("history-encode") for name in ran_on["prepare"]), ran_on
    assert all(name.startswith("history-encode") for name in ran_on["digest"]), ran_on
    write_opens = next(
        index for index, statement in enumerate(order) if statement.startswith("SELECT game_records.id AS")
    )
    assert "<prepare>" in order and order.index("<prepare>") < write_opens
    expected_blob, magic, version, checksum = prepare_stored_drawing(frame)
    async with session_factory() as session:
        [drawing] = (await session.scalars(select(TurnDrawing))).all()
    assert magic == b"SKCD", "the delta encoding, not a frame stored as it travels"
    assert (drawing.payload, drawing.format_magic, drawing.format_version, drawing.checksum_sha256) == (
        expected_blob, magic.decode("ascii"), version, checksum,
    )


def _path_heavy_frame() -> bytes:
    """A frame big enough that the stored form is the delta encoding."""
    import math

    from app.canvas_history import PackedCanvasHistory

    history = PackedCanvasHistory()
    for stroke in range(20):
        history.append_path(
            [(0.5 + 0.4 * math.cos(step / 30 + stroke), 0.5 + 0.4 * math.sin(step / 25)) for step in range(200)],
            color=0x112233,
            width=4,
        )
    return history.binary_payload()


async def test_an_erased_drawers_unreadable_drawing_is_a_tombstone_and_anyone_elses_fails(env):
    """Preparing moved before the transaction, where the erased set is not yet
    known; a drawing that cannot be prepared still fails the write only if it
    is going to be written (#976 review)."""
    from uuid import UUID

    from app.db.models import User
    from app.domain_values import AccountState

    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    async with session_factory() as session:
        async with session.begin():
            (await session.get(User, UUID(ann))).state = AccountState.DELETED.value
    erased_game = history_for(str(generate_uuid()), ann, bob, drawing=b"not a frame")
    await history.save_game(
        erased_game.record, erased_game.participants, erased_game.turns,
        erased_game.score_events, erased_game.drawings, erased_game.reactions,
    )
    async with session_factory() as session:
        [row] = (await session.scalars(select(TurnDrawing))).all()
    assert row.status != "ready" and row.payload is None

    carol = (await users.create_anonymous(display_name="Carol")).id
    live_game = history_for(str(generate_uuid()), carol, bob, drawing=b"not a frame")
    with pytest.raises(ValueError):
        await history.save_game(
            live_game.record, live_game.participants, live_game.turns,
            live_game.score_events, live_game.drawings, live_game.reactions,
        )


async def test_a_replay_of_a_written_game_encodes_nothing(env, monkeypatch):
    """Answered by one read before any drawing is prepared (#976 review)."""
    import app.repositories.sqlalchemy as repository_module

    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    game = history_for(str(generate_uuid()), ann, bob, drawing=_frame(2))
    arguments = (game.record, game.participants, game.turns, game.score_events, game.drawings, game.reactions)
    first = await history.save_game(*arguments)
    prepared: list[int] = []
    real = repository_module.prepare_stored_drawing
    monkeypatch.setattr(repository_module, "prepare_stored_drawing", lambda payload: (prepared.append(1), real(payload))[1])
    assert await history.save_game(*arguments) == first
    assert prepared == []


def test_a_drawing_row_cannot_be_built_without_its_prepared_bytes():
    """`prepared` is required, so no caller can quietly put the encode back on
    the thread it is called from (#976 review)."""
    import inspect

    from app.repositories.sqlalchemy import _turn_drawing

    prepared = inspect.signature(_turn_drawing).parameters["prepared"]
    assert prepared.default is inspect.Parameter.empty
    assert inspect.signature(_turn_drawing).parameters["sizing"].default is inspect.Parameter.empty


def test_both_encode_pools_are_as_wide_as_the_setting(monkeypatch):
    """The setting is only worth having if it reaches both pools: replacing
    each `max_workers` with a literal passed every test (#976 third review)."""
    import app.repositories.sqlalchemy as repository_module
    import app.services.game_handoff as handoff

    monkeypatch.setenv("HISTORY_ENCODE_WORKERS", "3")
    monkeypatch.setattr(repository_module, "_ENCODE_POOL", None)
    monkeypatch.setattr(handoff, "_ENVELOPE_POOL", None)
    try:
        assert repository_module._encode_pool()._max_workers == 3
        assert handoff._envelope_pool()._max_workers == 3
        assert repository_module._encode_pool()._thread_name_prefix == "history-encode"
        assert handoff._envelope_pool()._thread_name_prefix == "history-envelope"
    finally:
        for module, name in ((repository_module, "_ENCODE_POOL"), (handoff, "_ENVELOPE_POOL")):
            pool = getattr(module, name)
            if pool is not None:
                pool.shutdown(wait=False)
            setattr(module, name, None)


async def test_the_encode_is_not_inside_the_write_bound(monkeypatch):
    """A room's ten-second bound is for the write. A burst of endings queueing
    on the envelope pool must cost latency, not games, so an encode that takes
    longer than the bound still ends with the game staged (#976 third review)."""
    from types import SimpleNamespace

    import app.services.game_flow as flow_module

    monkeypatch.setattr(flow_module, "HISTORY_WRITE_TIMEOUT_SECONDS", 0.05)

    class SlowEncode:
        def __init__(self) -> None:
            self.written: list[str] = []

        async def encode(self, envelope):
            await asyncio.sleep(0.2)
            return envelope

        async def stage_encoded(self, staged):
            self.written.append(staged.game_id)
            return StageOutcome.STAGED

    worker = SlowEncode()
    flow = object.__new__(flow_module.GameFlowService)
    flow._ctx = SimpleNamespace(finished_games=worker)
    outcomes: list[tuple[str, str]] = []
    flow.note_history_outcome = lambda game_id, state, room=None: outcomes.append(
        (game_id, state)
    )
    flow._note_abandoned_write = lambda room, kind, reason, started: outcomes.append(
        (kind, reason)
    )

    await flow._hand_off_finished_game(
        SimpleNamespace(id="room"), SimpleNamespace(game_id="game")
    )

    assert worker.written == ["game"], "the slow encode cost latency, not the game"
    assert outcomes == []


async def test_the_shutdown_drain_cancels_and_counts_what_it_cannot_wait_for(caplog):
    """A deferred staging left running when the budget is spent used to be
    neither awaited nor cancelled: the loop closed under it, the game was lost
    with no counter, and the room kept saying "pending" (#976 fourth review).
    """
    import logging

    from app.handlers.context import HandlerContext

    ctx = object.__new__(HandlerContext)
    ctx.room_cleanups = set()
    started = asyncio.Event()

    async def never_finishes():
        started.set()
        await asyncio.sleep(3600)

    ctx.defer_cleanup(never_finishes())
    await asyncio.wait_for(started.wait(), timeout=2)
    [task] = list(ctx.room_cleanups)

    with caplog.at_level(logging.WARNING):
        await asyncio.wait_for(ctx.drain_room_cleanups(0.05), timeout=5)

    assert task.cancelled(), "the drain does not leave it to the loop closing"
    assert "Cancelled 1 deferred room cleanup" in caplog.text


async def test_a_staging_cancelled_by_the_drain_is_counted_as_a_lost_write(monkeypatch):
    """Counted like every other lost write before it goes, rather than
    disappearing with the process (#976 fourth review)."""
    from types import SimpleNamespace

    import app.services.game_flow as flow_module

    class Stuck:
        async def encode(self, envelope):
            await asyncio.sleep(3600)

        async def stage_encoded(self, staged):  # pragma: no cover - never reached
            raise AssertionError("the encode never finished")

    flow = object.__new__(flow_module.GameFlowService)
    flow._ctx = SimpleNamespace(finished_games=Stuck())
    abandoned: list[tuple[str, str]] = []
    outcomes: list[tuple[str, str]] = []
    flow._note_abandoned_write = lambda room, kind, reason, start: abandoned.append((kind, reason))
    flow.note_history_outcome = lambda game_id, state, room=None: outcomes.append((game_id, state))

    handoff = asyncio.create_task(
        flow._hand_off_finished_game(
            SimpleNamespace(id="room"), SimpleNamespace(game_id="game")
        )
    )
    await asyncio.sleep(0.02)
    handoff.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await handoff

    assert abandoned == [("handoff", "cancelled")]
    assert outcomes == [("game", "failed")]
    # And it is still cancelled: swallowing the cancellation would report a
    # task that never finished as one that did (#976 fifth review).
    assert handoff.cancelled()


async def test_staging_wakes_the_loop_rather_than_waiting_for_its_sweep(env):
    """Without the wake a staged game sits until the sweep comes round - up to
    a minute of a room saying "pending" for a write that is ready (#976 fourth
    review)."""
    session_factory, users, history, store = env
    ann, bob = await two_players(users)
    worker = worker_for(store, history)
    woken: list[int] = []
    worker.wake = lambda: woken.append(1)

    envelope = FinishedGameEnvelope(history_for(str(generate_uuid()), ann, bob))
    assert await worker.stage_encoded(await worker.encode(envelope)) is StageOutcome.STAGED

    assert woken == [1]


async def test_the_lifespan_refuses_a_width_the_process_cannot_use(monkeypatch):
    """Validated in the lifespan, so a typo is heard at startup rather than at
    the first finished game - and driven through the lifespan itself, because
    making that call unreachable passed every test (#976 fourth review)."""
    import app.main as main_module

    monkeypatch.setenv("HISTORY_ENCODE_WORKERS", "nonsense")
    with pytest.raises(ValueError, match="HISTORY_ENCODE_WORKERS"):
        async with main_module.lifespan(None):
            raise AssertionError("the process started with a width it cannot use")


async def test_the_drain_waits_for_a_cleanup_another_cleanup_created(caplog):
    """A room teardown ends its game, and ending a game defers the staging: a
    drain that snapshots once gives the teardown its first step and then
    returns while the staging it just created runs on - neither awaited,
    cancelled nor counted (#976 fifth review)."""
    import logging

    from app.handlers.context import HandlerContext

    ctx = object.__new__(HandlerContext)
    ctx.room_cleanups = set()
    staged = asyncio.Event()

    async def staging():
        await asyncio.sleep(0.05)
        staged.set()

    async def teardown():
        await asyncio.sleep(0)
        ctx.defer_cleanup(staging())

    ctx.defer_cleanup(teardown())
    with caplog.at_level(logging.WARNING):
        await asyncio.wait_for(ctx.drain_room_cleanups(5), timeout=5)

    assert staged.is_set(), "the drain returned while the staging was still running"
    assert ctx.room_cleanups == set()
    assert "Cancelled" not in caplog.text


def test_the_shutdown_budget_covers_the_encodes_the_process_can_hold(monkeypatch):
    """The allowance is the whole fix for the shutdown finding, and a fixed
    ten seconds was pinned by nothing: setting it to 0 restored the pre-fix
    budget with 593 tests passing. It is computed now, from every room this
    process will hold ending at once at the configured width (#976 fifth
    review)."""
    from app.services.game_flow import (
        ENVELOPE_ENCODE_SECONDS,
        history_encode_drain_seconds,
    )

    monkeypatch.setenv("ROOM_GLOBAL_LIMIT", "200")
    monkeypatch.setenv("HISTORY_ENCODE_WORKERS", "2")
    assert history_encode_drain_seconds() >= 200 * ENVELOPE_ENCODE_SECONDS / 2

    # A host that gives the encode one thread waits twice as long for it.
    monkeypatch.setenv("HISTORY_ENCODE_WORKERS", "1")
    assert history_encode_drain_seconds() >= 200 * ENVELOPE_ENCODE_SECONDS

    # And a smaller ceiling costs a shorter shutdown.
    monkeypatch.setenv("ROOM_GLOBAL_LIMIT", "20")
    assert history_encode_drain_seconds() < 200 * ENVELOPE_ENCODE_SECONDS


def test_the_shutdown_hands_the_drain_that_budget():
    """The allowance is only worth computing if the process uses it: the drain
    tests pass their own budget, so nothing exercised the one the shutdown
    hands over (#976 fifth review)."""

    from app.services.game_flow import (
        ENVELOPE_ENCODE_SECONDS,
        HISTORY_WRITE_TIMEOUT_SECONDS,
        history_encode_drain_seconds,
        shutdown_cleanup_budget_seconds,
    )

    budget = shutdown_cleanup_budget_seconds()
    assert budget == history_encode_drain_seconds() + HISTORY_WRITE_TIMEOUT_SECONDS
    assert budget > HISTORY_WRITE_TIMEOUT_SECONDS, "the write bound alone is the old budget"
    # The measurement the budget is computed from: one stroke-heavy envelope
    # on the machine #976 measured. Shrinking it shrinks the budget with every
    # test still green (#976 sixth review).
    assert ENVELOPE_ENCODE_SECONDS == 0.15


def test_each_encode_pool_is_built_once():
    """Lazily, not per call: a fresh executor on every finished game would be
    two new pools of N threads per game, which passed every test (#976 fifth
    review)."""
    import app.repositories.sqlalchemy as repository_module
    import app.services.game_handoff as handoff

    try:
        assert repository_module._encode_pool() is repository_module._encode_pool()
        assert handoff._envelope_pool() is handoff._envelope_pool()
    finally:
        for module, name in ((repository_module, "_ENCODE_POOL"), (handoff, "_ENVELOPE_POOL")):
            pool = getattr(module, name)
            if pool is not None:
                pool.shutdown(wait=False)
            setattr(module, name, None)


def test_the_cleanups_are_drained_before_the_handoff_worker_stops():
    """The drain ends rooms and stages their games; the bounded replay pass
    below it is what writes them. In the other order every game the drain
    stages misses that pass and waits for the next process (#976 fifth
    review). Compared on the calls, because the prose around them mentions
    both (#976 sixth review)."""
    import inspect

    import app.main as main_module

    source = inspect.getsource(main_module.lifespan)
    drain = source.index("await handler_context.drain_room_cleanups(")
    assert drain < source.index("await stop_handoff_worker(")
    # And the runtime events both of them record - a staging the drain
    # cancelled, a replay the pass below abandoned - are written before the
    # engine goes away. `stop_metrics_loop(None, ...)` returned on its first
    # line, so the flush has to be the call itself (#976 seventh review).
    flush = source.index("await flush_events(async_session_factory)")
    assert flush > source.index("finished_game_worker.drain()")
    assert flush < source.index("await async_engine.dispose()")


async def test_a_cleanup_deferred_at_the_deadline_is_cancelled_and_counted(caplog):
    """The re-read fixed the waiting half; the cancelling half still worked
    from a snapshot, so a staging deferred by a teardown that was itself about
    to be cancelled escaped the shutdown entirely (#976 sixth review).

    And it is *counted*: a coroutine cancelled before it has run a line never
    enters its own `try`, so the game was lost with no record - which is the
    half R-HIST-03 promises (#976 seventh review).
    """
    import logging

    from app.handlers.context import HandlerContext

    ctx = object.__new__(HandlerContext)
    ctx.room_cleanups = set()
    steps: list[str] = []

    async def staging():
        try:
            steps.append("started")
            await asyncio.sleep(0.5)
            steps.append("escaped")
        except asyncio.CancelledError:
            steps.append("counted the loss")
            raise

    async def teardown():
        await asyncio.sleep(0)
        ctx.defer_cleanup(staging())
        await asyncio.sleep(5)  # still running when the budget is spent

    ctx.defer_cleanup(teardown())
    with caplog.at_level(logging.WARNING):
        await asyncio.wait_for(ctx.drain_room_cleanups(0.1), timeout=5)

    assert ctx.room_cleanups == set(), "nothing is left running"
    assert steps == ["started", "counted the loss"], steps
    assert "Cancelled 2 deferred room cleanup" in caplog.text


async def test_a_cleanup_cancelled_before_its_first_step_still_counts_its_loss():
    """A coroutine cancelled before it has run a line never enters its own
    `try`, so the game it was going to stage is lost *and* uncounted - the
    half R-HIST-03 promises. With a spent budget the drain reaches the cancel
    phase without ever yielding, which is exactly that case (#976 seventh
    review)."""
    from app.handlers.context import HandlerContext

    ctx = object.__new__(HandlerContext)
    ctx.room_cleanups = set()
    steps: list[str] = []

    async def staging():
        try:
            steps.append("started")
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            steps.append("counted the loss")
            raise

    ctx.defer_cleanup(staging())  # created, not yet stepped
    await asyncio.wait_for(ctx.drain_room_cleanups(0), timeout=5)

    assert steps == ["started", "counted the loss"], steps
    assert ctx.room_cleanups == set()


async def test_a_cleanup_deferred_from_inside_a_cancellation_is_cancelled_too(caplog):
    """The cancel phase loops for the same reason the wait phase does: a
    teardown can defer its successor on its way out, and a single round would
    leave that one running. Collapsing the loop to one snapshot passed (#976
    seventh review)."""
    import logging

    from app.handlers.context import HandlerContext

    ctx = object.__new__(HandlerContext)
    ctx.room_cleanups = set()
    escaped = asyncio.Event()

    async def successor():
        await asyncio.sleep(0.5)
        escaped.set()

    async def teardown():
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            ctx.defer_cleanup(successor())
            raise

    ctx.defer_cleanup(teardown())
    await asyncio.sleep(0)
    with caplog.at_level(logging.WARNING):
        await asyncio.wait_for(ctx.drain_room_cleanups(0.05), timeout=5)

    assert ctx.room_cleanups == set()
    assert not escaped.is_set(), "the successor was cancelled too"
    assert "Cancelled 2 deferred room cleanup" in caplog.text


async def test_the_cancel_phase_gives_up_rather_than_holding_the_shutdown(caplog):
    """A cleanup that swallows its cancellation cannot be made to stop, and a
    shutdown that waits for one for ever is a shutdown that does not happen.
    It is left behind, and said so (#976 seventh review)."""
    import logging

    from app.handlers import context as context_module
    from app.handlers.context import HandlerContext

    ctx = object.__new__(HandlerContext)
    ctx.room_cleanups = set()
    # The test keeps a way to end it: a task that truly cannot be stopped
    # would wedge this run rather than fail it, which is the trap this suite
    # has met twice.
    relent = asyncio.Event()

    async def stubborn():
        while True:
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                if relent.is_set():
                    raise

    ctx.defer_cleanup(stubborn())
    await asyncio.sleep(0)
    real_bound = context_module.CLEANUP_CANCEL_SECONDS
    context_module.CLEANUP_CANCEL_SECONDS = 0.1
    try:
        with caplog.at_level(logging.WARNING):
            await asyncio.wait_for(ctx.drain_room_cleanups(0.05), timeout=5)
    finally:
        # Whatever happened above, this task is made to end: one that cannot
        # be stopped would wedge the whole run rather than fail this test,
        # which is the trap this suite has met twice.
        context_module.CLEANUP_CANCEL_SECONDS = real_bound
        relent.set()
        for task in list(ctx.room_cleanups):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    assert "1 left" in caplog.text
    # And the bound it gave up after is the shipped one: raising it to a day
    # passed every test (#976 seventh review).
    assert real_bound == 5
