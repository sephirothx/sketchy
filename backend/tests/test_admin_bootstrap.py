"""First-administrator bootstrap security and audit behavior."""
from __future__ import annotations

import pytest
import pytest_asyncio
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.admin import AdminBootstrapError, bootstrap_first_admin
from app.db.models import AuditEvent, Base, User, generate_uuid
from app.domain_values import AccountState, UserRole


@pytest_asyncio.fixture
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _add_user(database, *, username: str | None, state: str) -> str:
    async with database() as session:
        async with session.begin():
            user = User(
                id=generate_uuid(),
                username=username,
                password_hash="hash" if username else None,
                display_name=username or "Guest",
                state=state,
            )
            session.add(user)
        return str(user.id)


@pytest.mark.asyncio
async def test_bootstrap_promotes_registered_user_and_writes_audit(database):
    user_id = await _add_user(
        database, username="Operator", state=AccountState.REGISTERED.value
    )

    result = await bootstrap_first_admin(
        database, username="operator", reason="Initial production operator"
    )

    assert result.user_id == user_id
    async with database() as session:
        user = await session.get(User, UUID(user_id))
        event = await session.scalar(select(AuditEvent))
        assert user is not None and user.role == UserRole.ADMIN.value
        assert event is not None
        assert event.event_type == "admin.bootstrap"
        assert event.actor_user_id == user.id == event.target_user_id
        assert event.details == {"reason": "Initial production operator"}


@pytest.mark.asyncio
async def test_bootstrap_is_one_time_only(database):
    await _add_user(database, username="First", state=AccountState.REGISTERED.value)
    await _add_user(database, username="Second", state=AccountState.REGISTERED.value)
    await bootstrap_first_admin(database, username="First", reason="Initial setup")

    with pytest.raises(AdminBootstrapError, match="already exists"):
        await bootstrap_first_admin(database, username="Second", reason="Try again")

    async with database() as session:
        count = await session.scalar(select(func.count(AuditEvent.id)))
        assert count == 1


@pytest.mark.asyncio
async def test_bootstrap_rejects_guest_and_requires_reason(database):
    await _add_user(database, username=None, state=AccountState.ANONYMOUS.value)
    with pytest.raises(AdminBootstrapError, match="registered account"):
        await bootstrap_first_admin(database, username="missing", reason="Initial setup")
    with pytest.raises(AdminBootstrapError, match="reason"):
        await bootstrap_first_admin(database, username="missing", reason="  ")
