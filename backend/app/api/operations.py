"""Operator-facing views of how the server is behaving.

Two surfaces over one set of numbers, because two different people need them.
`/metrics` is Prometheus text behind a bearer token, for a deployment with a
monitoring stack. The JSON under `/api/admin` is for the in-app page, behind
the administrator role that already exists.

The per-player view is the one with a cost. It answers "which account keeps
disconnecting", which is exactly what an operator needs when diagnosing abuse
or a flaky client, and it is also a surveillance surface on the game's own
players. Every use writes an audit event naming the account looked at, so the
looking is itself on the record.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
import os

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.admin_auth import admin_gate
from app.auth.audit import audit_coordinates
from app.db.models import (
    AuditEvent,
    GameRecord,
    PromptList,
    PromptVersion,
    User,
    generate_uuid,
)
from app.domain_values import AuditTargetType, GameOutcome
from app.services.runtime_metrics import (
    daily_totals,
    metrics,
    recent_events,
    stored_event_count,
)


def _scrape_token() -> str:
    return os.environ.get("METRICS_TOKEN", "").strip()


def _prometheus_lines() -> list[str]:
    gauges = metrics.gauges
    lines = [
        "# HELP sketchy_rooms_live Rooms currently held by this worker.",
        "# TYPE sketchy_rooms_live gauge",
        f"sketchy_rooms_live {gauges.rooms}",
        "# HELP sketchy_players_live Players currently seated in a room.",
        "# TYPE sketchy_players_live gauge",
        f"sketchy_players_live {gauges.players}",
        "# HELP sketchy_active_games_live Rooms with a game in progress.",
        "# TYPE sketchy_active_games_live gauge",
        f"sketchy_active_games_live {gauges.active_games}",
        "# HELP sketchy_rooms_peak Most rooms held at once since start.",
        "# TYPE sketchy_rooms_peak gauge",
        f"sketchy_rooms_peak {gauges.peak_rooms}",
        "# HELP sketchy_players_peak Most players seated at once since start.",
        "# TYPE sketchy_players_peak gauge",
        f"sketchy_players_peak {gauges.peak_players}",
        "# HELP sketchy_active_games_peak Most games running at once since start.",
        "# TYPE sketchy_active_games_peak gauge",
        f"sketchy_active_games_peak {gauges.peak_active_games}",
        "# HELP sketchy_events_buffered Observations waiting to be written.",
        "# TYPE sketchy_events_buffered gauge",
        f"sketchy_events_buffered {metrics.buffered}",
        "# HELP sketchy_events_dropped_total Observations lost to a full buffer.",
        "# TYPE sketchy_events_dropped_total counter",
        f"sketchy_events_dropped_total {metrics.dropped_events}",
        "# HELP sketchy_events_total Observations recorded since start, by kind.",
        "# TYPE sketchy_events_total counter",
    ]
    for event_type, count in sorted(metrics.totals().items()):
        lines.append(f'sketchy_events_total{{event="{event_type}"}} {count}')
    return lines


async def _resolve_subjects(
    session: AsyncSession, rows: list[AuditEvent]
) -> dict[tuple[str | None, str | None], str]:
    """Look up a readable name for each actor and target in a page of entries.

    Read here and never written into `audit_events`. That table is append-only,
    and a name copied into it would be personal data in a place erasure cannot
    reach - the point of resolving live is that deleting an account stops the
    ledger naming them while the entry itself still stands. It is also why a
    name may come back as "Deleted player": that is the truth about who that
    account is now, which is what an administrator following a trail needs.

    One query per kind of subject rather than one per row.
    """
    wanted: dict[str, set[str]] = {}
    for row in rows:
        if row.actor_user_id:
            wanted.setdefault("user", set()).add(str(row.actor_user_id))
        if row.target_type and row.target_id:
            wanted.setdefault(row.target_type, set()).add(row.target_id)

    resolved: dict[tuple[str | None, str | None], str] = {}

    def _ids(kind: str) -> dict[UUID, list[str]]:
        """Every spelling each id arrived in, against the id itself.

        The same account can appear as `01a0-...` from code and as bare hex
        from a backfill, because casting a UUID to text drops the dashes. Both
        have to find the same row, and each has to be answered in the spelling
        it was asked in - a name keyed only one way leaves the other rendering
        as a raw id.
        """
        found: dict[UUID, list[str]] = {}
        for value in wanted.get(kind, set()):
            try:
                parsed = UUID(value)
            except ValueError:
                # A target id need not be a UUID - app_config names a key.
                continue
            found.setdefault(parsed, []).append(value)
        return found

    if user_ids := _ids("user"):
        for user in (
            await session.scalars(select(User).where(User.id.in_(user_ids)))
        ).all():
            for spelling in user_ids.get(user.id, []):
                resolved[("user", spelling)] = user.display_name

    if list_ids := _ids("prompt_list"):
        for prompt_list in (
            await session.scalars(
                select(PromptList).where(PromptList.id.in_(list_ids))
            )
        ).all():
            for spelling in list_ids.get(prompt_list.id, []):
                resolved[("prompt_list", spelling)] = prompt_list.name

    if version_ids := _ids("prompt_version"):
        for version in (
            await session.scalars(
                select(PromptVersion).where(PromptVersion.id.in_(version_ids))
            )
        ).all():
            for spelling in version_ids.get(version.id, []):
                resolved[("prompt_version", spelling)] = version.canonical_answer

    return resolved


def create_operations_router(
    session_factory: async_sessionmaker[AsyncSession],
) -> APIRouter:
    router = APIRouter()
    require_admin = admin_gate(session_factory)

    @router.get("/metrics")
    async def scrape(request: Request):
        """Prometheus exposition, for deployments that scrape.

        A bearer token rather than the session cookie: a scraper has no
        session, and the alternative - leaving it open - publishes the shape of
        the deployment to anyone who asks.
        """
        expected = _scrape_token()
        if not expected:
            raise HTTPException(
                status_code=404,
                detail="Metrics scraping is not enabled.",
            )
        supplied = request.headers.get("authorization", "")
        if supplied != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail="Not authorized.")
        body = "\n".join(_prometheus_lines()) + "\n"
        return Response(content=body, media_type="text/plain; version=0.0.4")

    @router.get("/api/admin/metrics")
    async def live_metrics(request: Request):
        """What is happening right now, and what has happened in total."""
        await require_admin(request)
        gauges = metrics.gauges
        stored = await stored_event_count(session_factory)
        async with session_factory() as session:
            outcomes = {
                outcome: count
                for outcome, count in (
                    await session.execute(
                        select(GameRecord.outcome, func.count(GameRecord.id)).group_by(
                            GameRecord.outcome
                        )
                    )
                ).all()
            }
        return {
            "live": {
                "rooms": gauges.rooms,
                "players": gauges.players,
                "activeGames": gauges.active_games,
            },
            "peak": {
                "rooms": gauges.peak_rooms,
                "players": gauges.peak_players,
                "activeGames": gauges.peak_active_games,
            },
            "recorder": {
                "buffered": metrics.buffered,
                "dropped": metrics.dropped_events,
                "storedEvents": stored,
                "startedAt": metrics.started_at.isoformat(),
            },
            "totals": metrics.totals(),
            "games": {
                "finished": outcomes.get(GameOutcome.FINISHED.value, 0),
                "abandoned": outcomes.get(GameOutcome.ABANDONED.value, 0),
                "shutdown": outcomes.get(GameOutcome.SHUTDOWN.value, 0),
            },
        }

    @router.get("/api/admin/metrics/daily")
    async def daily(
        request: Request,
        days: int = Query(default=30, ge=1, le=365),
    ):
        """The permanent aggregates, which outlive the raw rows behind them."""
        await require_admin(request)
        return {"days": await daily_totals(session_factory, days=days)}

    @router.get("/api/admin/metrics/events")
    async def events(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
        event_type: str | None = Query(default=None, alias="eventType"),
        room_id: str | None = Query(default=None, alias="roomId"),
    ):
        """Raw observations, for looking at one room or one kind of event."""
        await require_admin(request)
        return {
            "events": await recent_events(
                session_factory,
                limit=limit,
                event_type=event_type,
                room_id=room_id,
            )
        }

    @router.get("/api/admin/players/{user_id}/activity")
    async def player_activity(
        user_id: str,
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
    ):
        """One account's recorded activity.

        This is a surveillance surface on the game's own players, so looking is
        recorded: the audit event names both the administrator who looked and
        the account they looked at.
        """
        admin = await require_admin(request)
        try:
            target_id = UUID(user_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="No such player.") from error
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        async with session_factory() as session:
            async with session.begin():
                target = await session.get(User, target_id)
                if target is None:
                    raise HTTPException(status_code=404, detail="No such player.")
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="admin.player_activity_viewed",
                        actor_user_id=admin.id,
                        target_user_id=target_id,
                        target_type=AuditTargetType.USER.value,
                        target_id=str(target_id),
                        request_id=request_id,
                        ip_hash=ip_hash,
                        details={},
                        created_at=datetime.now(timezone.utc),
                    )
                )
                display_name = target.display_name
        return {
            "player": {"id": user_id, "displayName": display_name},
            "events": await recent_events(
                session_factory, limit=limit, user_id=target_id
            ),
        }

    @router.get("/api/admin/audit")
    async def audit_ledger(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
        event_type: str | None = Query(default=None, alias="eventType"),
        target_type: str | None = Query(default=None, alias="targetType"),
        target_id: str | None = Query(default=None, alias="targetId"),
    ):
        """The append-only record of security- and moderation-sensitive actions.

        Reachable now that a takedown names what it took down: filtering by
        target is the question the ledger could not answer before #397.
        """
        await require_admin(request)
        async with session_factory() as session:
            statement = select(AuditEvent).order_by(AuditEvent.created_at.desc())
            if event_type:
                statement = statement.where(AuditEvent.event_type == event_type)
            if target_type:
                statement = statement.where(AuditEvent.target_type == target_type)
            if target_id:
                statement = statement.where(AuditEvent.target_id == target_id)
            rows = (await session.execute(statement.limit(limit))).scalars().all()
            names = await _resolve_subjects(session, rows)
        return {
            "entries": [
                {
                    "id": str(row.id),
                    "eventType": row.event_type,
                    "createdAt": row.created_at.isoformat(),
                    "actorUserId": (
                        str(row.actor_user_id) if row.actor_user_id else None
                    ),
                    "targetUserId": (
                        str(row.target_user_id) if row.target_user_id else None
                    ),
                    "targetType": row.target_type,
                    "targetId": row.target_id,
                    "actorName": names.get(("user", str(row.actor_user_id)))
                    if row.actor_user_id
                    else None,
                    "targetName": names.get((row.target_type, row.target_id)),
                    "details": row.details,
                }
                for row in rows
            ]
        }

    return router
