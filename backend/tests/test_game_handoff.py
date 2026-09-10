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
