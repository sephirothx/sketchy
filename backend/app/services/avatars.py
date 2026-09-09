"""Uploading, serving and removing a player's picture (#573).

Everything that writes an avatar goes through here, so the limits, the
audit row and the moderator's block are enforced once regardless of which
route asked. Guests are refused at the door: R-ACCT-05 is why a name in the
player list is either a claimed account or an unclaimed guest, and a picture
on a guest would break exactly that.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.avatars import (
    avatar_reupload_block,
    AvatarError,
    avatar_key_for,
    inspect_avatar,
)
from app.db.models import (
    AuditEvent,
    UploadedAvatarAsset,
    User,
    UserWarning,
    generate_uuid,
)
from app.domain_values import AccountState, AuditTargetType


class AvatarBlocked(AvatarError):
    """A moderator removed this account's picture; no upload until `until`."""

    def __init__(self, until: datetime):
        super().__init__(
            "A moderator removed your picture. You can upload another on "
            f"{until.strftime('%d %b %Y')}."
        )
        self.until = until


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


async def _registered(session: AsyncSession, user_id: UUID) -> User:
    # Locked so an upload that passed authentication before a deletion
    # cannot commit after it (app.auth.erasure) - FOR UPDATE rather than
    # shared, because this transaction writes the row it locks.
    user = await session.get(User, user_id, with_for_update=True)
    if user is None or user.state == AccountState.DELETED.value:
        raise AvatarError("account not found")
    if user.state != AccountState.REGISTERED.value:
        raise AvatarError("Create an account to choose a picture.")
    return user


def _audit(
    session: AsyncSession,
    *,
    event_type: str,
    actor_id: UUID | None,
    target_id: UUID,
    details: dict,
    request_id: str | None,
    ip_hash: str | None,
) -> None:
    session.add(
        AuditEvent(
            id=generate_uuid(),
            event_type=event_type,
            actor_user_id=actor_id,
            target_user_id=target_id,
            target_type=AuditTargetType.USER.value,
            target_id=str(target_id),
            request_id=request_id,
            ip_hash=ip_hash,
            details=details,
        )
    )


async def set_avatar(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str | UUID,
    payload: bytes,
    request_id: str | None = None,
    ip_hash: str | None = None,
    now: datetime | None = None,
) -> str:
    """Store `payload` as the account's picture and return its key."""
    at = now or datetime.now(timezone.utc)
    content_type, width, height = inspect_avatar(payload)
    key = avatar_key_for(payload, content_type)
    db_user_id = UUID(str(user_id))
    async with session_factory() as session:
        async with session.begin():
            user = await _registered(session, db_user_id)
            blocked_until = _aware(user.avatar_upload_blocked_until)
            if blocked_until is not None and blocked_until > at:
                raise AvatarBlocked(blocked_until)
            # One picture per account: the old row goes with the old key.
            await session.execute(
                delete(UploadedAvatarAsset).where(UploadedAvatarAsset.user_id == db_user_id)
            )
            session.add(
                UploadedAvatarAsset(
                    id=generate_uuid(),
                    user_id=db_user_id,
                    object_key=key,
                    content_type=content_type,
                    byte_size=len(payload),
                    width=width,
                    height=height,
                    checksum_sha256=key.split(".")[0],
                    payload=payload,
                    created_at=at,
                )
            )
            user.avatar_key = key
            user.updated_at = at
            _audit(
                session,
                event_type="avatar.uploaded",
                actor_id=db_user_id,
                target_id=db_user_id,
                details={"key": key, "byte_size": len(payload)},
                request_id=request_id,
                ip_hash=ip_hash,
            )
    return key


def _removal_notice(wait: timedelta, until: datetime | None) -> str:
    """What the player is told when a moderator takes their picture down.

    The wait is the part they can act on, so it is what the sentence ends
    with. A first removal has none: they may put another picture up straight
    away, and saying so is what keeps the notice from reading as a punishment
    it is not.
    """
    head = "A moderator removed the picture on your account."
    if wait == timedelta(0) or until is None:
        return f"{head} You can upload another one now."
    return f"{head} You can upload another one on {until.strftime('%d %b %Y')}."


@dataclass(frozen=True)
class AvatarRemoval:
    """What a removal did, for a caller that has to announce it.

    `warning_id` is the notice the player will be shown. A removal they are
    never told about is the thing this exists to prevent, so the notice is
    written in the same transaction as the removal: there is no state in which
    the picture is gone and nothing owes them an explanation (R-AVA-08).
    """

    had_one: bool
    warning_id: UUID | None = None
    blocked_until: datetime | None = None


async def _prior_moderator_removals(session: AsyncSession, user_id: UUID) -> int:
    """How many pictures a moderator has already taken down from this account.

    Read from the append-only ledger, which is where the removals actually
    are. A player taking their own picture down is not counted: it is not a
    punishment and sets no block (R-AVA-04), so it must never move an account
    up the ladder.

    Bounded in practice by how many pictures one account has had removed,
    which is a handful at the very worst - and an account reaching the top of
    the ladder is one a moderator is already looking at for other reasons.
    """
    rows = (
        await session.scalars(
            select(AuditEvent.details).where(
                AuditEvent.event_type == "avatar.removed",
                AuditEvent.target_user_id == user_id,
            )
        )
    ).all()
    return sum(1 for details in rows if (details or {}).get("by_moderator"))


async def remove_avatar(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str | UUID,
    actor_id: str | UUID | None,
    by_moderator: bool = False,
    report_id: str | UUID | None = None,
    request_id: str | None = None,
    ip_hash: str | None = None,
    now: datetime | None = None,
) -> AvatarRemoval:
    """Take the picture down, and tell its owner that somebody did.

    A moderator's removal blocks re-upload for a while that grows with how
    many of this account's pictures they have taken down before
    (`avatar_reupload_block`), and writes the notice that says so. Both happen
    here rather than in the caller so neither can happen without the other.

    `had_one` is False when there was nothing to remove - the block is still
    applied in that case, because the report was about a picture the player
    may have replaced since.
    """
    at = now or datetime.now(timezone.utc)
    db_user_id = UUID(str(user_id))
    async with session_factory() as session:
        async with session.begin():
            user = await session.get(User, db_user_id)
            if user is None:
                raise AvatarError("account not found")
            removed = await session.execute(
                delete(UploadedAvatarAsset).where(UploadedAvatarAsset.user_id == db_user_id)
            )
            had_one = bool(removed.rowcount) or user.avatar_key is not None
            warning_id: UUID | None = None
            blocked_until: datetime | None = None
            user.avatar_key = None
            user.updated_at = at
            wait = None
            if by_moderator:
                # How many a moderator has taken down from this account before
                # this one, counted from the ledger rather than from a column
                # kept beside it: the removals are the facts, and a tally can
                # only ever disagree with them.
                wait = avatar_reupload_block(
                    await _prior_moderator_removals(session, db_user_id)
                )
                user.avatar_upload_blocked_until = at + wait
            _audit(
                session,
                event_type="avatar.removed",
                actor_id=UUID(str(actor_id)) if actor_id else None,
                target_id=db_user_id,
                details={
                    "by_moderator": by_moderator,
                    **({"report_id": str(report_id)} if report_id else {}),
                    **(
                        {
                            "blocked_until": (
                                user.avatar_upload_blocked_until.isoformat()
                            ),
                            "block_days": wait.days if wait is not None else 0,
                        }
                        if by_moderator
                        else {}
                    ),
                },
                request_id=request_id,
                ip_hash=ip_hash,
            )
            if by_moderator:
                # Issued as a Warning, which is the notice machinery a player
                # already meets: shown once, acknowledged, pushed to a live
                # socket and waiting on the next visit otherwise. A removal
                # restricts something a warning does not, so what it restricts
                # and until when is said in the words themselves - there is no
                # moderator sentence to carry it, this being one button rather
                # than a decision with a note.
                # Only when there is actually a wait. A first removal costs
                # none, and `avatar_upload_blocked_until` is then simply now -
                # a date a caller would otherwise report as a block.
                blocked_until = (
                    user.avatar_upload_blocked_until if wait > timedelta(0) else None
                )
                warning_id = generate_uuid()
                session.add(
                    UserWarning(
                        id=warning_id,
                        kind="avatar_removal",
                        user_id=db_user_id,
                        issued_by_user_id=UUID(str(actor_id)) if actor_id else None,
                        reason=_removal_notice(wait, blocked_until),
                        source_report_id=UUID(str(report_id)) if report_id else None,
                        created_at=at,
                    )
                )
    return AvatarRemoval(
        had_one=had_one, warning_id=warning_id, blocked_until=blocked_until
    )


async def read_avatar(
    session_factory: async_sessionmaker[AsyncSession], *, key: str
) -> tuple[bytes, str] | None:
    """The bytes behind a key and their content type, or None."""
    async with session_factory() as session:
        asset = await session.scalar(
            select(UploadedAvatarAsset).where(UploadedAvatarAsset.object_key == key)
        )
        if asset is None:
            return None
        return bytes(asset.payload), asset.content_type


async def delete_avatars_for(
    session: AsyncSession, user_ids: list[UUID] | set[UUID]
) -> None:
    """Deletion (R-PRIV-05): the picture goes with the account, in its transaction."""
    if not user_ids:
        return
    await session.execute(
        delete(UploadedAvatarAsset).where(UploadedAvatarAsset.user_id.in_(list(user_ids)))
    )
