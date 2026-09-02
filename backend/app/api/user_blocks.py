"""Persistent block, unblock, and block-list endpoints."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.audit import audit_coordinates
from app.auth.blocks import BlockService
from app.services.friends import FriendService
from app.domain_values import AuditTargetType
from app.db.models import (
    AuditEvent,
    IdentityAlias,
    User,
    UserBlock,
    generate_uuid,
)
from app.domain_values import AccountState


MAX_BLOCKS_PER_ACCOUNT = 1_000


class BlockBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    user_id: UUID = Field(alias="userId")


def _block_payload(block: UserBlock, target: User) -> dict:
    return {
        "userId": str(target.id),
        "username": target.username,
        "displayName": target.display_name,
        "isAnonymous": target.is_anonymous,
        "createdAt": block.created_at.isoformat(),
    }


async def _target_user(session: AsyncSession, user_id: UUID) -> User | None:
    target = await session.get(User, user_id)
    if target is not None and target.state == AccountState.MERGED.value:
        canonical_id = await session.scalar(
            select(IdentityAlias.target_user_id).where(
                IdentityAlias.source_user_id == target.id
            )
        )
        target = await session.get(User, canonical_id) if canonical_id else None
    if target is None or target.state == AccountState.DELETED.value:
        return None
    return target


def create_user_blocks_router(
    session_factory: async_sessionmaker[AsyncSession],
    block_service: BlockService,
    friend_service: FriendService | None = None,
    # Called with each side of a friendship a block has just revoked, so their
    # lists stop showing a join capability that is gone.
    on_friends_changed: Callable[[str], Awaitable[None]] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/users/me/blocks")

    def blocker_id(request: Request) -> UUID:
        value = getattr(request.state, "user_id", None)
        if not value:
            raise HTTPException(status_code=401, detail="Sign in first.")
        return UUID(value)

    @router.get("")
    async def list_blocks(request: Request):
        current_id = blocker_id(request)
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(UserBlock, User)
                    .join(User, User.id == UserBlock.blocked_user_id)
                    .where(UserBlock.blocker_user_id == current_id)
                    .order_by(UserBlock.created_at, UserBlock.blocked_user_id)
                )
            ).all()
            return {"blocks": [_block_payload(block, target) for block, target in rows]}

    @router.post("")
    async def block_user(body: BlockBody, request: Request, response: Response):
        current_id = blocker_id(request)
        request_id, ip_hash = await audit_coordinates(request, session_factory)

        unfriended = False
        async with session_factory() as session:
            try:
                async with session.begin():
                    target = await _target_user(session, body.user_id)
                    if target is None:
                        raise HTTPException(status_code=404, detail="No such player.")
                    if current_id == target.id:
                        raise HTTPException(
                            status_code=422, detail="You cannot block yourself."
                        )
                    existing = await session.scalar(
                        select(UserBlock).where(
                            UserBlock.blocker_user_id == current_id,
                            UserBlock.blocked_user_id == target.id,
                        )
                    )
                    if existing is not None:
                        block_service.invalidate(str(target.id))
                        response.status_code = 200
                        return _block_payload(existing, target)
                    count = await session.scalar(
                        select(func.count(UserBlock.blocked_user_id)).where(
                            UserBlock.blocker_user_id == current_id
                        )
                    )
                    if (count or 0) >= MAX_BLOCKS_PER_ACCOUNT:
                        raise HTTPException(
                            status_code=409, detail="Your block list is full."
                        )
                    block = UserBlock(
                        blocker_user_id=current_id,
                        blocked_user_id=target.id,
                    )
                    session.add(block)
                    if friend_service is not None:
                        # In the same transaction as the block itself. A
                        # surviving friendship is a private-room join
                        # capability (#529) that the blocker has just tried to
                        # revoke, so it cannot outlive the block by even one
                        # failed commit. Deleted rather than tombstoned: the
                        # block is now the durable record, and unblocking must
                        # not silently restore a friendship neither party
                        # re-agreed to.
                        unfriended = await friend_service.forget_pair(
                            session, current_id, target.id
                        )
                    session.add(
                        AuditEvent(
                            id=generate_uuid(),
                            event_type="block.created",
                            actor_user_id=current_id,
                            target_user_id=target.id,
                            target_type=AuditTargetType.USER.value,
                            target_id=str(target.id),
                            request_id=request_id,
                            ip_hash=ip_hash,
                        )
                    )
                    await session.flush()
            except IntegrityError:
                # Concurrent duplicate inserts converge on the same idempotent
                # result instead of surfacing the unique constraint.
                async with session_factory() as retry_session:
                    row = await retry_session.execute(
                        select(UserBlock, User)
                        .join(User, User.id == UserBlock.blocked_user_id)
                        .where(
                            UserBlock.blocker_user_id == current_id,
                            UserBlock.blocked_user_id == target.id,
                        )
                    )
                    pair = row.one_or_none()
                    if pair is None:
                        raise
                    block_service.invalidate(str(target.id))
                    response.status_code = 200
                    return _block_payload(*pair)

        block_service.invalidate(str(target.id))
        # After the commit, and only where a friendship actually went. Telling
        # a stranger their lists moved would make a block a way to ask whether
        # they were a friend.
        if unfriended and on_friends_changed is not None:
            await on_friends_changed(str(current_id))
            await on_friends_changed(str(target.id))
        response.status_code = 201
        return _block_payload(block, target)

    @router.delete("/{user_id}", status_code=204)
    async def unblock_user(user_id: UUID, request: Request, response: Response):
        current_id = blocker_id(request)
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        async with session_factory() as session:
            async with session.begin():
                target = await _target_user(session, user_id)
                target_id = target.id if target is not None else user_id
                block = await session.scalar(
                    select(UserBlock).where(
                        UserBlock.blocker_user_id == current_id,
                        UserBlock.blocked_user_id == target_id,
                    )
                )
                if block is None:
                    response.status_code = 204
                    return None
                await session.execute(
                    delete(UserBlock).where(
                        UserBlock.blocker_user_id == current_id,
                        UserBlock.blocked_user_id == target_id,
                    )
                )
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="block.deleted",
                        actor_user_id=current_id,
                        target_user_id=target_id,
                        target_type=AuditTargetType.USER.value,
                        target_id=str(target_id),
                        request_id=request_id,
                        ip_hash=ip_hash,
                    )
                )
        block_service.invalidate(str(target_id))
        return None

    return router
