"""A staff role offered, and waiting on the second factor that starts it.

Granting a role and being able to use it are two moments, and R-AUTH-20 puts
something between them: a moderator or administrator must hold a second
factor, and the grant revokes every session the account has, so an account
promoted before it enrolled could not sign in to enrol. The first shape of
this rule made enrolment a precondition - the grant was refused until the
player had already set a factor up on their own. That worked, and it was
backwards. Every promotion began with an administrator telling somebody out
of band to go and find a setting, and the setting had to sit in front of every
player who would never be offered anything.

So the grant records an **offer** instead. `users.pending_role` says a role is
waiting; the account stays exactly what it was, keeps its sessions, and is
told. Enrolling the second factor is what takes the offer up, and only then
does the role move into `users.role` and the sessions end - which means the
account signs back in immediately afterwards and produces a code, and there is
never a staff account without a factor.

An offer that nobody takes up lapses. It is a standing invitation on somebody
else's account, and thirty days is long enough that a volunteer on holiday
still finds it and short enough that a grant nobody chased does not sit there
for ever. Nothing sweeps: the offer is checked where it is used, so a lapsed
one is refused when it would have been taken up and cleared then.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.sessions import revoke_sessions
from app.db.models import AuditEvent, User, generate_uuid
from app.domain_values import AuditTargetType

# How long an offer stands. Read from `users.pending_role_at`, which is the
# moment it was made.
OFFER_LIFETIME = timedelta(days=30)

ROLE_OFFERED_EVENT = "admin.role_offered"
ROLE_OFFER_LAPSED_EVENT = "admin.role_offer_lapsed"
ROLE_TAKEN_UP_EVENT = "admin.role_taken_up"


def offer_expired(offered_at: datetime | None, now: datetime | None = None) -> bool:
    """Whether an offer made then is too old to take up now."""
    if offered_at is None:
        return True
    at = now or datetime.now(timezone.utc)
    if offered_at.tzinfo is None:
        offered_at = offered_at.replace(tzinfo=timezone.utc)
    return at - offered_at > OFFER_LIFETIME


def pending_offer(user: User, now: datetime | None = None) -> str | None:
    """The role waiting for this account, if one is and it still stands."""
    if not user.pending_role:
        return None
    return None if offer_expired(user.pending_role_at, now) else user.pending_role


async def take_up_offer(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    request_id: str | None = None,
    ip_hash: str | None = None,
) -> str | None:
    """Turn a standing offer into the role, now that the factor exists.

    Called when an enrolment completes with the account's password proved,
    which is the whole of what R-AUTH-20 asks before a role is granted: a
    second factor, and evidence that its owner is the account's owner.

    Returns the role that took effect, or ``None`` when there was no offer to
    take up - including an offer that has lapsed, which is cleared here rather
    than left to be found again tomorrow.

    Everything happens in one transaction, for the reason the grant did: a
    role nobody was told about, or a notice about a role that was not granted,
    are both worse than either alone.
    """
    try:
        target = UUID(user_id)
    except (ValueError, TypeError):
        return None

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        async with session.begin():
            user = await session.get(User, target)
            if user is None or not user.pending_role:
                return None

            offered = user.pending_role
            offered_at = user.pending_role_at
            lapsed = offer_expired(offered_at, now)
            user.pending_role = None
            user.pending_role_at = None
            if lapsed:
                # Recorded rather than dropped: an administrator who granted a
                # role a month ago and finds no moderator should be able to
                # read why, and "it lapsed" is a different answer from "it was
                # never done".
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type=ROLE_OFFER_LAPSED_EVENT,
                        actor_user_id=None,
                        target_user_id=target,
                        target_type=AuditTargetType.USER.value,
                        target_id=str(target),
                        request_id=request_id,
                        ip_hash=ip_hash,
                        # snake_case, like every other ledger detail: these are
                        # stored fields an operator reads, not a wire payload.
                        details={
                            "role": offered,
                            "offered_at": (
                                offered_at.isoformat() if offered_at else None
                            ),
                        },
                        created_at=now,
                    )
                )
                return None

            previous = user.role
            user.role = offered
            # No actor: the administrator acted a while ago and is recorded
            # there; what happened here is the account taking the offer up.
            session.add(
                AuditEvent(
                    id=generate_uuid(),
                    event_type=ROLE_TAKEN_UP_EVENT,
                    actor_user_id=target,
                    target_user_id=target,
                    target_type=AuditTargetType.USER.value,
                    target_id=str(target),
                    request_id=request_id,
                    ip_hash=ip_hash,
                    details={"from": previous, "to": offered},
                    created_at=now,
                )
            )
            # The same two consequences the direct grant has, for the same two
            # reasons (R-AUTH-03, R-AUTH-20): a staff role must not be reachable
            # from a session issued before a code was ever required, and a
            # year-long player cookie must not stay a year long on a staff
            # account.
            await revoke_sessions(session, user_id=target)
            # No notice. `role_change_notices` exists for a change made while
            # the account was elsewhere - an administrator acts, and the
            # player finds a menu entry that appeared with no explanation.
            # This change is the account's own last action, taken in a dialog
            # that says what just happened, so a pop-up on the next page load
            # telling them again would be the app talking to itself.
            return offered
