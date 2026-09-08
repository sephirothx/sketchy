"""Opaque, hashed, server-side account session lifecycle."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from http.cookies import SimpleCookie
import secrets
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AuditEvent, AuthSession, User, UserBan, generate_uuid
from app.deployment import is_production
from app.domain_values import AuditTargetType, UserRole


COOKIE_NAME = "sketchy_session"
# In production the cookie is `__Host-sketchy_session` (#467). A browser
# accepts a `__Host-` cookie only when it was set over HTTPS with `Secure`,
# `Path=/` and no `Domain`, and it can then be set by nobody else: not by a
# subdomain, not by a plain-HTTP hop somebody has managed to put in front of
# the server. The plain name stays in development because a browser refuses
# the prefixed one over http://localhost.
HOST_COOKIE_PREFIX = "__Host-"


@dataclass(frozen=True)
class SessionLifetime:
    """How long a session may live, sit unused, and go without rotating."""

    absolute: timedelta
    idle: timedelta
    rotate_after: timedelta


# A player's cookie still lasts a year, deliberately: this is a drawing game,
# people come back to it in months, and being signed out is the failure they
# actually meet. What was missing was the other bound - a session that nobody
# has used since spring stayed valid until next spring (#468). Ninety days of
# silence now ends it, which is what removes the abandoned-device and
# long-forgotten-cookie cases without touching anybody who plays.
#
# Weekly rotation replaces the old rotate-at-halfway, which fired once at six
# months and so did nothing for a token stolen in month seven. Rotation is
# per-device (it swaps the cookie on the browser making the request and leaves
# every other device alone), so its cost is nothing a player can see, and its
# value is that a copied token stops working within a week of the real browser
# being used - and, by R-AUTH-22, announces the theft when it is tried.
PLAYER_LIFETIME = SessionLifetime(
    absolute=timedelta(days=365),
    idle=timedelta(days=90),
    rotate_after=timedelta(days=7),
)
# Staff are the compromise the audit was actually about: a moderator's cookie
# reads reports, reported drawings and operational data, and an administrator's
# changes a live server. A week, and a day of inactivity, is the most that is
# worth carrying for a role that also has to pass R-AUTH-21's step-up before it
# can do anything destructive. Rotation is daily rather than weekly, because a
# weekly rotation on a week-long session would never fire.
STAFF_LIFETIME = SessionLifetime(
    absolute=timedelta(days=7),
    idle=timedelta(hours=24),
    rotate_after=timedelta(days=1),
)

# Kept for callers that only want the outer bound of an ordinary session.
SESSION_TTL = PLAYER_LIFETIME.absolute

# A browser with several requests in flight can rotate the same row twice, and
# the loser of that race holds a token revoked a moment ago. Sixty seconds of
# grace lets it resolve rather than signing somebody out for using their own
# browser normally. Outside the window a revoked predecessor is not a race: it
# is a copy somebody kept, and R-AUTH-22 treats it as one.
ROTATION_GRACE = timedelta(seconds=60)

LAST_USED_WRITE_INTERVAL = timedelta(minutes=5)
TOKEN_BYTES = 32

# How long a step-up assertion stands before a destructive action asks again
# (R-AUTH-21). Long enough to work through a moderation queue, short enough
# that a cookie stolen from an idle staff browser is not already stepped up.
STEP_UP_WINDOW = timedelta(minutes=15)

STAFF_ROLES = (UserRole.MODERATOR.value, UserRole.ADMIN.value)


def lifetime_for(role: str | None) -> SessionLifetime:
    """The lifetime rule this account's sessions live under."""
    return STAFF_LIFETIME if role in STAFF_ROLES else PLAYER_LIFETIME


@dataclass(frozen=True)
class SessionData:
    id: str
    user_id: str
    device_label: str
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    # The rule this session was issued under. Frozen at issue, because a role
    # change revokes every session the account holds (R-AUTH-20) - so there is
    # no such thing as a live session issued under a role its owner no longer
    # has, and resolving one never has to ask what their role is now.
    lifetime: SessionLifetime = PLAYER_LIFETIME
    # When silence alone would end it, as the row itself records.
    idle_expires_at: datetime | None = None
    # Set when this session was last used from a browser that does not match
    # the one it was issued to - or, for staff, a different network. What the
    # device list shows and what clears a step-up (R-AUTH-22).
    anomaly_at: datetime | None = None
    anomaly_count: int = 0
    # The last successful step-up assertion on this session (R-AUTH-21).
    stepped_up_at: datetime | None = None

    def is_stepped_up(self, *, now: datetime | None = None) -> bool:
        """Whether a destructive action may proceed without asking again."""
        if self.stepped_up_at is None:
            return False
        checked_at = now or datetime.now(timezone.utc)
        return checked_at - self.stepped_up_at < STEP_UP_WINDOW


@dataclass(frozen=True)
class IssuedSession:
    token: str
    session: SessionData


@dataclass(frozen=True)
class SessionResolution:
    session: SessionData | None
    banned_user_id: str | None = None


def hash_session_token(token: str) -> str:
    """One-way digest for a high-entropy token; raw tokens never enter storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def cookie_name() -> str:
    """The session cookie's name for this deployment: prefixed in production."""
    return HOST_COOKIE_PREFIX + COOKIE_NAME if is_production() else COOKIE_NAME


def session_token_from_cookie_header(cookie_header: str | None) -> str | None:
    """Extract the opaque token from an HTTP or Socket.IO cookie header."""
    if not cookie_header:
        return None
    jar = SimpleCookie()
    try:
        jar.load(cookie_header)
    except Exception:
        return None
    morsel = jar.get(cookie_name())
    return morsel.value if morsel and morsel.value else None


def device_label_from_user_agent(user_agent: str | None) -> str:
    """Derive a useful coarse label without storing a detailed fingerprint."""
    value = user_agent or ""
    if "Firefox/" in value:
        browser = "Firefox"
    elif "Edg/" in value:
        browser = "Edge"
    elif "Chrome/" in value or "CriOS/" in value:
        browser = "Chrome"
    elif "Safari/" in value:
        browser = "Safari"
    else:
        browser = "Browser"

    if "Android" in value:
        platform = "Android"
    elif "iPhone" in value or "iPad" in value:
        platform = "iOS"
    elif "Windows" in value:
        platform = "Windows"
    elif "Macintosh" in value:
        platform = "macOS"
    elif "Linux" in value:
        platform = "Linux"
    else:
        platform = "unknown device"
    return f"{browser} on {platform}"


def lifetime_of(record: AuthSession) -> SessionLifetime:
    """The rule this session was issued under, read off the row.

    From the span the row itself records rather than from the account's role,
    which resolving a token deliberately does not look up (R-AUTH-03): a role
    change revokes every session, so the span a live row carries is always the
    one its owner's role allows. A staff session is issued for seven days and
    a player's for a year, so the two are never close enough to confuse.

    This is what makes rotation work for staff. Defaulting to the player rule
    here - as an earlier version did by taking an optional role nobody on the
    resolve path had - gave staff sessions the seven-day rotation interval,
    which their own seven-day expiry meant they never reached.
    """
    return (
        STAFF_LIFETIME
        if record.expires_at - record.created_at <= STAFF_LIFETIME.absolute
        else PLAYER_LIFETIME
    )


def _session_data(record: AuthSession) -> SessionData:
    """The immutable view of one row, reading only that row."""
    return SessionData(
        id=str(record.id),
        user_id=str(record.user_id),
        device_label=record.device_label,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        expires_at=record.expires_at,
        lifetime=lifetime_of(record),
        idle_expires_at=record.idle_expires_at,
        anomaly_at=record.anomaly_at,
        anomaly_count=record.anomaly_count,
        stepped_up_at=record.stepped_up_at,
    )


async def create_session(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    device_label: str,
    rotated_from_id: str | None = None,
    ip_hash: str | None = None,
    role: str | None = None,
    now: datetime | None = None,
) -> IssuedSession:
    """Issue a session under the lifetime its account's role allows.

    The role is read here when the caller does not supply it, rather than
    defaulting to a player's year: a staff session written with a player's
    `expires_at` would be clamped correctly on every resolution, but the row
    itself would claim a year, and a row that says something other than what
    the server enforces is the kind of disagreement worth not creating.
    """
    issued_at = now or datetime.now(timezone.utc)
    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    if role is None:
        # Only when the caller could not say. Read on its own connection and
        # not inside the write transaction below: guest provisioning is the
        # hottest write path this server has, and SQLite serializes writers,
        # so a SELECT inside the write transaction holds the lock for the
        # length of both. Every caller that already knows the role passes it.
        async with session_factory() as reader:
            role = await reader.scalar(
                select(User.role).where(User.id == UUID(user_id))
            )
    lifetime = lifetime_for(role)
    async with session_factory() as database:
        async with database.begin():
            record = AuthSession(
                id=generate_uuid(),
                user_id=UUID(user_id),
                token_hash=hash_session_token(raw_token),
                device_label=device_label[:64],
                rotated_from_id=UUID(rotated_from_id) if rotated_from_id else None,
                ip_hash=ip_hash,
                last_ip_hash=ip_hash,
                created_at=issued_at,
                last_used_at=issued_at,
                expires_at=issued_at + lifetime.absolute,
                idle_expires_at=issued_at + lifetime.idle,
            )
            database.add(record)
    return IssuedSession(token=raw_token, session=_session_data(record))


async def resolve_session(
    session_factory: async_sessionmaker[AsyncSession],
    token: str | None,
    *,
    now: datetime | None = None,
    ip_hash: str | None = None,
    device_label: str | None = None,
) -> SessionData | None:
    """`resolve_session_status` for callers with no interest in the ban case."""
    return (
        await resolve_session_status(
            session_factory,
            token,
            now=now,
            ip_hash=ip_hash,
            device_label=device_label,
        )
    ).session


async def resolve_session_status(
    session_factory: async_sessionmaker[AsyncSession],
    token: str | None,
    *,
    now: datetime | None = None,
    ip_hash: str | None = None,
    device_label: str | None = None,
) -> SessionResolution:
    """Resolve a token and retain the reason an active ban rejected it.

    Revoked ban-time tokens must remain recognizable until the ban expires;
    otherwise the next request would look like a cookieless visitor and could
    provision a replacement guest account. The raw token still never leaves
    this boundary or enters storage.

    Two bounds are applied here rather than one (#468), and both are columns
    on the row this already reads: `expires_at`, and `idle_expires_at`, which
    moves forward with `last_used_at`. Deliberately not derived from the
    account's role - that would mean joining `users` on the single hottest
    read in the server, once per request and once per socket handshake, to
    learn something that cannot have changed: a role change revokes every
    session the account holds (R-AUTH-20), so a live session is always one
    issued under the role its owner has now.

    `ip_hash` and `device_label` describe the caller, and are compared against
    what this session has been used from before. They are optional because the
    socket handshake and the HTTP path know different amounts about a caller,
    and a signal that is unavailable should record nothing rather than record
    a false one.
    """
    if not token:
        return SessionResolution(session=None)
    checked_at = now or datetime.now(timezone.utc)
    digest = hash_session_token(token)
    async with session_factory() as database:
        async with database.begin():
            active_ban_created_at = (
                select(UserBan.created_at)
                .where(
                    UserBan.user_id == AuthSession.user_id,
                    UserBan.revoked_at.is_(None),
                    or_(
                        UserBan.expires_at.is_(None),
                        UserBan.expires_at > checked_at,
                    ),
                )
                .order_by(UserBan.created_at.desc())
                .limit(1)
                .correlate(AuthSession)
                .scalar_subquery()
            )
            result = (
                await database.execute(
                    select(
                        AuthSession,
                        active_ban_created_at.label("banned_at"),
                    ).where(AuthSession.token_hash == digest)
                )
            ).one_or_none()
            if result is None:
                return SessionResolution(session=None)
            record, banned_at = result
            if banned_at is not None:
                # A token that was valid when the ban landed remains usable
                # only for the narrow export/delete escape hatch selected by
                # HTTP middleware. A token revoked before the ban cannot be
                # resurrected as a privacy credential.
                was_active_when_banned = (
                    record.expires_at > banned_at
                    and (
                        record.revoked_at is None
                        or record.revoked_at >= banned_at
                    )
                )
                return SessionResolution(
                    session=(
                        _session_data(record) if was_active_when_banned else None
                    ),
                    banned_user_id=str(record.user_id),
                )
            if record.revoked_at is not None:
                replayed = await _rotated_away_token(
                    database, record, checked_at=checked_at
                )
                if replayed is None:
                    return SessionResolution(session=None)
                if replayed is False:
                    # Inside the grace window: a browser that had two requests
                    # in flight when this row rotated, not a thief. Let its own
                    # row answer; the successor cookie is already on its way
                    # back to it.
                    return SessionResolution(session=_session_data(record))
                # Beyond the grace window a revoked predecessor is a copy
                # somebody kept. Everything descended from it goes, which
                # signs out the thief and the real device together - the
                # device can sign in again, and being asked to is how its
                # owner learns the token was taken (R-AUTH-22).
                revoked = await _revoke_rotation_chain(
                    database, record, now=checked_at
                )
                database.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="session.token_replayed",
                        actor_user_id=None,
                        target_user_id=record.user_id,
                        target_type=AuditTargetType.USER.value,
                        target_id=str(record.user_id),
                        details={
                            "device_label": record.device_label,
                            "sessions_revoked": revoked,
                        },
                    )
                )
                return SessionResolution(session=None)

            if (
                checked_at >= record.expires_at
                or checked_at >= record.idle_expires_at
            ):
                return SessionResolution(session=None)

            anomaly = _anomaly_reason(
                record, ip_hash=ip_hash, device_label=device_label
            )
            if anomaly is not None:
                # Recorded immediately rather than on the throttled write
                # below: the whole value of the signal is that it is there
                # the first time the session is used from somewhere new.
                record.anomaly_at = checked_at
                record.anomaly_count = (record.anomaly_count or 0) + 1
                record.last_ip_hash = ip_hash or record.last_ip_hash
                record.last_used_at = checked_at
                record.idle_expires_at = _idle_deadline(record, checked_at)
                # A step-up is an assertion about the browser holding the
                # session. A session that has moved has to make it again.
                record.stepped_up_at = None
                database.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="session.anomaly",
                        actor_user_id=None,
                        target_user_id=record.user_id,
                        target_type=AuditTargetType.USER.value,
                        target_id=str(record.user_id),
                        details={"reason": anomaly, "session_id": str(record.id)},
                    )
                )
            elif checked_at - record.last_used_at >= LAST_USED_WRITE_INTERVAL:
                record.last_used_at = checked_at
                record.idle_expires_at = _idle_deadline(record, checked_at)
                if ip_hash:
                    record.last_ip_hash = ip_hash
        return SessionResolution(session=_session_data(record))


async def _rotated_away_token(
    database: AsyncSession, record: AuthSession, *, checked_at: datetime
) -> bool | None:
    """Whether a revoked row is a replayed predecessor, a race, or just gone.

    ``None`` for a session that was simply revoked - a logout, a password
    change, a device the owner dropped - which is the ordinary case and buys
    nobody anything. ``False`` while a rotation's grace window is open.
    ``True`` once a token that was rotated away is presented after it, which
    is the one shape that means a second copy exists.
    """
    successor = await database.scalar(
        select(AuthSession.id).where(AuthSession.rotated_from_id == record.id)
    )
    if successor is None:
        return None
    if (
        record.revoked_at is not None
        and checked_at - record.revoked_at < ROTATION_GRACE
    ):
        return False
    return True


async def _revoke_rotation_chain(
    database: AsyncSession, record: AuthSession, *, now: datetime
) -> int:
    """Revoke every session descended from this one, and this one's successor.

    Walked rather than done in one statement because the chain is a linked
    list through `rotated_from_id`, and it is short by construction: one link
    per rotation the device has lived through.
    """
    revoked = 0
    cursor: UUID | None = record.id
    seen: set[UUID] = {record.id}
    while cursor is not None:
        successor = (
            await database.execute(
                select(AuthSession).where(AuthSession.rotated_from_id == cursor)
            )
        ).scalar_one_or_none()
        if successor is None or successor.id in seen:
            break
        seen.add(successor.id)
        if successor.revoked_at is None:
            successor.revoked_at = now
            revoked += 1
        cursor = successor.id
    return revoked


def _idle_deadline(record: AuthSession, used_at: datetime) -> datetime:
    """Push the idle window forward, never past the session's own expiry.

    The window comes from the lifetime the row itself records. It used to be
    measured as `idle_expires_at - last_used_at`, which reads as "how long
    this session is given" but is only that before anybody uses it: both
    callers set `last_used_at` to now first, so the subtraction gave the time
    *remaining*, and adding that back to now returned the deadline unchanged.
    The window never moved, and a session was ended ninety days after it was
    issued however much it had been used.
    """
    return min(used_at + lifetime_of(record).idle, record.expires_at)


def _anomaly_reason(
    record: AuthSession,
    *,
    ip_hash: str | None,
    device_label: str | None,
) -> str | None:
    """What about this use of the session does not match how it was issued.

    A changed browser is the signal worth acting on for everybody: a session
    issued to Chrome on Windows and used from Safari on macOS is a token that
    has moved between machines, and no ordinary browsing does that.

    A changed address deliberately is **not**, for players. A phone crossing
    between mobile data and wi-fi changes address several times an hour, and a
    signal that fires that often is noise nobody can read. It counts only for
    staff, whose sessions last a week rather than a year and whose credentials
    are worth the false positives (#468).
    """
    if (
        device_label
        and record.device_label
        and device_label[:64] != record.device_label
    ):
        return "device"
    # Staff sessions are the short ones, and the only ones for which an
    # address change is worth the false positives. Same reading of the row
    # that decides rotation, so there is one rule rather than two.
    if (
        lifetime_of(record) is STAFF_LIFETIME
        and ip_hash
        and record.last_ip_hash
        and ip_hash != record.last_ip_hash
    ):
        return "network"
    return None


def should_rotate(session: SessionData, *, now: datetime | None = None) -> bool:
    """Whether this device's token has gone long enough without changing.

    Measured from `created_at`, which a rotation resets by minting a new row,
    so this is "how long since this device's current token was issued" rather
    than "how long since the device first signed in".
    """
    checked_at = now or datetime.now(timezone.utc)
    return checked_at - session.created_at >= session.lifetime.rotate_after


async def rotate_session(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    session_id: str,
    user_id: str,
    device_label: str,
    role: str | None = None,
    ip_hash: str | None = None,
    now: datetime | None = None,
) -> IssuedSession | None:
    """Replace one device's token, leaving every other device alone.

    The predecessor is revoked and the successor points back at it, so a
    later use of the old token is recognizable as a replay rather than as an
    unknown cookie (R-AUTH-22). Both statements share one transaction: a
    successor without its predecessor revoked would be two live tokens for one
    device, and a revocation without its successor would sign somebody out
    mid-request.
    """
    rotated_at = now or datetime.now(timezone.utc)
    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    async with session_factory() as database:
        async with database.begin():
            if role is None:
                role = await database.scalar(
                    select(User.role).where(User.id == UUID(user_id))
                )
            lifetime = lifetime_for(role)
            successor = AuthSession(
                id=generate_uuid(),
                user_id=UUID(user_id),
                token_hash=hash_session_token(raw_token),
                device_label=device_label[:64],
                rotated_from_id=UUID(session_id),
                ip_hash=ip_hash,
                last_ip_hash=ip_hash,
                created_at=rotated_at,
                last_used_at=rotated_at,
                expires_at=rotated_at + lifetime.absolute,
                idle_expires_at=rotated_at + lifetime.idle,
            )
            revoked = await database.execute(
                update(AuthSession)
                .where(
                    AuthSession.id == UUID(session_id),
                    AuthSession.user_id == UUID(user_id),
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > rotated_at,
                )
                # The step-up goes with the revocation. A predecessor still
                # resolves for sixty seconds (R-AUTH-22, so a parallel request
                # is not a logout), and leaving the grant on it meant a copied
                # staff token could authorize a destructive action inside that
                # window using a proof the real browser had just given up -
                # the successor is issued without one.
                .values(revoked_at=rotated_at, stepped_up_at=None)
            )
            if revoked.rowcount != 1:
                return None
            database.add(successor)
    return IssuedSession(token=raw_token, session=_session_data(successor))


async def record_step_up(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    session_id: str,
    user_id: str,
    now: datetime | None = None,
) -> bool:
    """Mark this session as having just proved a second factor (R-AUTH-21).

    Kept on the session rather than in memory so it survives a restart the way
    the session itself does, and so revoking a device also revokes whatever
    step-up that device had earned.
    """
    try:
        db_session_id = UUID(session_id)
        db_user_id = UUID(user_id)
    except (ValueError, TypeError, AttributeError):
        return False
    stepped_at = now or datetime.now(timezone.utc)
    async with session_factory() as database:
        async with database.begin():
            result = await database.execute(
                update(AuthSession)
                .where(
                    AuthSession.id == db_session_id,
                    AuthSession.user_id == db_user_id,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > stepped_at,
                )
                .values(stepped_up_at=stepped_at)
            )
            return result.rowcount == 1


async def revoke_session(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    session_id: str,
    user_id: str,
    now: datetime | None = None,
) -> bool:
    try:
        db_session_id = UUID(session_id)
        db_user_id = UUID(user_id)
    except (ValueError, TypeError, AttributeError):
        return False
    async with session_factory() as database:
        async with database.begin():
            result = await database.execute(
                update(AuthSession)
                .where(
                    AuthSession.id == db_session_id,
                    AuthSession.user_id == db_user_id,
                    AuthSession.revoked_at.is_(None),
                )
                .values(revoked_at=now or datetime.now(timezone.utc))
            )
            return result.rowcount == 1


async def revoke_sessions(
    database: AsyncSession,
    *,
    user_id: str | UUID,
    now: datetime | None = None,
) -> int:
    """Revoke every live session of an account inside the caller's transaction.

    A password reset or change wants this to commit with the new credential,
    or not at all: a crash between the two would leave a committed password
    and every old device still signed in (#607), which is the one outcome
    R-AUTH-10 exists to rule out.
    """
    result = await database.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == UUID(str(user_id)),
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now or datetime.now(timezone.utc))
    )
    return int(result.rowcount or 0)


async def revoke_all_sessions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    now: datetime | None = None,
) -> int:
    """`revoke_sessions` in a transaction of its own, for callers that have none."""
    async with session_factory() as database:
        async with database.begin():
            return await revoke_sessions(database, user_id=user_id, now=now)


async def list_active_sessions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    now: datetime | None = None,
) -> list[SessionData]:
    """The devices a resolution would still accept, newest use first.

    Filtered on the idle window as well as the stored expiry, so the list
    matches what signing in from that device would actually find: a session
    the idle rule has ended is gone, not shown as revocable.
    """
    checked_at = now or datetime.now(timezone.utc)
    async with session_factory() as database:
        records = (
            await database.scalars(
                select(AuthSession)
                .where(
                    AuthSession.user_id == UUID(user_id),
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > checked_at,
                    AuthSession.idle_expires_at > checked_at,
                )
                .order_by(AuthSession.last_used_at.desc())
            )
        ).all()
        return [_session_data(record) for record in records]
