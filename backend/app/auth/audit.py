"""Privacy-safe request correlation for append-only audit events."""
from __future__ import annotations

from uuid import UUID

from starlette.requests import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.rate_limit import client_key, keyed_client_hash
from app.db.models import generate_uuid


def audit_request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "").strip()
    if supplied:
        try:
            return str(UUID(supplied))
        except ValueError:
            pass
    return str(generate_uuid())


async def audit_coordinates(
    request: Request, session_factory: async_sessionmaker[AsyncSession]
) -> tuple[str, str]:
    return audit_request_id(request), await keyed_client_hash(
        session_factory, client_key(request)
    )
