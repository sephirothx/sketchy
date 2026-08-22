"""Audited command for bootstrapping the first service administrator."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import async_engine, async_session_factory, init_db
from app.db.models import AuditEvent, User, generate_uuid
from app.domain_values import AccountState, UserRole


class AdminBootstrapError(RuntimeError):
    """Raised when the guarded first-administrator bootstrap cannot proceed."""


@dataclass(frozen=True)
class AdminBootstrapResult:
    user_id: str
    username: str


async def bootstrap_first_admin(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    username: str,
    reason: str,
) -> AdminBootstrapResult:
    """Promote one registered account if and only if no admin exists yet."""
    clean_username = username.strip()
    clean_reason = reason.strip()
    if not clean_username:
        raise AdminBootstrapError("username is required")
    if not clean_reason:
        raise AdminBootstrapError("an audit reason is required")

    async with session_factory() as session:
        async with session.begin():
            admin_count = await session.scalar(
                select(func.count(User.id)).where(User.role == UserRole.ADMIN.value)
            )
            if admin_count:
                raise AdminBootstrapError(
                    "an administrator already exists; use an authorized moderation flow"
                )

            user = await session.scalar(
                select(User).where(func.lower(User.username) == clean_username.lower())
            )
            if user is None or user.state != AccountState.REGISTERED.value:
                raise AdminBootstrapError(
                    "the target must be an existing registered account"
                )

            user.role = UserRole.ADMIN.value
            session.add(
                AuditEvent(
                    id=generate_uuid(),
                    event_type="admin.bootstrap",
                    actor_user_id=user.id,
                    target_user_id=user.id,
                    details={"reason": clean_reason},
                )
            )

        return AdminBootstrapResult(user_id=str(user.id), username=user.username or "")


async def _run(username: str, reason: str) -> AdminBootstrapResult:
    try:
        await init_db()
        return await bootstrap_first_admin(
            async_session_factory, username=username, reason=reason
        )
    finally:
        await async_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote the first registered Sketchy account to administrator."
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(_run(args.username, args.reason))
    except AdminBootstrapError as error:
        parser.error(str(error))
    print(f"Bootstrapped administrator {result.username} ({result.user_id}).")


if __name__ == "__main__":
    main()
