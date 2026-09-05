"""Operator-run password reset, for deployments that cannot send mail.

The zero-configuration default this game documents - embedded SQLite, a
generated signing key, no SMTP - has no way to mail a reset link, and the email
flow is the only self-service recovery there is. Recovery codes would close the
gap without an operator, at the cost of a second secret for people to lose.
This closes it with the access a self-hoster already has: a shell on the box.

It is deliberately not an API. There is no authentication that would make a
remote password reset safe, and adding one would be inventing a second
credential system beside the one being repaired.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.auth.mail import queue_email
from app.auth.password import PasswordPolicyError, hash_password, validate_password
from app.auth.sessions import revoke_sessions
from app.db import async_engine, async_session_factory, init_db
from app.db.models import AuditEvent, User, generate_uuid
from app.domain_values import AccountState, AuditTargetType, EmailTemplate


class OperatorResetError(RuntimeError):
    """The reset cannot proceed, and the operator needs to know why."""


@dataclass(frozen=True)
class OperatorResetResult:
    user_id: str
    username: str
    sessions_revoked: int
    notified: bool


async def reset_password_as_operator(
    session_factory,
    *,
    username: str,
    password: str,
    reason: str,
    now: datetime | None = None,
) -> OperatorResetResult:
    """Set an account's password directly, and record who did it.

    Audited like any other administrative action: a reset nobody can see is
    indistinguishable from a compromise.
    """
    try:
        validated = validate_password(password)
    except PasswordPolicyError as error:
        raise OperatorResetError(str(error)) from error
    if not reason.strip():
        raise OperatorResetError("A reason is required.")

    changed_at = now or datetime.now(timezone.utc)
    password_hash = await hash_password(validated)
    async with session_factory() as session:
        async with session.begin():
            user = await session.scalar(
                select(User)
                .where(func.lower(User.username) == username.strip().lower())
                .with_for_update()
            )
            if user is None:
                raise OperatorResetError(f"No account named {username!r}.")
            if user.state != AccountState.REGISTERED.value:
                raise OperatorResetError(
                    f"{username!r} is not a registered account."
                )
            user.password_hash = password_hash
            notified = bool(user.email and user.email_verified_at is not None)
            if notified:
                queue_email(
                    session,
                    to_address=user.email,
                    template=EmailTemplate.PASSWORD_CHANGED,
                    payload={"displayName": user.display_name},
                    user_id=user.id,
                    now=changed_at,
                )
            session.add(
                AuditEvent(
                    id=generate_uuid(),
                    event_type="account.password_reset_by_operator",
                    actor_user_id=None,
                    target_user_id=user.id,
                    target_type=AuditTargetType.USER.value,
                    target_id=str(user.id),
                    details={"reason": reason.strip()},
                    created_at=changed_at,
                )
            )
            # Committed with the password, or not at all (R-AUTH-10).
            revoked = await revoke_sessions(session, user_id=user.id, now=changed_at)
            user_id, resolved_name = str(user.id), user.username or username

    return OperatorResetResult(
        user_id=user_id,
        username=resolved_name,
        sessions_revoked=revoked,
        notified=notified,
    )


async def _run(args) -> OperatorResetResult:
    try:
        await init_db()
        return await reset_password_as_operator(
            async_session_factory,
            username=args.username,
            password=args.password,
            reason=args.reason,
        )
    finally:
        await async_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Set an account's password from the server. For deployments with "
            "no SMTP configured, where the emailed reset flow cannot run."
        )
    )
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--reason",
        required=True,
        help="Recorded in the audit log beside the reset.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Omit to be prompted, which keeps it out of the shell history.",
    )
    args = parser.parse_args()
    if not args.password:
        args.password = getpass.getpass("New password: ")
    try:
        result = asyncio.run(_run(args))
    except OperatorResetError as error:
        raise SystemExit(str(error)) from error
    print(
        f"Reset the password for {result.username} ({result.user_id}); "
        f"{result.sessions_revoked} signed-in device(s) were signed out."
    )
    print(
        "A notification is queued for their confirmed address."
        if result.notified
        else "No confirmed address on file, so nobody was notified."
    )


if __name__ == "__main__":
    main()
