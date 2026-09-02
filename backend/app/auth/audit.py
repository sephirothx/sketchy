"""Privacy-safe request correlation for append-only audit events."""
from __future__ import annotations

from uuid import UUID

from starlette.requests import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import correlation
from app.auth.rate_limit import client_key, keyed_client_hash
from app.db.models import generate_uuid


def audit_request_id(request: Request) -> str:
    """The id the rest of this request is already logging under.

    The timing middleware accepts or mints one for every request and sets
    it as the correlation context, so the ledger row and the log lines of
    one request share an id. The header is read directly only when the
    middleware is absent - a router mounted on a bare test app.
    """
    current = correlation.request_id.get()
    if current:
        return current
    supplied = request.headers.get(correlation.REQUEST_ID_HEADER, "").strip()
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
