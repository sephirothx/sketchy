"""An in-memory `EnvelopeStore`, so the handoff can be exercised without a database.

Same contract as the SQL store, including the fencing: every write after a
claim checks the token, so the tests that reclaim a stale claim can prove
the old holder is refused.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4

from app.domain_values import FinishedGameHandoffState, HandoffPartState
from app.services.game_handoff import (
    ClaimedEnvelope,
    EnvelopeConflictError,
    EnvelopeStore,
    QueueDepthReading,
    StagedEnvelope,
    StageOutcome,
)
from app.services.sweeps import SweepBudget


@dataclass
class _Row:
    game_id: str
    version: int
    payload: bytes | None
    checksum: str
    state: str = FinishedGameHandoffState.PENDING.value
    history_state: str = HandoffPartState.PENDING.value
    usage_state: str = HandoffPartState.PENDING.value
    attempts: int = 0
    next_attempt_at: datetime | None = None
    claimed_at: datetime | None = None
    claim_token: str | None = None
    failure_code: str | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    failed_at: datetime | None = None


@dataclass
class MemoryEnvelopeStore(EnvelopeStore):
    rows: dict[str, _Row] = field(default_factory=dict)
    # Knobs for failure injection: every staging raises this, or hangs.
    fail_stage: Exception | None = None
    hang_stage: bool = False

    async def stage(self, staged: StagedEnvelope, *, now: datetime) -> StageOutcome:
        if self.hang_stage:
            await asyncio.sleep(3600)
        if self.fail_stage is not None:
            raise self.fail_stage
        existing = self.rows.get(staged.game_id)
        if existing is not None:
            if existing.checksum == staged.checksum:
                return StageOutcome.DUPLICATE
            raise EnvelopeConflictError(staged.game_id)
        self.rows[staged.game_id] = _Row(
            game_id=staged.game_id,
            version=staged.version,
            payload=staged.payload,
            checksum=staged.checksum,
            usage_state=(
                HandoffPartState.PENDING.value
                if staged.has_usage
                else HandoffPartState.NONE.value
            ),
            next_attempt_at=now,
            created_at=now,
        )
        return StageOutcome.STAGED

    async def claim_next(
        self, *, now: datetime, stale_after: timedelta
    ) -> ClaimedEnvelope | None:
        due = [
            row
            for row in self.rows.values()
            if (
                row.state == FinishedGameHandoffState.PENDING.value
                and row.next_attempt_at is not None
                and row.next_attempt_at <= now
            )
            or (
                row.state == FinishedGameHandoffState.PROCESSING.value
                and row.claimed_at is not None
                and row.claimed_at <= now - stale_after
            )
        ]
        if not due:
            return None
        row = min(due, key=lambda r: (r.next_attempt_at, r.game_id))
        row.state = FinishedGameHandoffState.PROCESSING.value
        row.claimed_at = now
        row.claim_token = str(uuid4())
        row.attempts += 1
        assert row.payload is not None
        return ClaimedEnvelope(
            game_id=row.game_id,
            token=row.claim_token,
            attempts=row.attempts,
            version=row.version,
            payload=row.payload,
            checksum=row.checksum,
            history_state=row.history_state,
            usage_state=row.usage_state,
        )

    def _ours(self, claim: ClaimedEnvelope) -> _Row | None:
        row = self.rows.get(claim.game_id)
        if (
            row is None
            or row.state != FinishedGameHandoffState.PROCESSING.value
            or row.claim_token != claim.token
        ):
            return None
        return row

    async def mark_part(self, claim: ClaimedEnvelope, part: str, state: str) -> bool:
        row = self._ours(claim)
        if row is None:
            return False
        setattr(row, {"history": "history_state", "usage": "usage_state"}[part], state)
        return True

    async def complete(self, claim: ClaimedEnvelope) -> bool:
        if self._ours(claim) is None:
            return False
        del self.rows[claim.game_id]
        return True

    async def release(self, claim: ClaimedEnvelope, *, next_attempt_at: datetime) -> bool:
        row = self._ours(claim)
        if row is None:
            return False
        row.state = FinishedGameHandoffState.PENDING.value
        row.claimed_at = None
        row.claim_token = None
        row.next_attempt_at = next_attempt_at
        return True

    async def fail(
        self, claim: ClaimedEnvelope, *, code: str, error: str, now: datetime
    ) -> bool:
        row = self._ours(claim)
        if row is None:
            return False
        row.state = FinishedGameHandoffState.FAILED.value
        row.claimed_at = None
        row.claim_token = None
        row.payload = None
        row.failure_code = code
        row.last_error = error[:200]
        row.failed_at = now
        return True

    async def purge_failed(self, *, before: datetime, budget: SweepBudget) -> int:
        doomed = [
            game_id
            for game_id, row in self.rows.items()
            if row.state == FinishedGameHandoffState.FAILED.value
            and row.failed_at is not None
            and row.failed_at < before
        ][: budget.rows]
        for game_id in doomed:
            del self.rows[game_id]
        return len(doomed)

    async def depth(self, *, now: datetime) -> QueueDepthReading:
        live = [r for r in self.rows.values() if r.state != FinishedGameHandoffState.FAILED.value]
        oldest = min((r.created_at for r in live if r.created_at), default=None)
        return QueueDepthReading(len(live), oldest, len(self.rows) - len(live))
