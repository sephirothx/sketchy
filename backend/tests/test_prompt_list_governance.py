"""Prompt-list governance schema reserved for private/unlisted UGC."""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import (
    Base,
    PromptList,
    PromptListRevision,
    PromptListRevisionTag,
    PromptTag,
    User,
    generate_uuid,
)

pytestmark = pytest.mark.asyncio


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


async def test_user_list_defaults_are_private_owned_and_actively_moderated():
    factory, engine = await _database()
    try:
        owner_id = generate_uuid()
        async with factory() as session:
            async with session.begin():
                session.add(User(id=owner_id, display_name="Owner"))
                prompt_list = PromptList(
                    slug="owners-list",
                    name="Owner's list",
                    owner_user_id=owner_id,
                    is_bundled=False,
                )
                session.add(prompt_list)
            await session.refresh(prompt_list)
            assert prompt_list.visibility == "private"
            assert prompt_list.moderation_state == "active"
            assert prompt_list.share_code is None
            assert prompt_list.created_at is not None
            assert prompt_list.updated_at is not None

        async with factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    session.add(
                        PromptList(
                            slug="unshareable",
                            name="Unshareable",
                            owner_user_id=owner_id,
                            is_bundled=False,
                            visibility="unlisted",
                        )
                    )

        async with factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    session.add(
                        PromptList(
                            slug="owned-official",
                            name="Owned official",
                            owner_user_id=owner_id,
                            is_bundled=True,
                            visibility="public",
                        )
                    )
    finally:
        await engine.dispose()


async def test_unlisted_share_provenance_and_tags_are_structured():
    factory, engine = await _database()
    try:
        owner_id = generate_uuid()
        async with factory() as session:
            async with session.begin():
                session.add(User(id=owner_id, display_name="Owner"))
                source = PromptList(
                    slug="source-list",
                    name="Source",
                    owner_user_id=owner_id,
                    is_bundled=False,
                    visibility="unlisted",
                    share_code="SOURCE123",
                )
                fork = PromptList(
                    slug="fork-list",
                    name="Fork",
                    owner_user_id=owner_id,
                    is_bundled=False,
                )
                session.add_all([source, fork])
                await session.flush()
                source_revision = PromptListRevision(
                    prompt_list_id=source.id,
                    version=1,
                    language="en",
                    content_hash="a" * 64,
                )
                session.add(source_revision)
                await session.flush()
                fork_revision = PromptListRevision(
                    prompt_list_id=fork.id,
                    forked_from_revision_id=source_revision.id,
                    version=1,
                    language="en",
                    content_hash="b" * 64,
                )
                tag = PromptTag(slug="animals", name="Animals")
                session.add_all([fork_revision, tag])
                await session.flush()
                session.add(
                    PromptListRevisionTag(
                        revision_id=fork_revision.id,
                        tag_id=tag.id,
                    )
                )

        async with factory() as session:
            stored = await session.scalar(
                select(PromptListRevision).where(
                    PromptListRevision.prompt_list_id == fork.id
                )
            )
            assert stored is not None
            assert stored.forked_from_revision_id == source_revision.id
            assert (
                await session.scalar(select(PromptListRevisionTag.tag_id))
            ) == tag.id
    finally:
        await engine.dispose()
