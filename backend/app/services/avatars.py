"""Uploading, serving and removing a player's picture (#573).

Everything that writes an avatar goes through here, so the limits, the
audit row and the moderator's block are enforced once regardless of which
route asked. Guests are refused at the door: R-ACCT-05 is why a name in the
player list is either a claimed account or an unclaimed guest, and a picture
on a guest would break exactly that.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.avatars import (
    AVATAR_CONTENT_TYPE,
    AVATAR_REUPLOAD_BLOCK,
    AvatarError,
    avatar_key_for,
    inspect_avatar,
)
from app.db.models import AuditEvent, UploadedAvatarAsset, User, generate_uuid
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
    user = await session.get(User, user_id)
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
    width, height = inspect_avatar(payload)
    key = avatar_key_for(payload)
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
                    content_type=AVATAR_CONTENT_TYPE,
                    byte_size=len(payload),
                    width=width,
                    height=height,
                    checksum_sha256=key.removesuffix(".png"),
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
) -> bool:
    """Take the picture down. A moderator's removal also blocks re-upload.

    Returns False when there was nothing to remove - the block is still
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
            user.avatar_key = None
            user.updated_at = at
            if by_moderator:
                user.avatar_upload_blocked_until = at + AVATAR_REUPLOAD_BLOCK
            _audit(
                session,
                event_type="avatar.removed",
                actor_id=UUID(str(actor_id)) if actor_id else None,
                target_id=db_user_id,
                details={
                    "by_moderator": by_moderator,
                    **({"report_id": str(report_id)} if report_id else {}),
                    **(
                        {"blocked_until": user.avatar_upload_blocked_until.isoformat()}
                        if by_moderator
                        else {}
                    ),
                },
                request_id=request_id,
                ip_hash=ip_hash,
            )
    return had_one


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
