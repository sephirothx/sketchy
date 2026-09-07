"""Durable handoff of a finished game into history (#541).

A finished game used to go straight into six history tables in one
transaction - three attempts, ten seconds, and then it was forgotten, with
#482 making the loss countable. The bytes of a game live only in the process
that played it, so every failure inside that window was final: a lock held a
moment too long, a database restart, a process dying with the write in the
air.

Now the whole game is written down first, as one envelope row, and unpacked
into history afterwards by a supervised loop:

1. `game_flow` builds the history and the prompt-usage facts as before, and
   hands them to `FinishedGameHandoffWorker.stage`: one small INSERT of a
   versioned, bounded, checksummed blob. That insert is the only write the
   room waits on, and it is bounded like the old one was. If *it* fails - the
   database is down at the moment the game ends - the game is lost, and that
   is recorded exactly as before (`history.write_abandoned`, kind `handoff`).
   The issue is explicit that an outbox in the same unavailable database is
   not an outage guarantee; what it guarantees is everything after the insert.
2. The loop claims one due row at a time with a lease and a fencing token,
   decodes it, and writes the two parts - history through `save_game`, usage
   through `record_prompt_usage` - recording each as done under the one row,
   so a crash between them resumes the missing one rather than both. Both
   writes are idempotent by content (R-HIST-02, now including drawings and
   usage), so a write whose commit outcome was never learned is simply tried
   again. When both parts are done the row is deleted: history is the record.
3. A transient failure releases the claim with backoff, up to about two hours
   in total; a conflict - the database already holds this game or this batch
   with different content - fails on the first sight of it, as does an
   envelope this build cannot read. A terminal failure keeps the row without
   its payload, so an operator can see what was lost and why, and nothing an
   erased account authored (#606) sits here longer than the retry window. The
   replay itself goes through the same erasure barrier as every writer
   (R-PRIV-15), so content erased while an envelope waited is tombstoned on
   the way in, never restored.

The loop is one of the supervised in-process loops (N-12): the table is the
queue, the request wakes it, the interval sweep is the retry and the reclaim.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import os
import time
import zlib
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import FinishedGameEnvelope as EnvelopeRow
from app.db.models import generate_uuid
from app.domain_values import (
    FinishedGameHandoffState,
    HandoffFailureCode,
    HandoffPartState,
    RuntimeEventType,
)
from app.repositories.interfaces import (
    GameHistoryConflictError,
    GameHistoryRepository,
    GameParticipantInput,
    GameRecordInput,
    PromptListRepository,
    PromptOfferInput,
    PromptPickTotals,
    PromptUsage,
    PromptUsageConflictError,
    ScoreEventInput,
    TurnDrawingInput,
    TurnDrawingReactionInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.services.game_history import GameHistoryWrite
from app.services.readiness import LoopHealth
from app.services.runtime_metrics import metrics
from app.services.sweeps import SweepBudget, delete_in_batches
from app.services.telemetry import telemetry

logger = logging.getLogger("sketchy.services.game_handoff")

ENVELOPE_VERSION = 1

# The one write a room waits on after a game ends: the staging insert. Ten
# seconds, the same bound the direct write had, and the same one the entry
# path uses for its own database wait (`tests/test_entry_timeouts.py`).
WRITE_TIMEOUT_SECONDS = 10

# How long one replay attempt may take. Longer than the staging bound: this
# is off the room's path, and a big game's drawings are several megabytes.
REPLAY_TIMEOUT_SECONDS = 60

# Waits between attempts. Attempt n failing transiently schedules the next
# one this many seconds later; past the last entry the envelope is failed as
# exhausted. About two hours in total: long enough to ride out a database
# restart or failover, short enough that an erased account's staged content
# is bounded (#606).
RETRY_BACKOFF_SECONDS: tuple[float, ...] = (1, 5, 30, 120, 600, 1800, 3600)
MAX_ATTEMPTS = len(RETRY_BACKOFF_SECONDS) + 1

# A claim older than this belongs to a process that died mid-replay; the
# next sweep takes it. Same window as the export worker's.
STALE_CLAIM_AFTER = timedelta(minutes=15)

# How long a failed row - game id, reason, attempts, no payload - is kept
# for the operations page before the purge removes it.
FAILED_RETENTION = timedelta(days=30)

# An envelope past this is refused at staging and the game recorded as lost.
# The recap budget bounds a game's drawings at 8 MiB; the rest of a game is
# kilobytes, and the blob is compressed, so this is never reached by a game
# the room could hold.
DEFAULT_MAX_ENVELOPE_BYTES = 16 * 1024 * 1024
DEFAULT_SWEEP_SECONDS = 60.0


def sweep_interval_seconds(environ: dict[str, str] | None = None) -> float:
    values = os.environ if environ is None else environ
    raw = values.get("HISTORY_HANDOFF_SWEEP_SECONDS", "").strip()
    try:
        seconds = float(raw) if raw else DEFAULT_SWEEP_SECONDS
    except ValueError:
        return DEFAULT_SWEEP_SECONDS
    return seconds if seconds > 0 else DEFAULT_SWEEP_SECONDS


def max_envelope_bytes(environ: dict[str, str] | None = None) -> int:
    values = os.environ if environ is None else environ
    raw = values.get("HISTORY_HANDOFF_MAX_BYTES", "").strip()
    try:
        limit = int(raw) if raw else DEFAULT_MAX_ENVELOPE_BYTES
    except ValueError:
        return DEFAULT_MAX_ENVELOPE_BYTES
    return limit if limit > 0 else DEFAULT_MAX_ENVELOPE_BYTES


# --- the envelope -----------------------------------------------------------


@dataclass(frozen=True)
class FinishedGameEnvelope:
    """Everything a finished game leaves behind, in one piece."""

    history: GameHistoryWrite
    # None when the game had no pinned prompt-list sources or offered nothing
    # from them: there is no usage to write, which is a fact, not a gap.
    usage: PromptUsage | None = None
    usage_revision_ids: tuple[str, ...] = ()

    @property
    def game_id(self) -> str:
        assert self.history.record.id is not None
        return self.history.record.id


class EnvelopeUnreadable(ValueError):
    """Bytes that do not decode to an envelope this build understands."""


class EnvelopeTooLarge(ValueError):
    def __init__(self, size: int, limit: int) -> None:
        super().__init__(f"envelope is {size} bytes, past the {limit} byte ceiling")
        self.size = size
        self.limit = limit


class EnvelopeConflictError(RuntimeError):
    """The same game id was staged twice with different content."""


def _iso(value: datetime) -> str:
    return value.isoformat()


def _when(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _bytes_out(value: bytes | None) -> str | None:
    return None if value is None else base64.b64encode(value).decode("ascii")


def _bytes_in(value: str | None) -> bytes | None:
    return None if value is None else base64.b64decode(value.encode("ascii"))


def _offer_out(offer: PromptOfferInput) -> dict:
    return {
        "position": offer.position,
        "prompt": offer.prompt,
        "selected": offer.selected,
        "source_kind": offer.source_kind,
        "prompt_version_id": offer.prompt_version_id,
        "source_revision_ids": list(offer.source_revision_ids),
    }


def _offer_in(value: dict) -> PromptOfferInput:
    return PromptOfferInput(
        position=value["position"],
        prompt=value["prompt"],
        selected=value["selected"],
        source_kind=value["source_kind"],
        prompt_version_id=value.get("prompt_version_id"),
        source_revision_ids=tuple(value.get("source_revision_ids", ())),
    )


def _outcome_out(outcome: TurnParticipantOutcomeInput) -> dict:
    return {
        "seat_id": outcome.seat_id,
        "user_id": outcome.user_id,
        "eligible": outcome.eligible,
        "eligibility_reason": outcome.eligibility_reason,
        "outcome": outcome.outcome,
        "terminal_state": outcome.terminal_state,
        "correct_guess_time_seconds": outcome.correct_guess_time_seconds,
        "wrong_guess_count": outcome.wrong_guess_count,
        "near_miss_count": outcome.near_miss_count,
        "hints_used": outcome.hints_used,
        "points_spent_on_hints": outcome.points_spent_on_hints,
        "points_awarded": outcome.points_awarded,
    }


def _outcome_in(value: dict) -> TurnParticipantOutcomeInput:
    return TurnParticipantOutcomeInput(**value)


def _turn_out(turn: TurnRecordInput) -> dict:
    return {
        "id": turn.id,
        "round_number": turn.round_number,
        "turn_number": turn.turn_number,
        "drawer_user_id": turn.drawer_user_id,
        "prompt": turn.prompt,
        "duration_seconds": turn.duration_seconds,
        "prompt_version_id": turn.prompt_version_id,
        "prompt_source_kind": turn.prompt_source_kind,
        "guesser_count": turn.guesser_count,
        "prompt_auto_picked": turn.prompt_auto_picked,
        "stroke_count": turn.stroke_count,
        "end_reason": turn.end_reason,
        "wrong_guess_count": turn.wrong_guess_count,
        "near_miss_count": turn.near_miss_count,
        "prompt_offers": [_offer_out(offer) for offer in turn.prompt_offers],
        "drawer_seat_id": turn.drawer_seat_id,
        "participant_outcomes": [
            _outcome_out(outcome) for outcome in turn.participant_outcomes
        ],
    }


def _turn_in(value: dict) -> TurnRecordInput:
    return TurnRecordInput(
        id=value["id"],
        round_number=value["round_number"],
        turn_number=value["turn_number"],
        drawer_user_id=value.get("drawer_user_id"),
        prompt=value["prompt"],
        duration_seconds=value["duration_seconds"],
        prompt_version_id=value.get("prompt_version_id"),
        prompt_source_kind=value["prompt_source_kind"],
        guesser_count=value["guesser_count"],
        prompt_auto_picked=value["prompt_auto_picked"],
        stroke_count=value["stroke_count"],
        end_reason=value["end_reason"],
        wrong_guess_count=value["wrong_guess_count"],
        near_miss_count=value["near_miss_count"],
        prompt_offers=tuple(_offer_in(offer) for offer in value.get("prompt_offers", ())),
        drawer_seat_id=value.get("drawer_seat_id"),
        participant_outcomes=tuple(
            _outcome_in(outcome) for outcome in value.get("participant_outcomes", ())
        ),
    )


def _record_out(record: GameRecordInput) -> dict:
    return {
        "id": record.id,
        "room_name": record.room_name,
        "scoring_mode": record.scoring_mode,
        "hint_mode": record.hint_mode,
        "drawing_seconds": record.drawing_seconds,
        "total_rounds": record.total_rounds,
        "player_count": record.player_count,
        "started_at": _iso(record.started_at),
        "finished_at": _iso(record.finished_at),
        "scoring_version": record.scoring_version,
        "score_ledger_version": record.score_ledger_version,
        "rule_snapshot_version": record.rule_snapshot_version,
        "rule_snapshot": record.rule_snapshot,
        "prompt_source_mode": record.prompt_source_mode,
        "prompt_source_revision_ids": list(record.prompt_source_revision_ids),
        "outcome": record.outcome,
        "visibility": record.visibility,
    }


def _record_in(value: dict) -> GameRecordInput:
    return GameRecordInput(
        id=value["id"],
        room_name=value["room_name"],
        scoring_mode=value["scoring_mode"],
        hint_mode=value["hint_mode"],
        drawing_seconds=value["drawing_seconds"],
        total_rounds=value["total_rounds"],
        player_count=value["player_count"],
        started_at=_when(value["started_at"]),
        finished_at=_when(value["finished_at"]),
        scoring_version=value["scoring_version"],
        score_ledger_version=value["score_ledger_version"],
        rule_snapshot_version=value["rule_snapshot_version"],
        rule_snapshot=value["rule_snapshot"],
        prompt_source_mode=value["prompt_source_mode"],
        prompt_source_revision_ids=tuple(value["prompt_source_revision_ids"]),
        outcome=value["outcome"],
        visibility=value["visibility"],
    )


def _participant_out(seat: GameParticipantInput) -> dict:
    return {
        "user_id": seat.user_id,
        "final_score": seat.final_score,
        "final_rank": seat.final_rank,
        "turns_played": seat.turns_played,
        "seat_id": seat.seat_id,
        "display_name": seat.display_name,
        "name_color": seat.name_color,
        "is_anonymous": seat.is_anonymous,
    }


def _score_event_out(event: ScoreEventInput) -> dict:
    return {
        "participant_seat_id": event.participant_seat_id,
        "participant_user_id": event.participant_user_id,
        "event_order": event.event_order,
        "event_type": event.event_type,
        "points_delta": event.points_delta,
        "turn_id": event.turn_id,
        "corrects_event_order": event.corrects_event_order,
    }


def _drawing_out(drawing: TurnDrawingInput) -> dict:
    return {
        "turn_id": drawing.turn_id,
        "payload": _bytes_out(drawing.payload),
        "unavailable_reason": drawing.unavailable_reason,
    }


def _drawing_in(value: dict) -> TurnDrawingInput:
    return TurnDrawingInput(
        turn_id=value["turn_id"],
        payload=_bytes_in(value.get("payload")),
        unavailable_reason=value.get("unavailable_reason"),
    )


def _reaction_out(reaction: TurnDrawingReactionInput) -> dict:
    return {
        "turn_id": reaction.turn_id,
        "seat_id": reaction.seat_id,
        "user_id": reaction.user_id,
        "emoji": reaction.emoji,
        "set_version": reaction.set_version,
    }


def _usage_out(usage: PromptUsage | None) -> dict | None:
    if usage is None:
        return None
    return {
        "batch_id": usage.batch_id,
        "occurred_at": _iso(usage.occurred_at),
        "scoring_mode": usage.scoring_mode,
        "hint_mode": usage.hint_mode,
        "offers": dict(usage.offers),
        "picks": {
            key: [totals.picks, totals.correct_guesses, totals.total_guessers]
            for key, totals in usage.picks.items()
        },
    }


def _usage_in(value: dict | None) -> PromptUsage | None:
    if value is None:
        return None
    return PromptUsage(
        offers=dict(value["offers"]),
        picks={
            key: PromptPickTotals(*totals) for key, totals in value["picks"].items()
        },
        batch_id=value["batch_id"],
        occurred_at=_when(value["occurred_at"]),
        scoring_mode=value["scoring_mode"],
        hint_mode=value["hint_mode"],
    )


def encode_envelope(envelope: FinishedGameEnvelope) -> bytes:
    """One deflated JSON document. Drawings ride as base64 and are the bulk."""
    history = envelope.history
    document = {
        "version": ENVELOPE_VERSION,
        "record": _record_out(history.record),
        "participants": [_participant_out(seat) for seat in history.participants],
        "turns": [_turn_out(turn) for turn in history.turns],
        "score_events": [_score_event_out(event) for event in history.score_events],
        "drawings": [_drawing_out(drawing) for drawing in history.drawings],
        "reactions": [_reaction_out(reaction) for reaction in history.reactions],
        "usage": _usage_out(envelope.usage),
        "usage_revision_ids": list(envelope.usage_revision_ids),
    }
    return zlib.compress(json.dumps(document, separators=(",", ":")).encode(), 6)


def decode_envelope(payload: bytes, version: int) -> FinishedGameEnvelope:
    """The inverse of `encode_envelope`; `EnvelopeUnreadable` for anything else."""
    if version != ENVELOPE_VERSION:
        raise EnvelopeUnreadable(f"envelope version {version} is not readable by this build")
    try:
        document = json.loads(zlib.decompress(payload).decode())
        history = GameHistoryWrite(
            record=_record_in(document["record"]),
            participants=[
                GameParticipantInput(**seat) for seat in document["participants"]
            ],
            turns=[_turn_in(turn) for turn in document["turns"]],
            score_events=[ScoreEventInput(**event) for event in document["score_events"]],
            drawings=[_drawing_in(drawing) for drawing in document["drawings"]],
            reactions=[
                TurnDrawingReactionInput(**reaction) for reaction in document["reactions"]
            ],
        )
        return FinishedGameEnvelope(
            history=history,
            usage=_usage_in(document.get("usage")),
            usage_revision_ids=tuple(document.get("usage_revision_ids", ())),
        )
    except (zlib.error, ValueError, KeyError, TypeError) as error:
        raise EnvelopeUnreadable(f"envelope could not be decoded: {error}") from error


def envelope_checksum(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# --- the store -----------------------------------------------------------------


class StageOutcome(StrEnum):
    STAGED = "staged"
    # Already there with the same content: a retry of the staging itself.
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class StagedEnvelope:
    """What goes into the queue: the bytes and enough to reason about them."""

    game_id: str
    version: int
    payload: bytes
    checksum: str
    # Decided at staging time rather than by the replay, so a row says on
    # its own whether usage is still owed.
    has_usage: bool


@dataclass(frozen=True)
class ClaimedEnvelope:
    """A row the loop holds a lease on. `token` fences every later write."""

    game_id: str
    token: str
    attempts: int
    version: int
    payload: bytes
    checksum: str
    history_state: str
    usage_state: str


@dataclass(frozen=True)
class QueueDepthReading:
    pending: int
    oldest: datetime | None
    failed: int


class EnvelopeStore(ABC):
    """The queue behind the handoff. The SQL store is the one that ships;
    the in-memory one under `tests/` lets the flow be exercised without a
    database, exactly as the handler tests always were."""

    @abstractmethod
    async def stage(self, staged: StagedEnvelope, *, now: datetime) -> StageOutcome: ...

    @abstractmethod
    async def claim_next(
        self, *, now: datetime, stale_after: timedelta
    ) -> ClaimedEnvelope | None: ...

    @abstractmethod
    async def mark_part(self, claim: ClaimedEnvelope, part: str, state: str) -> bool:
        """Record one part as done or none. False when the claim is no longer ours."""

    @abstractmethod
    async def complete(self, claim: ClaimedEnvelope) -> bool:
        """Delete a fully replayed row. False when the claim is no longer ours."""

    @abstractmethod
    async def release(self, claim: ClaimedEnvelope, *, next_attempt_at: datetime) -> bool:
        """Hand the row back as pending, due at `next_attempt_at`."""

    @abstractmethod
    async def fail(
        self, claim: ClaimedEnvelope, *, code: str, error: str, now: datetime
    ) -> bool:
        """Mark the row terminally failed and drop its payload."""

    @abstractmethod
    async def purge_failed(self, *, before: datetime, budget: SweepBudget) -> int: ...

    @abstractmethod
    async def depth(self, *, now: datetime) -> QueueDepthReading: ...


def _entity(value: str) -> UUID:
    return value if isinstance(value, UUID) else UUID(value)


class SqlEnvelopeStore(EnvelopeStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def stage(self, staged: StagedEnvelope, *, now: datetime) -> StageOutcome:
        game_id = _entity(staged.game_id)
        async with self._session_factory() as session:
            async with session.begin():
                existing = await session.get(EnvelopeRow, game_id)
                if existing is not None:
                    if existing.checksum_sha256 == staged.checksum:
                        return StageOutcome.DUPLICATE
                    raise EnvelopeConflictError(
                        f"game {staged.game_id} was staged twice with different content"
                    )
                session.add(
                    EnvelopeRow(
                        game_id=game_id,
                        envelope_version=staged.version,
                        payload=staged.payload,
                        byte_size=len(staged.payload),
                        checksum_sha256=staged.checksum,
                        state=FinishedGameHandoffState.PENDING.value,
                        history_state=HandoffPartState.PENDING.value,
                        usage_state=(
                            HandoffPartState.PENDING.value
                            if staged.has_usage
                            else HandoffPartState.NONE.value
                        ),
                        attempts=0,
                        next_attempt_at=now,
                        created_at=now,
                    )
                )
        return StageOutcome.STAGED

    async def claim_next(
        self, *, now: datetime, stale_after: timedelta
    ) -> ClaimedEnvelope | None:
        pending = FinishedGameHandoffState.PENDING.value
        processing = FinishedGameHandoffState.PROCESSING.value
        due = or_(
            (EnvelopeRow.state == pending) & (EnvelopeRow.next_attempt_at <= now),
            # A claim a dead process left behind: taken over, not waited on.
            (EnvelopeRow.state == processing)
            & (EnvelopeRow.claimed_at <= now - stale_after),
        )
        token = generate_uuid()
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.scalar(
                    select(EnvelopeRow)
                    .where(due)
                    .order_by(EnvelopeRow.next_attempt_at, EnvelopeRow.game_id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                if row is None:
                    return None
                attempts = row.attempts + 1
                # Compare-and-set on what was read: the lock above is a
                # no-op on SQLite, so the state is checked again in the
                # UPDATE itself. The loaded row is deliberately not kept in
                # step with the UPDATE; everything below reads from before.
                claimed = await session.execute(
                    update(EnvelopeRow)
                    .where(
                        EnvelopeRow.game_id == row.game_id,
                        EnvelopeRow.state == row.state,
                        EnvelopeRow.claim_token.is_(row.claim_token)
                        if row.claim_token is None
                        else EnvelopeRow.claim_token == row.claim_token,
                    )
                    .values(
                        state=processing,
                        claimed_at=now,
                        claim_token=token,
                        attempts=attempts,
                    )
                    .execution_options(synchronize_session=False)
                )
                if claimed.rowcount != 1:
                    return None
                return ClaimedEnvelope(
                    game_id=str(row.game_id),
                    token=str(token),
                    attempts=attempts,
                    version=row.envelope_version,
                    payload=bytes(row.payload or b""),
                    checksum=row.checksum_sha256,
                    history_state=row.history_state,
                    usage_state=row.usage_state,
                )

    def _ours(self, claim: ClaimedEnvelope):
        return (
            EnvelopeRow.game_id == _entity(claim.game_id),
            EnvelopeRow.claim_token == _entity(claim.token),
            EnvelopeRow.state == FinishedGameHandoffState.PROCESSING.value,
        )

    async def _update_ours(self, claim: ClaimedEnvelope, **values) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    update(EnvelopeRow).where(*self._ours(claim)).values(**values)
                )
                return result.rowcount == 1

    async def mark_part(self, claim: ClaimedEnvelope, part: str, state: str) -> bool:
        column = {"history": "history_state", "usage": "usage_state"}[part]
        return await self._update_ours(claim, **{column: state})

    async def complete(self, claim: ClaimedEnvelope) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    delete(EnvelopeRow).where(*self._ours(claim))
                )
                return result.rowcount == 1

    async def release(self, claim: ClaimedEnvelope, *, next_attempt_at: datetime) -> bool:
        return await self._update_ours(
            claim,
            state=FinishedGameHandoffState.PENDING.value,
            claimed_at=None,
            claim_token=None,
            next_attempt_at=next_attempt_at,
        )

    async def fail(
        self, claim: ClaimedEnvelope, *, code: str, error: str, now: datetime
    ) -> bool:
        return await self._update_ours(
            claim,
            state=FinishedGameHandoffState.FAILED.value,
            claimed_at=None,
            claim_token=None,
            payload=None,
            failure_code=code,
            last_error=error[:200],
            failed_at=now,
        )

    async def purge_failed(self, *, before: datetime, budget: SweepBudget) -> int:
        report = await delete_in_batches(
            self._session_factory,
            name="finished_game_envelopes",
            candidates=select(EnvelopeRow.game_id)
            .where(
                EnvelopeRow.state == FinishedGameHandoffState.FAILED.value,
                EnvelopeRow.failed_at < before,
            )
            .order_by(EnvelopeRow.failed_at, EnvelopeRow.game_id),
            delete_for=lambda keys: delete(EnvelopeRow).where(
                EnvelopeRow.game_id.in_(keys)
            ),
            budget=budget,
            now=before,
        )
        return int(report)

    async def depth(self, *, now: datetime) -> QueueDepthReading:
        from sqlalchemy import func

        async with self._session_factory() as session:
            live = (
                await session.execute(
                    select(func.count(), func.min(EnvelopeRow.created_at)).where(
                        EnvelopeRow.state != FinishedGameHandoffState.FAILED.value
                    )
                )
            ).one()
            failed = await session.scalar(
                select(func.count()).where(
                    EnvelopeRow.state == FinishedGameHandoffState.FAILED.value
                )
            )
        return QueueDepthReading(int(live[0] or 0), live[1], int(failed or 0))


# --- replay --------------------------------------------------------------------


class ReplayOutcome(StrEnum):
    RECORDED = "recorded"
    RETRIED = "retried"
    FAILED = "failed"
    # Another process reclaimed the row while this one held it: nothing
    # more is written under the old token, and the reclaimer does the rest.
    LOST_CLAIM = "lost_claim"


class _Transient(Exception):
    """A failure the next attempt may not see."""


async def replay_claim(
    store: EnvelopeStore,
    claim: ClaimedEnvelope,
    *,
    game_history_repo: GameHistoryRepository,
    prompt_list_repo: PromptListRepository | None,
    now: datetime,
    write_timeout: float | None = None,
) -> tuple[ReplayOutcome, str | None]:
    """Write one claimed envelope's parts into history. Never raises on the
    row's account: every failure ends in a released, failed or lost claim.
    Returns the outcome and, for a failure, its code."""

    # Read at call time, so a test can shorten it.
    if write_timeout is None:
        write_timeout = REPLAY_TIMEOUT_SECONDS

    async def _fail(code: HandoffFailureCode, error: str) -> tuple[ReplayOutcome, str]:
        logger.error("finished game %s will not be recorded (%s): %s", claim.game_id, code, error)
        if not await store.fail(claim, code=code.value, error=error, now=now):
            return ReplayOutcome.LOST_CLAIM, None
        # One lost game is one observation, whichever stage lost it (#482):
        # the same event the staging path records, under kind `replay`.
        metrics.record(
            RuntimeEventType.HISTORY_WRITE_ABANDONED,
            value=claim.attempts,
            details={"kind": "replay", "reason": code.value, "game_id": claim.game_id},
        )
        telemetry.history_write_abandoned("replay", code.value)
        return ReplayOutcome.FAILED, code.value

    if envelope_checksum(claim.payload) != claim.checksum:
        return await _fail(HandoffFailureCode.UNREADABLE, "stored bytes fail their checksum")
    try:
        envelope = decode_envelope(claim.payload, claim.version)
    except EnvelopeUnreadable as error:
        return await _fail(HandoffFailureCode.UNREADABLE, str(error))

    history_state = claim.history_state
    usage_state = claim.usage_state
    try:
        if history_state == HandoffPartState.PENDING.value:
            history = envelope.history
            try:
                await asyncio.wait_for(
                    game_history_repo.save_game(
                        history.record,
                        history.participants,
                        history.turns,
                        history.score_events,
                        history.drawings,
                        history.reactions,
                    ),
                    timeout=write_timeout,
                )
            except GameHistoryConflictError as error:
                return await _fail(HandoffFailureCode.CONFLICT, str(error))
            except (asyncio.TimeoutError, Exception) as error:
                raise _Transient(f"history: {error!r}") from error
            if not await store.mark_part(claim, "history", HandoffPartState.DONE.value):
                return ReplayOutcome.LOST_CLAIM, None
            history_state = HandoffPartState.DONE.value

        if usage_state == HandoffPartState.PENDING.value:
            if envelope.usage is None or prompt_list_repo is None:
                # Staged as owed but there is nothing to write: an envelope
                # from a build that decided later, or a deployment with no
                # prompt store. Recorded as none, not left pending for ever.
                state = HandoffPartState.NONE.value
            else:
                try:
                    await asyncio.wait_for(
                        prompt_list_repo.record_prompt_usage(
                            envelope.usage_revision_ids, envelope.usage
                        ),
                        timeout=write_timeout,
                    )
                except PromptUsageConflictError as error:
                    return await _fail(HandoffFailureCode.CONFLICT, str(error))
                except (asyncio.TimeoutError, Exception) as error:
                    raise _Transient(f"usage: {error!r}") from error
                state = HandoffPartState.DONE.value
            if not await store.mark_part(claim, "usage", state):
                return ReplayOutcome.LOST_CLAIM, None
    except _Transient as error:
        if claim.attempts >= MAX_ATTEMPTS:
            return await _fail(HandoffFailureCode.EXHAUSTED, str(error))
        wait = RETRY_BACKOFF_SECONDS[min(claim.attempts, len(RETRY_BACKOFF_SECONDS)) - 1]
        logger.warning(
            "finished game %s not recorded on attempt %d of %d (%s); next in %.0fs",
            claim.game_id,
            claim.attempts,
            MAX_ATTEMPTS,
            error,
            wait,
        )
        if not await store.release(claim, next_attempt_at=now + timedelta(seconds=wait)):
            return ReplayOutcome.LOST_CLAIM, None
        return ReplayOutcome.RETRIED, None

    if not await store.complete(claim):
        return ReplayOutcome.LOST_CLAIM, None
    return ReplayOutcome.RECORDED, None


@dataclass
class ReplayReport:
    recorded: int = 0
    retried: int = 0
    failed: int = 0
    lost: int = 0

    @property
    def attempted(self) -> int:
        return self.recorded + self.retried + self.failed + self.lost


# --- the worker ---------------------------------------------------------------


class FinishedGameHandoffWorker:
    """Stages finished games and replays them into history, one at a time."""

    def __init__(
        self,
        store: EnvelopeStore,
        *,
        game_history_repo: GameHistoryRepository,
        prompt_list_repo: PromptListRepository | None = None,
        interval_seconds: float | None = None,
        max_bytes: int | None = None,
        on_outcome: Callable[[str, str], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._game_history_repo = game_history_repo
        self._prompt_list_repo = prompt_list_repo
        self._interval = interval_seconds or sweep_interval_seconds()
        self._max_bytes = max_bytes or max_envelope_bytes()
        # Told which game ended up where, so the room that held it can open
        # its recap to reactions ("recorded") or stop offering them.
        self._on_outcome = on_outcome
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._wake = asyncio.Event()

    @property
    def interval_seconds(self) -> float:
        return self._interval

    @property
    def store(self) -> EnvelopeStore:
        return self._store

    def bind_outcome(self, callback: Callable[[str, str], None] | None) -> None:
        """Say who is told when a replay ends; the flow service, in practice."""
        self._on_outcome = callback

    def wake(self) -> None:
        """Ask for a sweep now. Safe from any coroutine on the loop."""
        self._wake.set()

    async def stage(self, envelope: FinishedGameEnvelope) -> StageOutcome:
        """The one write a room waits on. Raises on a database that will
        not take it, or an envelope past the ceiling; the caller records
        either as a lost game."""
        payload = encode_envelope(envelope)
        if len(payload) > self._max_bytes:
            raise EnvelopeTooLarge(len(payload), self._max_bytes)
        outcome = await self._store.stage(
            StagedEnvelope(
                game_id=envelope.game_id,
                version=ENVELOPE_VERSION,
                payload=payload,
                checksum=envelope_checksum(payload),
                has_usage=envelope.usage is not None,
            ),
            now=self._clock(),
        )
        telemetry.history_handoff(outcome.value)
        self.wake()
        return outcome

    async def replay_one(self) -> tuple[ReplayOutcome, str | None] | None:
        """Claim and replay the next due envelope; None when nothing is due."""
        now = self._clock()
        claim = await self._store.claim_next(now=now, stale_after=STALE_CLAIM_AFTER)
        if claim is None:
            return None
        try:
            outcome, code = await replay_claim(
                self._store,
                claim,
                game_history_repo=self._game_history_repo,
                prompt_list_repo=self._prompt_list_repo,
                now=now,
            )
        except asyncio.CancelledError:
            # A planned shutdown, not a failure: hand the row back so the
            # next process replays it at once rather than after the stale
            # window. Best effort on the way out; the stale rule is the
            # path a hard crash takes anyway.
            with contextlib.suppress(Exception):
                await self._store.release(claim, next_attempt_at=now)
            raise
        telemetry.history_replay(outcome.value if code is None else code)
        if self._on_outcome is not None and outcome in (
            ReplayOutcome.RECORDED,
            ReplayOutcome.FAILED,
        ):
            self._on_outcome(claim.game_id, outcome.value)
        return outcome, code

    async def drain(self, *, limit: int | None = None) -> ReplayReport:
        """Replay every due envelope, one at a time, until a claim finds nothing."""
        report = ReplayReport()
        while limit is None or report.attempted < limit:
            result = await self.replay_one()
            if result is None:
                break
            outcome, _ = result
            if outcome is ReplayOutcome.RECORDED:
                report.recorded += 1
            elif outcome is ReplayOutcome.RETRIED:
                report.retried += 1
            elif outcome is ReplayOutcome.FAILED:
                report.failed += 1
            else:
                report.lost += 1
        return report

    async def purge_failed(self, *, budget: SweepBudget | None = None) -> int:
        return await self._store.purge_failed(
            before=self._clock() - FAILED_RETENTION, budget=budget or SweepBudget()
        )

    async def run(self, *, health: LoopHealth | None = None) -> None:
        """Sweep for ever, surviving every failure but cancellation."""
        while True:
            self._wake.clear()
            try:
                started = time.monotonic()
                report = await self.drain()
                purged = await self.purge_failed()
                if health is not None:
                    health.record_success()
                    health.detail = {
                        "recorded": report.recorded,
                        "retried": report.retried,
                        "failed": report.failed,
                        "purged": purged,
                        "seconds": round(time.monotonic() - started, 3),
                    }
                if report.attempted or purged:
                    logger.info(
                        "history handoff sweep: %d recorded, %d retried, %d failed, %d purged",
                        report.recorded,
                        report.retried,
                        report.failed,
                        purged,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                if health is not None:
                    health.record_failure()
                logger.exception("history handoff sweep failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)

    def start(self, *, health: LoopHealth | None = None) -> asyncio.Task[None]:
        return asyncio.create_task(self.run(health=health))


async def stop_handoff_worker(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# --- by hand -------------------------------------------------------------------


async def _run(args) -> ReplayReport:
    from app.db import init_db, maintenance_engine
    from app.repositories.sqlalchemy import (
        SqlAlchemyGameHistoryRepository,
        SqlAlchemyPromptListRepository,
    )

    engine, factory = maintenance_engine()
    try:
        await init_db(engine)
        worker = FinishedGameHandoffWorker(
            SqlEnvelopeStore(factory),
            game_history_repo=SqlAlchemyGameHistoryRepository(factory),
            prompt_list_repo=SqlAlchemyPromptListRepository(factory),
        )
        return await worker.drain(limit=args.limit)
    finally:
        await engine.dispose()


def main() -> None:
    from app.logging_config import configure_logging

    parser = argparse.ArgumentParser(
        description="Replay staged finished games into history and report what happened."
    )
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    configure_logging()
    report = asyncio.run(_run(args))
    print(
        f"Attempted {report.attempted}: {report.recorded} recorded, "
        f"{report.retried} deferred, {report.failed} given up on, {report.lost} reclaimed elsewhere."
    )


if __name__ == "__main__":
    main()
